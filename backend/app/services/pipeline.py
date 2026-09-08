"""The safety pipeline.

OBSERVE -> DETECT -> ASSESS -> EXPLAIN -> INTERVENE -> (RECOVER) -> AUDIT

`evaluate_action` is the single entry point used by the simulator, the tests
and the manual /api/actions/evaluate endpoint. Everything the dashboard shows
about an action is produced here.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.app.agent.catalog import get_spec, sequence_deviation
from backend.app.database.models import (
    Action, Agent, Approval, Incident, Intervention, RiskAssessment, Session_,
)
from backend.app.services import audit, sandbox
from backend.app.services.events import hub
from backend.app.services.explanation import explain_action
from backend.app.services.ml_detector import detector
from backend.app.services.policy_engine import policy_engine
from backend.app.services.risk_engine import assess
from backend.ml.features import ActionContext

# Decisions that stop the action from reaching the simulated environment.
_BLOCKING = {"BLOCK", "BLOCK_AND_STOP", "REQUIRE_APPROVAL"}

_STATUS_FOR_DECISION = {
    "ALLOW": "ALLOWED",
    "MONITOR": "MONITORED",
    "BLOCK": "BLOCKED",
    "BLOCK_AND_STOP": "BLOCKED",
    "REQUIRE_APPROVAL": "PENDING_APPROVAL",
}


def next_incident_reference(db: Session) -> str:
    return f"INC-{db.query(Incident).count() + 1:04d}"


def action_to_dict(a: Action) -> Dict[str, Any]:
    return {
        "id": a.id,
        "timestamp": a.timestamp.isoformat(),
        "session_id": a.session_id,
        "agent_id": a.agent_id,
        "task_id": a.task_id,
        "step_index": a.step_index,
        "action_type": a.action_type,
        "tool_name": a.tool_name,
        "resource": a.resource,
        "permission_level": a.permission_level,
        "task_relevance": round(a.task_relevance, 3),
        "action_status": a.action_status,
        "anomaly_score": a.anomaly_score,
        "risk_score": a.risk_score,
        "risk_level": a.risk_level,
        "policy_violation": a.policy_violation,
        "explanation": a.explanation,
        "risk_factors": json.loads(a.risk_factors_json or "{}"),
        "incident_id": a.incident_id,
    }


def evaluate_action(
    db: Session,
    *,
    agent: Agent,
    sess: Session_,
    task_id: str,
    action_type: str,
    step_index: int,
    prev_action: Optional[str],
    repeated_count: int = 0,
    seconds_since_prev: float = 3.0,
    task_relevance: Optional[float] = None,
    execute_if_allowed: bool = True,
) -> Dict[str, Any]:
    """Run one attempted agent action through the full safety pipeline."""
    spec = get_spec(action_type)
    relevance = spec.base_relevance if task_relevance is None else float(task_relevance)

    # ---- DETECT (ML) -----------------------------------------------------
    ctx = ActionContext(
        action_type=action_type,
        prev_action=prev_action,
        repeated_count=repeated_count,
        seconds_since_prev=seconds_since_prev,
        step_index=step_index,
        task_relevance=relevance,
    )
    ml = detector.score(ctx)
    anomaly = ml["anomaly_score"]

    # ---- POLICY ----------------------------------------------------------
    pol = policy_engine.evaluate(action_type, spec.resource, spec.permission_level, relevance)

    # ---- ASSESS RISK -----------------------------------------------------
    risk = assess(action_type, anomaly, spec.permission_level, relevance, pol)

    # ---- DECIDE ----------------------------------------------------------
    decision = policy_engine.decide(risk.risk_level, pol, destructive=spec.destructive)
    status = _STATUS_FOR_DECISION[decision]

    # ---- EXPLAIN ---------------------------------------------------------
    seq_dev = sequence_deviation(prev_action, action_type)
    explanation = explain_action(
        action_type, spec.resource, anomaly, risk.risk_score, risk.risk_level,
        decision, pol, risk.factors, prev_action, seq_dev)

    # ---- PERSIST ---------------------------------------------------------
    factors_payload = {
        "factors": risk.factors,
        "weighted_contributions": risk.contributions,
        "sequence_deviation": round(seq_dev, 3),
        "ml_source": ml["source"],
        "ml_raw_score": ml["raw_score"],
        "features": {k: round(float(v), 4) for k, v in ml["features"].items()},
        "policy_violations": pol.violations,
        "policy_details": pol.details,
    }
    action = Action(
        session_id=sess.id, agent_id=agent.id, task_id=task_id, step_index=step_index,
        action_type=action_type, tool_name=spec.tool_name, resource=spec.resource,
        permission_level=spec.permission_level, task_relevance=relevance,
        action_status=status, anomaly_score=anomaly, risk_score=risk.risk_score,
        risk_level=risk.risk_level, policy_violation=pol.primary_violation,
        explanation=explanation, risk_factors_json=json.dumps(factors_payload),
    )
    db.add(action)
    db.commit()

    db.add(RiskAssessment(action_id=action.id, anomaly_score=anomaly,
                          risk_score=risk.risk_score, risk_level=risk.risk_level,
                          factors_json=json.dumps(factors_payload)))
    db.commit()

    # ---- INTERVENE -------------------------------------------------------
    agent_state = agent.status
    approval: Optional[Approval] = None
    incident: Optional[Incident] = None
    executed = False
    effects: Dict[str, str] = {}

    if decision in ("ALLOW", "MONITOR"):
        if execute_if_allowed:
            effects = sandbox.apply_effect(db, action_type)
            executed = True
        if decision == "MONITOR" and agent.status == "RUNNING":
            agent_state = "SUSPICIOUS"
    elif decision == "REQUIRE_APPROVAL":
        approval = Approval(
            action_id=action.id, session_id=sess.id, agent_id=agent.id,
            action_type=action_type, risk_score=risk.risk_score,
            reason=explanation, status="PENDING")
        db.add(approval)
        sess.status = "AWAITING_APPROVAL"
        agent_state = "PAUSED"
        db.commit()
    elif decision == "BLOCK":
        agent_state = "SUSPICIOUS"
    elif decision == "BLOCK_AND_STOP":
        agent_state = "PAUSED"

    agent.status = agent_state
    db.commit()

    db.add(Intervention(action_id=action.id, session_id=sess.id, decision=decision,
                        reason=explanation, agent_state_after=agent_state))
    db.commit()

    # ---- AUDIT + BROADCAST ----------------------------------------------
    payload = action_to_dict(action)
    payload["decision"] = decision
    payload["executed"] = executed
    payload["simulated_effects"] = effects
    payload["agent_status"] = agent_state
    hub.publish("action", payload)

    audit.record(db, "ACTION_EXECUTED", agent_id=agent.id, agent_name=agent.name,
                 session_id=sess.id, action_type=action_type,
                 risk_score=risk.risk_score, risk_level=risk.risk_level,
                 decision=decision, reason=f"{action_type} -> {status}")

    if anomaly >= policy_engine.policy["thresholds"]["anomaly_alert"]:
        audit.record(db, "ANOMALY_DETECTED", agent_id=agent.id, agent_name=agent.name,
                     session_id=sess.id, action_type=action_type,
                     risk_score=risk.risk_score, risk_level=risk.risk_level,
                     reason=f"Behavioural anomaly score {anomaly:.2f} exceeds alert threshold "
                            f"{policy_engine.policy['thresholds']['anomaly_alert']}")

    for v in pol.violations:
        audit.record(db, "POLICY_VIOLATION", agent_id=agent.id, agent_name=agent.name,
                     session_id=sess.id, action_type=action_type,
                     risk_score=risk.risk_score, risk_level=risk.risk_level,
                     reason=pol.details.get(v, v))

    audit.record(db, "RISK_CALCULATED", agent_id=agent.id, agent_name=agent.name,
                 session_id=sess.id, action_type=action_type,
                 risk_score=risk.risk_score, risk_level=risk.risk_level,
                 reason="Risk factors: " + ", ".join(
                     f"{k}={v:.0f}" for k, v in risk.factors.items()))

    if decision in _BLOCKING and decision != "REQUIRE_APPROVAL":
        audit.record(db, "ACTION_BLOCKED", agent_id=agent.id, agent_name=agent.name,
                     session_id=sess.id, action_type=action_type,
                     risk_score=risk.risk_score, risk_level=risk.risk_level,
                     decision=decision, reason=explanation)

    # ---- INCIDENT --------------------------------------------------------
    if risk.risk_level in ("HIGH", "CRITICAL") and decision != "REQUIRE_APPROVAL":
        # One incident per session: an escalating attack chain is a single
        # campaign, not three unrelated events. An existing open incident is
        # escalated in place rather than duplicated.
        incident = (db.query(Incident)
                      .filter(Incident.session_id == sess.id,
                              Incident.status.in_(("OPEN", "RECOVERING")))
                      .order_by(Incident.created_at.asc()).first())
        is_new = incident is None
        if is_new:
            incident = Incident(
                reference=next_incident_reference(db), session_id=sess.id, agent_id=agent.id,
                severity=risk.risk_level, risk_score=risk.risk_score,
                title=f"{action_type} attempt on {spec.resource}",
                reason=explanation, trigger_action_id=action.id, status="OPEN")
            db.add(incident)
        elif risk.risk_score >= incident.risk_score:
            # The chain got worse (or equally bad but later, which means the
            # agent escalated) -- the incident now describes its worst point.
            incident.severity = risk.risk_level
            incident.risk_score = risk.risk_score
            incident.title = f"{action_type} attempt on {spec.resource}"
            incident.reason = explanation
            incident.trigger_action_id = action.id
        db.commit()
        action.incident_id = incident.id
        db.commit()

        audit.record(
            db, "INCIDENT_CREATED" if is_new else "RISK_CALCULATED",
            agent_id=agent.id, agent_name=agent.name, session_id=sess.id,
            incident_id=incident.id, action_type=action_type,
            risk_score=risk.risk_score, risk_level=risk.risk_level,
            reason=(f"{incident.reference}: {incident.title}" if is_new else
                    f"{incident.reference} escalated by {action_type} "
                    f"(risk {risk.risk_score:.0f})"))
        hub.publish("incident", {"id": incident.id, "reference": incident.reference,
                                 "severity": incident.severity, "status": incident.status,
                                 "title": incident.title, "risk_score": incident.risk_score,
                                 "session_id": sess.id, "escalated": not is_new})

    # ---- halt conditions --------------------------------------------------
    # Either one irreversible CRITICAL attempt, or a pattern of blocked
    # attempts that shows the agent is not recovering on its own.
    pause_reason: Optional[str] = None
    if decision == "BLOCK_AND_STOP":
        pause_reason = ("Agent paused after attempting a CRITICAL, irreversible operation "
                        "that policy explicitly denies.")
    elif decision == "BLOCK":
        blocked_count = (db.query(Action)
                           .filter(Action.session_id == sess.id,
                                   Action.action_status == "BLOCKED").count())
        limit = policy_engine.policy.get("max_blocked_actions_per_session", 3)
        if blocked_count >= limit:
            pause_reason = (f"Agent paused after {blocked_count} blocked attempts in one "
                            f"session (limit {limit}). Repeated denial is treated as evidence "
                            f"the agent is not self-correcting.")

    if pause_reason:
        sess.status = "PAUSED"
        agent.status = "PAUSED"
        db.commit()
        audit.record(db, "AGENT_PAUSED", agent_id=agent.id, agent_name=agent.name,
                     session_id=sess.id, action_type=action_type,
                     risk_score=risk.risk_score, risk_level=risk.risk_level,
                     reason=pause_reason)
        hub.publish("agent_status", {"agent_id": agent.id, "status": "PAUSED",
                                     "session_id": sess.id})

    if decision == "REQUIRE_APPROVAL" and approval is not None:
        audit.record(db, "APPROVAL_REQUESTED", agent_id=agent.id, agent_name=agent.name,
                     session_id=sess.id, action_type=action_type,
                     risk_score=risk.risk_score, risk_level=risk.risk_level,
                     decision=decision,
                     reason=f"Human approval required for {action_type}.")
        hub.publish("approval_requested", {
            "id": approval.id, "action_id": action.id, "session_id": sess.id,
            "agent_id": agent.id, "agent_name": agent.name, "action_type": action_type,
            "risk_score": risk.risk_score, "reason": explanation})

    return {
        "action": payload,
        "decision": decision,
        "incident_id": incident.id if incident else None,
        "approval_id": approval.id if approval else None,
        "executed": executed,
    }
