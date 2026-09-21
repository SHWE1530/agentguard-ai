"""The simulated autonomous agents.

An agent PROPOSES actions; it has no authority to execute them. Every attempt
goes through the safety pipeline, which decides. When the pipeline halts or
holds the agent, the simulator stops; steps that were never attempted are
reported as PREVENTED.

The scenario plan is persisted on the session (plan_json + cursor), so a
session held for human approval resumes exactly where it stopped.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.agent import scenarios as scen
from backend.app.agent.profiles import AGENTS
from backend.app.config import SIMULATION_STEP_DELAY
from backend.app.database.db import session as new_session
from backend.app.database.models import (
    Action, Agent, DriftSnapshot, Incident, Session_, Task, utcnow,
)
from backend.app.services import audit, baseline, recovery, sandbox, trust as trust_svc
from backend.app.services.events import hub
from backend.app.services.pipeline import evaluate_action

DEFAULT_AGENT = "OpsAssist-Agent"
_running: Dict[str, Any] = {}


# --------------------------------------------------------------- scheduling
def _schedule(key: str, coro) -> bool:
    """Start a coroutine on the app's event loop (sync endpoints run in worker threads)."""
    loop = hub.loop
    if loop is None or not loop.is_running():
        coro.close()
        return False
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        _running[key] = loop.create_task(coro)
    else:
        _running[key] = asyncio.run_coroutine_threadsafe(coro, loop)
    return True


def is_running(session_id: str) -> bool:
    return session_id in _running


# ------------------------------------------------------------------ agents
def ensure_agent(db: Session, name: str = DEFAULT_AGENT) -> Agent:
    agent = db.query(Agent).filter(Agent.name == name).one_or_none()
    if agent is None:
        prof = AGENTS[name]
        agent = Agent(name=name, purpose=prof.purpose, status="IDLE")
        db.add(agent)
        db.commit()
    baseline.ensure(db, agent)
    return agent


def ensure_all_agents(db: Session) -> List[Agent]:
    return [ensure_agent(db, n) for n in AGENTS]


# ---------------------------------------------------------------- sessions
def create_session(db: Session, scenario_key: str) -> Tuple[Session_, Task, Agent, scen.Scenario]:
    sc = scen.get(scenario_key)
    agent = ensure_agent(db, sc.agent)
    sandbox.ensure_baseline(db)
    agent.status = "RUNNING"
    sess = Session_(agent_id=agent.id, scenario=sc.key, status="RUNNING",
                    plan_json=json.dumps([asdict(s) for s in sc.steps]), cursor=0, fault=sc.fault)
    db.add(sess)
    db.commit()
    task = Task(session_id=sess.id, description=sc.task)
    db.add(task)
    db.commit()
    audit.record(db, "AGENT_STARTED", agent_id=agent.id, agent_name=agent.name, session_id=sess.id,
                 reason=f"Agent started for scenario '{sc.name}'.")
    audit.record(db, "TASK_STARTED", agent_id=agent.id, agent_name=agent.name, session_id=sess.id, reason=sc.task)
    hub.publish("simulation_started", {
        "session_id": sess.id, "agent_id": agent.id, "agent_name": agent.name, "scenario": sc.key,
        "scenario_name": sc.name, "task": sc.task, "planned_sequence": [s.action for s in sc.steps],
        "expected_intervention": sc.expected_intervention})
    return sess, task, agent, sc


def start_simulation(db: Session, scenario_key: str) -> Dict[str, Any]:
    sess, task, agent, sc = create_session(db, scenario_key)
    _schedule(sess.id, _run(sess.id))
    return {"session_id": sess.id, "task_id": task.id, "agent_id": agent.id, "agent_name": agent.name,
            "scenario": sc.key, "scenario_name": sc.name, "task": sc.task,
            "planned_sequence": [s.action for s in sc.steps], "status": "RUNNING"}


def advance(db: Session, sess: Session_, agent: Agent, task: Task) -> Tuple[Optional[Dict[str, Any]], bool]:
    """Execute the next planned step. Returns (result, stop)."""
    db.refresh(sess)
    plan = json.loads(sess.plan_json)
    if sess.status != "RUNNING" or sess.cursor >= len(plan):
        return None, True
    idx = sess.cursor
    st = plan[idx]
    sess.cursor = idx + 1
    db.commit()
    res = evaluate_action(db, agent=agent, sess=sess, task_id=task.id, action_type=st["action"],
                          step_index=idx, dt=st["dt"], failed=st["failed"], content=st["content"],
                          bypass_guard=st["bypass"])
    db.refresh(sess)
    return res, sess.status in ("PAUSED", "AWAITING_APPROVAL", "STOPPED")


