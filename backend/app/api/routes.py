from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.agent import scenarios as scen
from backend.app.agent.catalog import CATALOG
from backend.app.database.db import get_db
from backend.app.database.models import (
    Action, Agent, Approval, AuditEvent, DriftSnapshot, Incident, Intervention, Session_, Task,
)
from backend.app.schemas.api import (
    ApprovalDecisionRequest, BaselineUpdateRequest, EvaluateActionRequest, RecoverRequest,
    OpenSessionRequest, StartAgentRequest, StartSimulationRequest,
)
from backend.app import config
from backend.app.services import (
    auth as auth_svc, approvals as approval_svc, architecture, audit, baseline, demo, graph, metrics, recovery,
    sandbox, simulator, trust as trust_svc,
)
from backend.app.services.events import hub
from backend.app.services.explanation import explain_incident
from backend.app.services.ml_detector import detector
from backend.app.services.pipeline import action_to_dict, evaluate_action
from backend.app.services.policy_engine import policy_engine

router = APIRouter(prefix="/api")


# -------------------------------------------------------------------- auth
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


@router.get("/auth/config")
def auth_config() -> Dict[str, Any]:
    """Public: tells the login page whether auth is on and whether demo accounts are active."""
    return {"enabled": config.AUTH_ENABLED, "demo_accounts": bool(config.AUTH_ENABLED and auth_svc.USING_DEMO_USERS),
            "demo_hint": [{"user": "judge", "password": "sentinel-demo", "role": "operator"},
                          {"user": "viewer", "password": "sentinel-view", "role": "viewer"}]
            if auth_svc.USING_DEMO_USERS else []}


@router.post("/auth/login")
def login(payload: LoginRequest, request: Request) -> Dict[str, Any]:
    client = request.client.host if request.client else "unknown"
    try:
        res = auth_svc.login(payload.username, payload.password, client)
    except auth_svc.RateLimited:
        raise HTTPException(status_code=429, detail="Too many failed sign-ins. Wait a minute and try again.")
    if res is None:
        raise HTTPException(status_code=401, detail="Incorrect username or password.")
    return res


@router.get("/auth/me")
def me(request: Request) -> Dict[str, Any]:
    user = getattr(request.state, "user", None)
    return {"user": user or "anonymous", "auth_enabled": config.AUTH_ENABLED}


def _who(request: Request, supplied: str) -> str:
    """The authenticated user is the decision-maker; a client-supplied name is only used when auth is off."""
    return getattr(request.state, "user", None) or supplied


