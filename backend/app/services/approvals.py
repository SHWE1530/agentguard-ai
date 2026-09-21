"""Human-in-the-loop decisions: APPROVE, REJECT or REQUEST MORE EVIDENCE."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.app.database.models import Action, Agent, Approval, Session_, utcnow
from backend.app.services import audit, evidence, sandbox
from backend.app.services.events import hub


class ApprovalError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def to_dict(a: Approval) -> Dict[str, Any]:
    return {
        "id": a.id, "action_id": a.action_id, "session_id": a.session_id, "agent_id": a.agent_id,
        "action_type": a.action_type, "risk_score": a.risk_score, "reason": a.reason, "status": a.status,
        "evidence": json.loads(a.evidence_json or "{}"), "impact": json.loads(a.impact_json or "{}"),
        "alternative": json.loads(a.alternative_json) if a.alternative_json else None,
        "evidence_rounds": a.evidence_rounds, "decision_note": a.decision_note, "decided_by": a.decided_by,
        "created_at": a.created_at.isoformat(), "decided_at": a.decided_at.isoformat() if a.decided_at else None,
    }


def _get(db: Session, approval_id: str) -> Approval:
    ap = db.get(Approval, approval_id)
    if ap is None:
        raise ApprovalError(404, f"Approval '{approval_id}' not found.")
    return ap


def request_more_evidence(db: Session, approval_id: str, requested_by: str) -> Dict[str, Any]:
    ap = _get(db, approval_id)
    if ap.status != "PENDING":
        raise ApprovalError(409, f"This request was already {ap.status.lower()}; evidence can only be requested while pending.")
    if ap.evidence_rounds >= 3:
        raise ApprovalError(409, "Evidence has already been requested three times; please decide.")
    evidence.gather(db, ap)
    agent = db.get(Agent, ap.agent_id)
    audit.record(db, "EVIDENCE_REQUESTED", agent_id=ap.agent_id, agent_name=agent.name if agent else None,
                 session_id=ap.session_id, action_type=ap.action_type, risk_score=ap.risk_score,
                 decision="MORE_EVIDENCE",
                 reason=f"{requested_by} requested more evidence (round {ap.evidence_rounds}) for {ap.action_type}.")
    hub.publish("approval_updated", {"id": ap.id, "evidence_rounds": ap.evidence_rounds})
    return to_dict(ap)


def decide(db: Session, approval_id: str, approve: bool, decided_by: str, note: Optional[str] = None,
           schedule: bool = True) -> Dict[str, Any]:
    ap = _get(db, approval_id)
    if ap.status != "PENDING":
        raise ApprovalError(409, f"This request was already {ap.status.lower()} by {ap.decided_by or 'an operator'}.")

    ap.status = "APPROVED" if approve else "REJECTED"
    ap.decided_by, ap.decided_at, ap.decision_note = decided_by, utcnow(), note
    action = db.get(Action, ap.action_id)
    agent = db.get(Agent, ap.agent_id)
    sess = db.get(Session_, ap.session_id)
    effects: Dict[str, str] = {}
    tail = f": {note}" if note else "."

    if approve:
        action.action_status = "APPROVED"
        action.execution_result = "SUCCESS"
        action.explanation += f" Operator '{decided_by}' approved execution{tail}"
        effects = sandbox.apply_effect(db, ap.action_type)
    else:
        action.action_status = "REJECTED"
        action.explanation += f" Operator '{decided_by}' rejected execution{tail}"
    db.commit()

    audit.record(db, "HUMAN_APPROVAL" if approve else "HUMAN_REJECTION", agent_id=ap.agent_id,
                 agent_name=agent.name if agent else None, session_id=ap.session_id, action_type=ap.action_type,
                 risk_score=ap.risk_score, decision=ap.status,
                 reason=f"{decided_by} {ap.status.lower()} {ap.action_type}." + (f" Note: {note}" if note else "")
                        + (f" Reviewed {ap.evidence_rounds} extra evidence round(s)." if ap.evidence_rounds else ""))

    if sess is not None:
        sess.status = "RUNNING"
    if agent is not None:
        agent.status = "RUNNING"
    db.commit()
    hub.publish("approval_decided", {"id": ap.id, "status": ap.status, "action_type": ap.action_type,
                                     "decided_by": ap.decided_by, "session_id": ap.session_id,
                                     "simulated_effects": effects})

    if schedule:
        from backend.app.services import simulator
        if not simulator._schedule(f"resume-{ap.session_id}", simulator.resume_after_decision(ap.session_id)):
            # No event loop (synchronous callers): finish inline
            from backend.app.agent import scenarios as scen
            from backend.app.database.models import Task
            task = db.query(Task).filter(Task.session_id == ap.session_id).one()
            while True:
                _, stop = simulator.advance(db, sess, agent, task)
                if stop:
                    break
            db.refresh(sess)
            if sess.status != "AWAITING_APPROVAL":
                simulator.finish_session(db, sess, agent)
                simulator.auto_recover(db, sess, scen.SCENARIOS.get(sess.scenario))
    return {**to_dict(ap), "simulated_effects": effects}
