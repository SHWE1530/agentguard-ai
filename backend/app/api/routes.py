from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.agent.catalog import CATALOG
from backend.app.agent.scenarios import list_scenarios
from backend.app.database.db import get_db
from backend.app.database.models import (
    Action, Agent, Approval, AuditEvent, Incident, Intervention, Session_, Task,
)
from backend.app.schemas.api import (
    ApprovalDecisionRequest, EvaluateActionRequest, StartAgentRequest, StartSimulationRequest,
)
from backend.app.services import audit, metrics, recovery, sandbox, simulator
from backend.app.services.events import hub
from backend.app.services.explanation import explain_incident
from backend.app.services.ml_detector import detector
from backend.app.services.pipeline import action_to_dict, evaluate_action
from backend.app.services.policy_engine import policy_engine

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ health
@router.get("/health")
def health(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return {
        "status": "ok",
        "time": datetime.utcnow().isoformat(),
        "model_loaded": detector.ready,
        "policy_version": policy_engine.policy.get("policy_version"),
        "websocket_clients": hub.client_count,
        "actions_recorded": db.query(Action).count(),
    }


# ------------------------------------------------------------------ agents
@router.get("/agents")
def get_agents(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    out = []
    for a in db.query(Agent).all():
        latest = (db.query(Session_).filter(Session_.agent_id == a.id)
                    .order_by(Session_.started_at.desc()).first())
        current_action = None
        task = None
        if latest:
            task_row = db.query(Task).filter(Task.session_id == latest.id).first()
            task = task_row.description if task_row else None
            last = (db.query(Action).filter(Action.session_id == latest.id)
                      .order_by(Action.timestamp.desc()).first())
            current_action = action_to_dict(last) if last else None
        out.append({
            "id": a.id, "name": a.name, "purpose": a.purpose, "status": a.status,
            "created_at": a.created_at.isoformat(),
            "current_session": latest.id if latest else None,
            "current_scenario": latest.scenario if latest else None,
            "session_status": latest.status if latest else None,
            "current_task": task,
            "current_action": current_action,
            "allowed_actions": [k for k, v in CATALOG.items() if v.allowed],
            "restricted_actions": [k for k, v in CATALOG.items() if not v.allowed],
        })
    return out


@router.post("/agents/start")
def start_agent(payload: StartAgentRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return simulator.start_simulation(db, payload.scenario)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ------------------------------------------------------------- simulations
@router.get("/scenarios")
def get_scenarios() -> List[dict]:
    return list_scenarios()


@router.post("/simulations/start")
def start_simulation(payload: StartSimulationRequest,
                     db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return simulator.start_simulation(db, payload.scenario)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/simulations/{session_id}")
def get_simulation(session_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    sess = db.get(Session_, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    agent = db.get(Agent, sess.agent_id)
    task = db.query(Task).filter(Task.session_id == sess.id).first()
    actions = (db.query(Action).filter(Action.session_id == sess.id)
                 .order_by(Action.step_index.asc()).all())
    incidents = db.query(Incident).filter(Incident.session_id == sess.id).all()
    approvals = db.query(Approval).filter(Approval.session_id == sess.id).all()
    return {
        "id": sess.id,
        "scenario": sess.scenario,
        "status": sess.status,
        "started_at": sess.started_at.isoformat(),
        "ended_at": sess.ended_at.isoformat() if sess.ended_at else None,
        "agent": {"id": agent.id, "name": agent.name, "status": agent.status} if agent else None,
        "task": task.description if task else None,
        "live": simulator.is_running(sess.id),
        "actions": [action_to_dict(a) for a in actions],
        "incidents": [_incident_dict(i) for i in incidents],
        "approvals": [_approval_dict(a) for a in approvals],
    }


@router.get("/sessions")
def get_sessions(db: Session = Depends(get_db), limit: int = Query(50, ge=1, le=200)):
    rows = db.query(Session_).order_by(Session_.started_at.desc()).limit(limit).all()
    return [{
        "id": s.id, "scenario": s.scenario, "status": s.status,
        "started_at": s.started_at.isoformat(),
        "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        "action_count": db.query(Action).filter(Action.session_id == s.id).count(),
    } for s in rows]


# ------------------------------------------------------------------ actions
@router.get("/actions")
def get_actions(db: Session = Depends(get_db),
                session_id: Optional[str] = None,
                risk_level: Optional[str] = None,
                status: Optional[str] = None,
                limit: int = Query(100, ge=1, le=500)) -> List[Dict[str, Any]]:
    q = db.query(Action)
    if session_id:
        q = q.filter(Action.session_id == session_id)
    if risk_level:
        q = q.filter(Action.risk_level == risk_level.upper())
    if status:
        q = q.filter(Action.action_status == status.upper())
    rows = q.order_by(Action.timestamp.desc()).limit(limit).all()
    return [action_to_dict(a) for a in rows]


@router.post("/actions/evaluate")
def evaluate_single_action(payload: EvaluateActionRequest,
                           db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Push one action through the safety pipeline without running a scenario."""
    if payload.action_type not in CATALOG:
        raise HTTPException(status_code=400,
                            detail=f"Unknown action_type '{payload.action_type}'.")
    sess = db.get(Session_, payload.session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    agent = db.get(Agent, sess.agent_id)
    task = db.query(Task).filter(Task.session_id == sess.id).first()
    step = db.query(Action).filter(Action.session_id == sess.id).count()
    return evaluate_action(
        db, agent=agent, sess=sess, task_id=task.id if task else "manual",
        action_type=payload.action_type, step_index=step,
        prev_action=payload.prev_action, task_relevance=payload.task_relevance)


@router.get("/catalog")
def get_catalog() -> Dict[str, Any]:
    return {"actions": [s.as_dict() for s in CATALOG.values()]}


# ---------------------------------------------------------------- incidents
def _incident_dict(i: Incident) -> Dict[str, Any]:
    return {
        "id": i.id, "reference": i.reference, "session_id": i.session_id,
        "agent_id": i.agent_id, "severity": i.severity, "title": i.title,
        "reason": i.reason, "risk_score": i.risk_score, "status": i.status,
        "trigger_action_id": i.trigger_action_id,
        "created_at": i.created_at.isoformat(),
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
    }


def _approval_dict(a: Approval) -> Dict[str, Any]:
    return {
        "id": a.id, "action_id": a.action_id, "session_id": a.session_id,
        "agent_id": a.agent_id, "action_type": a.action_type,
        "risk_score": a.risk_score, "reason": a.reason, "status": a.status,
        "decided_by": a.decided_by, "created_at": a.created_at.isoformat(),
        "decided_at": a.decided_at.isoformat() if a.decided_at else None,
    }


@router.get("/incidents")
def get_incidents(db: Session = Depends(get_db),
                  status: Optional[str] = None,
                  severity: Optional[str] = None) -> List[Dict[str, Any]]:
    q = db.query(Incident)
    if status:
        q = q.filter(Incident.status == status.upper())
    if severity:
        q = q.filter(Incident.severity == severity.upper())
    rows = q.order_by(Incident.created_at.desc()).all()
    out = []
    for i in rows:
        d = _incident_dict(i)
        agent = db.get(Agent, i.agent_id)
        d["agent_name"] = agent.name if agent else None
        out.append(d)
    return out


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found.")
    agent = db.get(Agent, inc.agent_id)
    actions = (db.query(Action).filter(Action.session_id == inc.session_id)
                 .order_by(Action.step_index.asc()).all())
    action_dicts = [action_to_dict(a) for a in actions]
    trigger = next((a for a in action_dicts if a["id"] == inc.trigger_action_id), None)
    interventions = (db.query(Intervention)
                       .filter(Intervention.session_id == inc.session_id)
                       .order_by(Intervention.created_at.asc()).all())
    audits = (db.query(AuditEvent)
                .filter(AuditEvent.session_id == inc.session_id)
                .order_by(AuditEvent.timestamp.asc()).all())
    return {
        **_incident_dict(inc),
        "agent_name": agent.name if agent else None,
        "actions": action_dicts,
        "trigger_action": trigger,
        "risk_factors": trigger["risk_factors"] if trigger else {},
        "ai_explanation": explain_incident(action_dicts),
        "interventions": [{
            "id": v.id, "action_id": v.action_id, "decision": v.decision,
            "reason": v.reason, "agent_state_after": v.agent_state_after,
            "created_at": v.created_at.isoformat()} for v in interventions],
        "recovery_events": recovery.recovery_events(db, inc.id),
        "timeline": [{
            "id": e.id, "timestamp": e.timestamp.isoformat(), "event_type": e.event_type,
            "reason": e.reason, "risk_score": e.risk_score, "risk_level": e.risk_level,
            "decision": e.decision, "action_type": e.action_type} for e in audits],
    }


@router.post("/incidents/{incident_id}/recover")
def recover_incident(incident_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found.")
    if inc.status in ("RECOVERED", "RESOLVED"):
        raise HTTPException(status_code=409,
                            detail=f"{inc.reference} has already been recovered.")
    return recovery.run_recovery(db, inc)


# ---------------------------------------------------------------- approvals
@router.get("/pending-approvals")
def pending_approvals(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    rows = (db.query(Approval).filter(Approval.status == "PENDING")
              .order_by(Approval.created_at.desc()).all())
    out = []
    for a in rows:
        d = _approval_dict(a)
        agent = db.get(Agent, a.agent_id)
        d["agent_name"] = agent.name if agent else None
        action = db.get(Action, a.action_id)
        d["action"] = action_to_dict(action) if action else None
        out.append(d)
    return out


@router.get("/approvals")
def all_approvals(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    rows = db.query(Approval).order_by(Approval.created_at.desc()).all()
    return [_approval_dict(a) for a in rows]


def _decide(db: Session, approval_id: str, approve: bool,
            payload: ApprovalDecisionRequest) -> Dict[str, Any]:
    ap = db.get(Approval, approval_id)
    if ap is None:
        raise HTTPException(status_code=404, detail=f"Approval '{approval_id}' not found.")
    if ap.status != "PENDING":
        raise HTTPException(
            status_code=409,
            detail=f"This request was already {ap.status.lower()} by "
                   f"{ap.decided_by or 'an operator'}.")

    from backend.app.database.models import utcnow

    ap.status = "APPROVED" if approve else "REJECTED"
    ap.decided_by = payload.decided_by
    ap.decided_at = utcnow()

    action = db.get(Action, ap.action_id)
    agent = db.get(Agent, ap.agent_id)
    sess = db.get(Session_, ap.session_id)
    effects: Dict[str, str] = {}

    if approve:
        action.action_status = "APPROVED"
        action.explanation += (
            f" Human operator '{payload.decided_by}' approved execution"
            + (f": {payload.note}" if payload.note else "."))
        effects = sandbox.apply_effect(db, ap.action_type)
    else:
        action.action_status = "REJECTED"
        action.explanation += (
            f" Human operator '{payload.decided_by}' rejected execution"
            + (f": {payload.note}" if payload.note else "."))
    db.commit()

    audit.record(db, "HUMAN_APPROVAL" if approve else "HUMAN_REJECTION",
                 agent_id=ap.agent_id, agent_name=agent.name if agent else None,
                 session_id=ap.session_id, action_type=ap.action_type,
                 risk_score=ap.risk_score, decision=ap.status,
                 reason=f"{payload.decided_by} {ap.status.lower()} {ap.action_type}."
                        + (f" Note: {payload.note}" if payload.note else ""))

    if sess is not None:
        sess.status = "RUNNING"
        db.commit()
    if agent is not None:
        agent.status = "RUNNING"
        db.commit()

    hub.publish("approval_decided", {
        "id": ap.id, "status": ap.status, "action_type": ap.action_type,
        "decided_by": ap.decided_by, "session_id": ap.session_id,
        "simulated_effects": effects})

    scheduled = simulator._schedule(
        f"resume-{ap.session_id}", simulator.resume_after_approval(ap.session_id))
    if not scheduled and sess is not None:
        # No event loop (e.g. the synchronous test client) -- close inline.
        sess.status = "COMPLETED"
        if agent is not None:
            agent.status = "IDLE"
        db.commit()

    return {**_approval_dict(ap), "simulated_effects": effects}


@router.post("/approvals/{approval_id}/approve")
def approve(approval_id: str, payload: ApprovalDecisionRequest = ApprovalDecisionRequest(),
            db: Session = Depends(get_db)) -> Dict[str, Any]:
    return _decide(db, approval_id, True, payload)


@router.post("/approvals/{approval_id}/reject")
def reject(approval_id: str, payload: ApprovalDecisionRequest = ApprovalDecisionRequest(),
           db: Session = Depends(get_db)) -> Dict[str, Any]:
    return _decide(db, approval_id, False, payload)


# -------------------------------------------------------------------- audit
@router.get("/audit")
def get_audit(db: Session = Depends(get_db),
              event_type: Optional[str] = None,
              risk_level: Optional[str] = None,
              session_id: Optional[str] = None,
              agent_name: Optional[str] = None,
              search: Optional[str] = None,
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
    rows = q.order_by(AuditEvent.timestamp.desc()).limit(limit).all()
    return [{
        "id": e.id, "timestamp": e.timestamp.isoformat(), "event_type": e.event_type,
        "agent_id": e.agent_id, "agent_name": e.agent_name, "session_id": e.session_id,
        "incident_id": e.incident_id, "action_type": e.action_type,
        "risk_score": e.risk_score, "risk_level": e.risk_level,
        "decision": e.decision, "reason": e.reason} for e in rows]


@router.get("/audit/event-types")
def audit_event_types() -> List[str]:
    return audit.EVENT_TYPES


# ------------------------------------------------------------------ metrics
@router.get("/metrics")
def get_metrics(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return metrics.compute(db)


@router.get("/environment")
def get_environment(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return {"resources": sandbox.snapshot(db), "verification": sandbox.verify(db)}


# ----------------------------------------------------------------------- ml
@router.get("/ml/status")
def ml_status() -> Dict[str, Any]:
    return detector.status()


@router.get("/policy")
def get_policy() -> Dict[str, Any]:
    return policy_engine.policy