# ------------------------------------------------------------------ health
@router.get("/health")
def health(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return {"status": "ok", "time": datetime.utcnow().isoformat(), "model_loaded": detector.ready,
            "policy_version": policy_engine.policy.get("policy_version"),
            "websocket_clients": hub.client_count, "actions_recorded": db.query(Action).count()}


# ------------------------------------------------------------------ agents
def _agent_row(db: Session, a: Agent) -> Dict[str, Any]:
    latest = (db.query(Session_).filter(Session_.agent_id == a.id).order_by(Session_.started_at.desc()).first())
    task = current = None
    if latest:
        t = db.query(Task).filter(Task.session_id == latest.id).first()
        task = t.description if t else None
        last = (db.query(Action).filter(Action.session_id == latest.id).order_by(Action.step_index.desc()).first())
        current = action_to_dict(last) if last else None
    t = trust_svc.compute(db, a.id)
    fp = baseline.active_fingerprint(db, a)
    allowed = policy_engine.allowed_actions(a.name)
    return {
        "id": a.id, "name": a.name, "purpose": a.purpose, "status": a.status,
        "created_at": a.created_at.isoformat(),
        "current_session": latest.id if latest else None, "current_scenario": latest.scenario if latest else None,
        "session_status": latest.status if latest else None, "current_task": task, "current_action": current,
        "trust": t["score"], "trust_band": t["band"], "baseline_version": fp.version,
        "allowed_actions": allowed,
        "restricted_actions": [k for k in CATALOG if k not in allowed],
    }


@router.get("/agents")
def get_agents(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    simulator.ensure_all_agents(db)
    return [_agent_row(db, a) for a in db.query(Agent).order_by(Agent.name).all()]


@router.get("/agents/{agent_id}/profile")
def agent_profile(agent_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    a = db.get(Agent, agent_id)
    if a is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    fp = baseline.active_fingerprint(db, a)
    drift = (db.query(DriftSnapshot).filter(DriftSnapshot.agent_id == a.id)
               .order_by(DriftSnapshot.created_at.asc()).all())[-20:]
    return {
        "agent": _agent_row(db, a), "trust": trust_svc.compute(db, a.id),
        "trust_history": trust_svc.history(db, a.id),
        "drift_history": [{"session_id": d.session_id, "peak": round(d.peak, 3), "final": round(d.final, 3),
                           "threshold": round(d.threshold, 3), "reference": round(d.reference_mean, 3),
                           "t": d.created_at.isoformat()} for d in drift],
        "fingerprint": fp.summary(), "baselines": baseline.history(db, a.id),
    }


@router.post("/agents/{agent_id}/baseline/update")
def baseline_update(agent_id: str, payload: BaselineUpdateRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Offer sessions to the adaptive baseline. Each is accepted or rejected with reasons."""
    a = db.get(Agent, agent_id)
    if a is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    if payload.session_id:
        s = db.get(Session_, payload.session_id)
        if s is None or s.agent_id != a.id:
            raise HTTPException(status_code=404, detail="Session not found for this agent.")
        sessions = [s]
    else:
        sessions = (db.query(Session_).filter(Session_.agent_id == a.id)
                      .order_by(Session_.started_at.desc()).limit(5).all())[::-1]
    results = [baseline.consider_session(db, s) for s in sessions]
    return {"results": results, "active_version": baseline.active_fingerprint(db, a).version,
            "baselines": baseline.history(db, a.id)}


@router.post("/agents/start")
def start_agent(payload: StartAgentRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return simulator.start_simulation(db, payload.scenario)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ------------------------------------------------------------- simulations
@router.get("/scenarios")
def get_scenarios() -> List[dict]:
    return scen.list_scenarios()


@router.post("/simulations/start")
def start_simulation(payload: StartSimulationRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return simulator.start_simulation(db, payload.scenario)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _incident_dict(i: Incident) -> Dict[str, Any]:
    return {"id": i.id, "reference": i.reference, "session_id": i.session_id, "agent_id": i.agent_id,
            "severity": i.severity, "title": i.title, "reason": i.reason, "risk_score": i.risk_score,
            "status": i.status, "kind": i.kind, "recovery_attempts": i.recovery_attempts,
            "trigger_action_id": i.trigger_action_id, "created_at": i.created_at.isoformat(),
            "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None}


@router.get("/simulations/{session_id}")
def get_simulation(session_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    sess = db.get(Session_, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    agent = db.get(Agent, sess.agent_id)
    task = db.query(Task).filter(Task.session_id == sess.id).first()
    actions = db.query(Action).filter(Action.session_id == sess.id).order_by(Action.step_index.asc()).all()
    plan = json.loads(sess.plan_json or "[]")
    return {
        "id": sess.id, "scenario": sess.scenario, "status": sess.status,
        "started_at": sess.started_at.isoformat(), "ended_at": sess.ended_at.isoformat() if sess.ended_at else None,
        "agent": {"id": agent.id, "name": agent.name, "status": agent.status} if agent else None,
        "task": task.description if task else None, "live": simulator.is_running(sess.id),
        "tainted": bool(sess.tainted), "taint": json.loads(sess.taint_json) if sess.taint_json else None,
        "planned_sequence": [p["action"] for p in plan],
        "prevented_steps": [p["action"] for p in plan[sess.cursor:]] if sess.status != "COMPLETED" else [],
        "actions": [action_to_dict(a) for a in actions],
        "incidents": [_incident_dict(i) for i in db.query(Incident).filter(Incident.session_id == sess.id)],
        "approvals": [approval_svc.to_dict(a) for a in db.query(Approval).filter(Approval.session_id == sess.id)],
    }


@router.get("/sessions")
def get_sessions(db: Session = Depends(get_db), limit: int = Query(50, ge=1, le=200)):
    rows = db.query(Session_).order_by(Session_.started_at.desc()).limit(limit).all()
    return [{"id": s.id, "scenario": s.scenario, "status": s.status, "started_at": s.started_at.isoformat(),
             "ended_at": s.ended_at.isoformat() if s.ended_at else None, "tainted": bool(s.tainted),
             "action_count": db.query(Action).filter(Action.session_id == s.id).count()} for s in rows]


@router.post("/sessions/open")
def open_session(payload: OpenSessionRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Integration entry point: an external agent opens a monitored session, then calls
    POST /api/actions/evaluate before EACH tool call and obeys the returned decision."""
    from backend.app.agent.profiles import AGENTS
    from backend.app.services.intent import resolve_task
    if payload.agent_name not in AGENTS or payload.agent_name not in policy_engine.policy["agents"]:
        raise HTTPException(status_code=404, detail=(
            f"Unknown agent '{payload.agent_name}'. Register it in agent/profiles.py and policies/agent_policy.json."))
    agent = simulator.ensure_agent(db, payload.agent_name)
    sandbox.ensure_baseline(db)
    agent.status = "RUNNING"
    sess = Session_(agent_id=agent.id, scenario="external", status="RUNNING", plan_json="[]", cursor=0)
    db.add(sess)
    db.commit()
    task = Task(session_id=sess.id, description=payload.task)
    db.add(task)
    db.commit()
    audit.record(db, "AGENT_STARTED", agent_id=agent.id, agent_name=agent.name, session_id=sess.id,
                 reason="External agent session opened via API.")
    audit.record(db, "TASK_STARTED", agent_id=agent.id, agent_name=agent.name, session_id=sess.id, reason=payload.task)
    tp = resolve_task(payload.task, agent.name)
    hub.publish("simulation_started", {"session_id": sess.id, "agent_id": agent.id, "agent_name": agent.name,
                                       "scenario": "external", "scenario_name": "External agent", "task": payload.task,
                                       "planned_sequence": [], "expected_intervention": "Decided per action."})
    return {"session_id": sess.id, "task_id": task.id, "agent": agent.name, "resolved_task_type": tp.task_type,
            "task_confidence": tp.confidence, "allowed_actions": policy_engine.allowed_actions(agent.name)}


@router.post("/sessions/{session_id}/close")
def close_session(session_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    sess = db.get(Session_, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if sess.status != "RUNNING":
        raise HTTPException(status_code=409, detail=f"Session is already {sess.status}.")
    agent = db.get(Agent, sess.agent_id)
    simulator.finish_session(db, sess, agent)
    db.refresh(sess)
    return {"session_id": sess.id, "status": sess.status}


@router.get("/sessions/{session_id}/graph")
def session_graph(session_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    if db.get(Session_, session_id) is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return graph.session_graph(db, session_id)


# ------------------------------------------------------------------ actions
@router.get("/actions")
def get_actions(db: Session = Depends(get_db), session_id: Optional[str] = None,
                risk_level: Optional[str] = None, status: Optional[str] = None,
                limit: int = Query(100, ge=1, le=500)) -> List[Dict[str, Any]]:
    q = db.query(Action)
    if session_id:
        q = q.filter(Action.session_id == session_id)
    if risk_level:
        q = q.filter(Action.risk_level == risk_level.upper())
    if status:
        q = q.filter(Action.action_status == status.upper())
    return [action_to_dict(a) for a in q.order_by(Action.timestamp.desc()).limit(limit).all()]


@router.post("/actions/evaluate")
def evaluate_single_action(payload: EvaluateActionRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Push one action through the pipeline. History, task and trust come from the DB."""
    if payload.action_type not in CATALOG:
        raise HTTPException(status_code=400, detail=f"Unknown action_type '{payload.action_type}'.")
    sess = db.get(Session_, payload.session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if sess.status not in ("RUNNING",):
        raise HTTPException(status_code=409, detail=f"Session is {sess.status}; the agent cannot act.")
    agent = db.get(Agent, sess.agent_id)
    task = db.query(Task).filter(Task.session_id == sess.id).first()
    step = db.query(Action).filter(Action.session_id == sess.id).count()
    result = evaluate_action(db, agent=agent, sess=sess, task_id=task.id if task else "manual",
                             action_type=payload.action_type, step_index=step, dt=payload.dt,
                             failed=payload.failed, content=payload.content)
    db.refresh(sess)
    sess.cursor = max(sess.cursor or 0, step + 1)      # keep "prevented steps" honest for manually driven sessions
    db.commit()
    return result


@router.get("/catalog")
def get_catalog() -> Dict[str, Any]:
    return {"actions": [s.as_dict() for s in CATALOG.values()]}


# ---------------------------------------------------------------- incidents
@router.get("/incidents")
def get_incidents(db: Session = Depends(get_db), status: Optional[str] = None,
                  severity: Optional[str] = None) -> List[Dict[str, Any]]:
    q = db.query(Incident)
    if status:
        q = q.filter(Incident.status == status.upper())
    if severity:
        q = q.filter(Incident.severity == severity.upper())
    out = []
    for i in q.order_by(Incident.created_at.desc()).all():
        d = _incident_dict(i)
        ag = db.get(Agent, i.agent_id)
        d["agent_name"] = ag.name if ag else None
        out.append(d)
    return out


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found.")
    agent = db.get(Agent, inc.agent_id)
    actions = db.query(Action).filter(Action.session_id == inc.session_id).order_by(Action.step_index.asc()).all()
    ad = [action_to_dict(a) for a in actions]
    trigger = next((a for a in ad if a["id"] == inc.trigger_action_id), None)
    ivs = (db.query(Intervention).filter(Intervention.session_id == inc.session_id)
             .order_by(Intervention.created_at.asc()).all())
    audits = (db.query(AuditEvent).filter(AuditEvent.session_id == inc.session_id)
                .order_by(AuditEvent.timestamp.asc()).all())
    sess = db.get(Session_, inc.session_id)
    plan = json.loads(sess.plan_json or "[]") if sess else []
    return {
        **_incident_dict(inc), "agent_name": agent.name if agent else None, "actions": ad,
        "trigger_action": trigger, "risk_factors": trigger["risk_factors"] if trigger else {},
        "ai_explanation": explain_incident(ad),
        "prevented_steps": [p["action"] for p in plan[sess.cursor:]] if sess and sess.status != "COMPLETED" else [],
        "interventions": [{"id": v.id, "action_id": v.action_id, "decision": v.decision, "reason": v.reason,
                           "agent_state_after": v.agent_state_after, "created_at": v.created_at.isoformat()} for v in ivs],
        "recovery_events": recovery.recovery_events(db, inc.id),
        "timeline": [{"id": e.id, "timestamp": e.timestamp.isoformat(), "event_type": e.event_type,
                      "reason": e.reason, "risk_score": e.risk_score, "risk_level": e.risk_level,
                      "decision": e.decision, "action_type": e.action_type} for e in audits],
    }


@router.get("/incidents/{incident_id}/replay")
def incident_replay(incident_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found.")
    return graph.incident_replay(db, inc)


@router.post("/incidents/{incident_id}/recover")
def recover_incident(incident_id: str, payload: RecoverRequest = RecoverRequest(),
                     db: Session = Depends(get_db)) -> Dict[str, Any]:
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found.")
    if inc.status == "RESOLVED":
        raise HTTPException(status_code=409, detail=f"{inc.reference} has already been recovered and verified.")
    if inc.status == "RECOVERING":
        raise HTTPException(status_code=409, detail=f"{inc.reference} is already being recovered.")
    try:
        return recovery.run_recovery(db, inc, fault=payload.fault)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------- approvals
@router.get("/pending-approvals")
def pending_approvals(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    out = []
    for a in db.query(Approval).filter(Approval.status == "PENDING").order_by(Approval.created_at.desc()).all():
        d = approval_svc.to_dict(a)
        ag = db.get(Agent, a.agent_id)
        d["agent_name"] = ag.name if ag else None
        act = db.get(Action, a.action_id)
        d["action"] = action_to_dict(act) if act else None
        out.append(d)
    return out


@router.get("/approvals")
def all_approvals(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    return [approval_svc.to_dict(a) for a in db.query(Approval).order_by(Approval.created_at.desc()).all()]


def _guard(fn):
    try:
        return fn()
    except approval_svc.ApprovalError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)


@router.post("/approvals/{approval_id}/approve")
def approve(approval_id: str, request: Request, payload: ApprovalDecisionRequest = ApprovalDecisionRequest(),
            db: Session = Depends(get_db)) -> Dict[str, Any]:
    return _guard(lambda: approval_svc.decide(db, approval_id, True, _who(request, payload.decided_by), payload.note))


@router.post("/approvals/{approval_id}/reject")
def reject(approval_id: str, request: Request, payload: ApprovalDecisionRequest = ApprovalDecisionRequest(),
           db: Session = Depends(get_db)) -> Dict[str, Any]:
    return _guard(lambda: approval_svc.decide(db, approval_id, False, _who(request, payload.decided_by), payload.note))


@router.post("/approvals/{approval_id}/request-evidence")
def request_evidence(approval_id: str, request: Request, payload: ApprovalDecisionRequest = ApprovalDecisionRequest(),
                     db: Session = Depends(get_db)) -> Dict[str, Any]:
    return _guard(lambda: approval_svc.request_more_evidence(db, approval_id, _who(request, payload.decided_by)))


# -------------------------------------------------------------------- audit
@router.get("/audit")
def get_audit(db: Session = Depends(get_db), event_type: Optional[str] = None, risk_level: Optional[str] = None,
              session_id: Optional[str] = None, agent_name: Optional[str] = None, search: Optional[str] = None,
              limit: int = Query(200, ge=1, le=1000)) -> List[Dict[str, Any]]:
    q = db.query(AuditEvent)
    if event_type:
        q = q.filter(AuditEvent.event_type == event_type.upper())
    if risk_level:
        q = q.filter(AuditEvent.risk_level == risk_level.upper())
    if session_id:
        q = q.filter(AuditEvent.session_id == session_id)
    if agent_name:
        q = q.filter(AuditEvent.agent_name == agent_name)
    if search:
        q = q.filter(AuditEvent.reason.contains(search))
    return [{"id": e.id, "timestamp": e.timestamp.isoformat(), "event_type": e.event_type, "agent_id": e.agent_id,
             "agent_name": e.agent_name, "session_id": e.session_id, "incident_id": e.incident_id,
             "action_type": e.action_type, "risk_score": e.risk_score, "risk_level": e.risk_level,
             "decision": e.decision, "reason": e.reason}
            for e in q.order_by(AuditEvent.timestamp.desc()).limit(limit).all()]


@router.get("/audit/event-types")
def audit_event_types() -> List[str]:
    return audit.EVENT_TYPES


# ------------------------------------------------------- metrics / ml / policy
@router.get("/metrics")
def get_metrics(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return metrics.compute(db)


@router.get("/environment")
def get_environment(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return {"resources": sandbox.snapshot(db), "verification": sandbox.verify(db)}


@router.get("/ml/status")
def ml_status() -> Dict[str, Any]:
    return detector.status()


@router.get("/evaluation")
def evaluation() -> Dict[str, Any]:
    ev = detector.status().get("evaluation")
    if not ev:
        raise HTTPException(status_code=404, detail="No evaluation report. Run: python -m backend.ml.evaluate")
    return ev


@router.get("/architecture")
def get_architecture(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return architecture.describe(db)


@router.get("/policy")
def get_policy() -> Dict[str, Any]:
    return policy_engine.policy


@router.post("/policy/reload")
def reload_policy() -> Dict[str, Any]:
    try:
        p = policy_engine.reload()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Policy file is invalid: {exc}")
    return {"reloaded": True, "policy_version": p.get("policy_version"), "rules": len(p.get("rules", []))}


# --------------------------------------------------------------------- demo
@router.post("/demo/reset")
def demo_reset() -> Dict[str, Any]:
    try:
        return demo.reset()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/demo/start")
def demo_start() -> Dict[str, Any]:
    if demo.STATE["running"]:
        raise HTTPException(status_code=409, detail="A demo is already running.")
    if not demo._schedule_run():
        raise HTTPException(status_code=503, detail="The event loop is not available.")
    return {"started": True, "stages": demo.STAGES}


@router.get("/demo/status")
def demo_status() -> Dict[str, Any]:
    return {"running": demo.STATE["running"], "stage": demo.STATE["stage"],
            "session_ids": demo.STATE["session_ids"], "stages": demo.STAGES}
