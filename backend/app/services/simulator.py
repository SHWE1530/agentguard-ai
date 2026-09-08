"""The simulated autonomous agent.

The agent proposes actions. It has no authority to execute them -- every
attempt goes through the safety pipeline, which decides. When the pipeline
stops the agent, the simulator halts.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.app.agent.scenarios import SCENARIOS, Scenario
from backend.app.config import SIMULATION_STEP_DELAY
from backend.app.database.db import session as new_session
from backend.app.database.models import Agent, Incident, Session_, Task, utcnow
from backend.app.services import audit, recovery, sandbox
from backend.app.services.events import hub
from backend.app.services.pipeline import evaluate_action

AGENT_NAME = "OpsAssist-Agent"
AGENT_PURPOSE = "Perform safe IT maintenance tasks."

# session_id -> asyncio.Task
_running: Dict[str, asyncio.Task] = {}


def _schedule(session_id: str, coro) -> bool:
    """Start a background coroutine on the app's event loop.

    Sync FastAPI endpoints execute in a worker thread with no running loop, so
    the loop captured at startup is used. Returns False when no loop is
    available (e.g. the synchronous test client), in which case the caller is
    expected to drive the actions itself.
    """
    loop = hub.loop
    if loop is None or not loop.is_running():
        coro.close()
        return False
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        _running[session_id] = loop.create_task(coro)
    else:
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        _running[session_id] = fut  # type: ignore[assignment]
    return True


def ensure_agent(db: Session) -> Agent:
    agent = db.query(Agent).filter(Agent.name == AGENT_NAME).one_or_none()
    if agent is None:
        agent = Agent(name=AGENT_NAME, purpose=AGENT_PURPOSE, status="IDLE")
        db.add(agent)
        db.commit()
    return agent


def start_simulation(db: Session, scenario_key: str) -> Dict[str, Any]:
    """Create the session + task rows and schedule the background run."""
    if scenario_key not in SCENARIOS:
        raise ValueError(f"Unknown scenario '{scenario_key}'. "
                         f"Valid: {', '.join(SCENARIOS)}")
    scenario = SCENARIOS[scenario_key]

    agent = ensure_agent(db)
    sandbox.ensure_baseline(db)

    agent.status = "RUNNING"
    sess = Session_(agent_id=agent.id, scenario=scenario_key, status="RUNNING")
    db.add(sess)
    db.commit()

    task = Task(session_id=sess.id, description=scenario.task)
    db.add(task)
    db.commit()

    audit.record(db, "AGENT_STARTED", agent_id=agent.id, agent_name=agent.name,
                 session_id=sess.id, reason=f"Agent started for scenario '{scenario.name}'.")
    audit.record(db, "TASK_STARTED", agent_id=agent.id, agent_name=agent.name,
                 session_id=sess.id, reason=scenario.task)
    hub.publish("simulation_started", {
        "session_id": sess.id, "agent_id": agent.id, "agent_name": agent.name,
        "scenario": scenario_key, "scenario_name": scenario.name,
        "task": scenario.task, "planned_sequence": scenario.sequence})

    _schedule(sess.id, _run(sess.id, scenario))

    return {
        "session_id": sess.id, "task_id": task.id, "agent_id": agent.id,
        "agent_name": agent.name, "scenario": scenario_key,
        "scenario_name": scenario.name, "task": scenario.task,
        "planned_sequence": scenario.sequence, "status": "RUNNING",
    }


async def _run(session_id: str, scenario: Scenario) -> None:
    """Background driver. Uses its own DB session (never the request's)."""
    db = new_session()
    try:
        sess = db.get(Session_, session_id)
        agent = db.get(Agent, sess.agent_id)
        task = db.query(Task).filter(Task.session_id == session_id).one()

        prev: Optional[str] = None
        counts: Dict[str, int] = {}
        halted = False

        for step, action_type in enumerate(scenario.sequence):
            await asyncio.sleep(SIMULATION_STEP_DELAY)
            db.refresh(sess)
            if sess.status not in ("RUNNING",):
                halted = True
                break

            result = evaluate_action(
                db, agent=agent, sess=sess, task_id=task.id, action_type=action_type,
                step_index=step, prev_action=prev,
                repeated_count=counts.get(action_type, 0),
                seconds_since_prev=SIMULATION_STEP_DELAY)

            counts[action_type] = counts.get(action_type, 0) + 1
            prev = action_type

            db.refresh(sess)
            if sess.status in ("PAUSED", "AWAITING_APPROVAL", "STOPPED"):
                halted = True
                break

        db.refresh(sess)
        if not halted and sess.status == "RUNNING":
            sess.status = "COMPLETED"
            sess.ended_at = utcnow()
            agent.status = "IDLE"
            db.commit()
            audit.record(db, "SESSION_COMPLETED", agent_id=agent.id, agent_name=agent.name,
                         session_id=sess.id,
                         reason=f"Scenario '{scenario.name}' completed without intervention.")
            hub.publish("simulation_finished", {"session_id": sess.id, "status": "COMPLETED"})
        else:
            hub.publish("simulation_finished", {"session_id": sess.id, "status": sess.status})

        # Automatic recovery for scenarios that produce a critical incident.
        if scenario.auto_recover:
            await asyncio.sleep(SIMULATION_STEP_DELAY)
            inc = (db.query(Incident)
                     .filter(Incident.session_id == sess.id, Incident.status == "OPEN")
                     .order_by(Incident.risk_score.desc()).first())
            if inc is not None:
                recovery.run_recovery(db, inc)

    except Exception as exc:  # pragma: no cover - defensive
        hub.publish("error", {"session_id": session_id,
                              "message": f"Simulation failed: {exc}"})
    finally:
        _running.pop(session_id, None)
        db.close()


async def resume_after_approval(session_id: str) -> None:
    """Continue a session that was held for a human decision."""
    db = new_session()
    try:
        sess = db.get(Session_, session_id)
        if sess is None:
            return
        scenario = SCENARIOS.get(sess.scenario)
        if scenario is None:
            return
        agent = db.get(Agent, sess.agent_id)
        sess.status = "COMPLETED"
        sess.ended_at = utcnow()
        agent.status = "IDLE"
        db.commit()
        audit.record(db, "SESSION_COMPLETED", agent_id=agent.id, agent_name=agent.name,
                     session_id=sess.id, reason="Session closed after the human decision.")
        hub.publish("simulation_finished", {"session_id": sess.id, "status": "COMPLETED"})
        hub.publish("agent_status", {"agent_id": agent.id, "status": "IDLE",
                                     "session_id": sess.id})
    finally:
        db.close()


def is_running(session_id: str) -> bool:
    return session_id in _running