def finish_session(db: Session, sess: Session_, agent: Agent) -> None:
    """Close out a session that ran to the end, or report how it was halted."""
    db.refresh(sess)
    plan = json.loads(sess.plan_json)
    prevented = [p["action"] for p in plan[sess.cursor:]] if sess.status != "COMPLETED" else []
    if sess.status == "RUNNING":
        sess.status = "COMPLETED"
        sess.ended_at = utcnow()
        agent.status = "IDLE"
        db.commit()
        audit.record(db, "SESSION_COMPLETED", agent_id=agent.id, agent_name=agent.name, session_id=sess.id,
                     reason="Session completed; every planned action was attempted.")
    _drift_snapshot(db, sess, agent)
    learned = baseline.consider_session(db, sess)      # always audited: accepted or rejected with reasons
    trust_svc.snapshot(db, agent.id, f"SESSION_{sess.status}", sess.id)
    hub.publish("simulation_finished", {"session_id": sess.id, "status": sess.status,
                                        "prevented_steps": prevented, "baseline": learned,
                                        "agent_status": agent.status})


def _drift_snapshot(db: Session, sess: Session_, agent: Agent) -> None:
    acts = db.query(Action).filter(Action.session_id == sess.id).order_by(Action.step_index.asc()).all()
    if not acts:
        return
    scores, thr, ref = [], 0.45, 0.2
    for a in acts:
        d = json.loads(a.risk_factors_json).get("drift", {})
        if d and not d.get("insufficient"):
            scores.append(d["score"])
        thr = json.loads(a.risk_factors_json).get("drift_threshold", thr)
    fp = baseline.active_fingerprint(db, agent)
    ref = fp.ref_drift.get("mean", ref)
    if scores:
        db.add(DriftSnapshot(agent_id=agent.id, session_id=sess.id, peak=max(scores), final=scores[-1],
                             threshold=thr, reference_mean=ref))
        db.commit()


def auto_recover(db: Session, sess: Session_, sc: Optional[scen.Scenario]) -> Optional[Dict[str, Any]]:
    if not sc or not sc.auto_recover:
        return None
    inc = (db.query(Incident).filter(Incident.session_id == sess.id, Incident.status == "OPEN")
             .order_by(Incident.risk_score.desc()).first())
    if inc is None:
        return None
    return recovery.run_recovery(db, inc, fault=sc.fault)


# ------------------------------------------------------------------ async
async def _run(session_id: str, delay_scale: float = 1.0) -> None:
    """Background driver. Uses its own DB session (never the request's)."""
    db = new_session()
    try:
        sess = db.get(Session_, session_id)
        agent = db.get(Agent, sess.agent_id)
        task = db.query(Task).filter(Task.session_id == session_id).one()
        sc = scen.SCENARIOS.get(sess.scenario)
        pace = (sc.pace if sc else 1.0) * delay_scale
        while True:
            await asyncio.sleep(SIMULATION_STEP_DELAY * pace)
            _, stop = advance(db, sess, agent, task)
            if stop:
                break
        db.refresh(sess)
        if sess.status == "AWAITING_APPROVAL":
            hub.publish("simulation_paused", {"session_id": session_id, "status": sess.status})
            return
        finish_session(db, sess, agent)
        if sc and sc.auto_recover:
            await asyncio.sleep(SIMULATION_STEP_DELAY)
            auto_recover(db, sess, sc)
    except Exception as exc:  # pragma: no cover - defensive
        hub.publish("error", {"session_id": session_id, "message": f"Simulation failed: {exc}"})
    finally:
        _running.pop(session_id, None)
        db.close()


async def resume_after_decision(session_id: str) -> None:
    """Continue a session that was held for a human decision."""
    await _run(session_id, delay_scale=1.0)


# -------------------------------------------------------------------- sync
def run_sync(db: Session, scenario_key: str, approve: Optional[bool] = None,
             decided_by: str = "auto-operator") -> Dict[str, Any]:
    """Run a scenario to completion without timers (tests, seeding, demo reset)."""
    sess, task, agent, sc = create_session(db, scenario_key)
    while True:
        _, stop = advance(db, sess, agent, task)
        if stop:
            db.refresh(sess)
            if sess.status == "AWAITING_APPROVAL" and approve is not None:
                from backend.app.services import approvals
                from backend.app.database.models import Approval
                ap = (db.query(Approval).filter(Approval.session_id == sess.id, Approval.status == "PENDING").first())
                approvals.decide(db, ap.id, approve, decided_by, "auto", schedule=False)
                db.refresh(sess)
                continue
            break
    if sess.status == "AWAITING_APPROVAL":
        return {"session_id": sess.id, "status": sess.status, "recovery": None}
    finish_session(db, sess, agent)
    rec = auto_recover(db, sess, sc)
    db.refresh(sess)
    return {"session_id": sess.id, "status": sess.status, "recovery": rec}
