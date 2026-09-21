"""The live safety pipeline.

OBSERVE -> DETECT -> ASSESS -> EXPLAIN -> INTERVENE -> (RECOVER) -> AUDIT

`evaluate_action` is the single entry point used by the simulator, the tests
and the manual /api/actions/evaluate endpoint. It rebuilds the session context
FROM THE DATABASE for every action (history, fingerprint, trust, environment):
callers cannot supply their own context, so an agent cannot talk its way to a
lower score by misreporting its previous action or its task relevance.

The analysis itself is the pure analyzer in analysis.py -- the same code the
offline evaluation measures.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.agent.catalog import get_spec, permission_value
from backend.app.database.models import (
    Action, Agent, Approval, Incident, Intervention, RiskAssessment, Session_, Task,
)
from backend.app.services import audit, baseline, evidence, sandbox, trust as trust_svc
from backend.app.services.analysis import Analysis, SessionContext, analyze
from backend.app.services.events import hub
from backend.app.services.intent import resolve_task
from backend.app.services.policy_engine import policy_engine
from backend.app.services.steps import StepRec

_STATUS_FOR_DECISION = {
    "ALLOW": "ALLOWED", "MONITOR": "MONITORED", "BLOCK": "BLOCKED", "TERMINATE": "BLOCKED",
    "REQUIRE_APPROVAL": "PENDING_APPROVAL",
}


def next_incident_reference(db: Session) -> str:
    return f"INC-{db.query(Incident).count() + 1:04d}"


def action_to_dict(a: Action) -> Dict[str, Any]:
    return {
        "id": a.id, "timestamp": a.timestamp.isoformat(), "session_id": a.session_id,
        "agent_id": a.agent_id, "task_id": a.task_id, "step_index": a.step_index,
        "action_type": a.action_type, "tool_name": a.tool_name, "resource": a.resource,
        "permission_level": a.permission_level, "task_relevance": round(a.task_relevance, 3),
        "action_status": a.action_status, "decision": a.decision,
        "execution_result": a.execution_result, "interval_s": a.interval_s,
        "anomaly_score": a.anomaly_score, "risk_score": a.risk_score, "risk_level": a.risk_level,
        "policy_violation": a.policy_violation, "explanation": a.explanation,
        "risk_factors": json.loads(a.risk_factors_json or "{}"), "incident_id": a.incident_id,
    }


def build_context(db: Session, agent: Agent, sess: Session_, task_text: str) -> SessionContext:
    """Everything the analyzer needs, read from the database -- never from the caller."""
    fp = baseline.active_fingerprint(db, agent)
    task = resolve_task(task_text, agent.name)
    prior: List[Action] = (db.query(Action).filter(Action.session_id == sess.id)
                             .order_by(Action.step_index.asc(), Action.timestamp.asc()).all())
    hist: List[StepRec] = []
    for a in prior:
        spec = get_spec(a.action_type)
        hist.append(StepRec(a.action_type, a.interval_s, permission_value(spec.permission_level),
                            spec.resource_sensitivity, spec.resource, spec.tool_name, a.task_relevance,
                            a.execution_result == "FAILED", a.decision in ("BLOCK", "TERMINATE")))
    t = trust_svc.compute(db, agent.id)
    return SessionContext(agent=agent.name, task=task, fp=fp, history=hist, env=sandbox.snapshot(db),
                          trust=t["score"], tainted=bool(sess.tainted),
                          taint_evidence=json.loads(sess.taint_json) if sess.taint_json else None,
                          blocked_in_session=sum(1 for s in hist if s.blocked))


def evaluate_action(db: Session, *, agent: Agent, sess: Session_, task_id: str, action_type: str,
                    step_index: int, dt: float = 3.0, failed: bool = False, content: Optional[str] = None,
                    bypass_guard: bool = False) -> Dict[str, Any]:
    """Run one attempted agent action through the full safety pipeline.

    `bypass_guard` exists ONLY for the recovery drill: it simulates damage that
    slipped past the safety layer (e.g. during a monitoring outage) so recovery
    can be exercised. The decision is still computed and recorded (late
    detection) but not enforced.
    """
    t_ctx = time.perf_counter()
    task_row = db.get(Task, task_id) or db.query(Task).filter(Task.session_id == sess.id).first()
    task_text = task_row.description if task_row else "Perform routine maintenance."
    ctx = build_context(db, agent, sess, task_text)
    ctx_ms = (time.perf_counter() - t_ctx) * 1000

    a: Analysis = analyze(ctx, action_type, dt=dt, failed=failed, content=content)
    spec = a.spec
    decision = a.decision
    a.latency_ms["context"] = ctx_ms
    a.latency_ms["decision_total"] = ctx_ms + a.latency_ms["total"]

    status = _STATUS_FOR_DECISION[decision]
    if bypass_guard and decision in ("BLOCK", "TERMINATE", "REQUIRE_APPROVAL"):
        status = "BYPASSED"

    payload_json = a.payload()
    action = Action(
        session_id=sess.id, agent_id=agent.id, task_id=task_id, step_index=step_index,
        action_type=action_type, tool_name=spec.tool_name, resource=spec.resource,
        permission_level=spec.permission_level, task_relevance=a.alignment, action_status=status,
        decision=decision, interval_s=dt, execution_result="NOT_EXECUTED",
        anomaly_score=a.anomaly, risk_score=a.risk.risk_score, risk_level=a.risk.risk_level,
        policy_violation=a.policy.primary_violation, explanation=a.explanation,
        risk_factors_json=json.dumps(payload_json))
    db.add(action)
    db.commit()
    db.add(RiskAssessment(action_id=action.id, anomaly_score=a.anomaly, risk_score=a.risk.risk_score,
                          risk_level=a.risk.risk_level, factors_json=json.dumps(payload_json)))
    db.commit()

    # ---- taint -----------------------------------------------------------
    if a.injection and a.injection["tainted"] and not sess.tainted:
        sess.tainted = True
        sess.taint_json = json.dumps(a.injection)
        db.commit()
        audit.record(db, "INJECTION_INDICATOR_DETECTED", agent_id=agent.id, agent_name=agent.name,
                     session_id=sess.id, action_type=action_type, risk_score=a.risk.risk_score,
                     risk_level=a.risk.risk_level,
                     reason=("Untrusted content contained injection indicators: "
                             + ", ".join(i["label"] for i in a.injection["indicators"])
                             + f" (score {a.injection['score']}). Session marked TAINTED."))
        hub.publish("taint", {"session_id": sess.id, "injection": a.injection})

    # ---- intervene -------------------------------------------------------
    agent_state = agent.status
    approval: Optional[Approval] = None
    executed = False
    effects: Dict[str, str] = {}

    proceeds = decision in ("ALLOW", "MONITOR") or bypass_guard
    if proceeds:
        if failed:
            action.execution_result = "FAILED"
        else:
            effects = sandbox.apply_effect(db, action_type)
            executed = True
            action.execution_result = "SUCCESS"
        db.commit()

    if decision == "MONITOR" and agent.status == "RUNNING":
        agent_state = "SUSPICIOUS"
    elif decision == "REQUIRE_APPROVAL" and not bypass_guard:
        approval = Approval(
            action_id=action.id, session_id=sess.id, agent_id=agent.id, action_type=action_type,
            risk_score=a.risk.risk_score, reason=a.explanation, status="PENDING",
            evidence_json=json.dumps(evidence.initial(a)),
            impact_json=json.dumps(a.counterfactual),
            alternative_json=json.dumps(a.alternative) if a.alternative else None)
        db.add(approval)
        sess.status = "AWAITING_APPROVAL"
        agent_state = "PAUSED"
        db.commit()
    elif decision == "BLOCK":
        agent_state = "SUSPICIOUS"
    elif decision == "TERMINATE":
        agent_state = "PAUSED"
        sess.status = "PAUSED"
        db.commit()

    agent.status = agent_state
    db.commit()
    db.add(Intervention(action_id=action.id, session_id=sess.id, decision=decision, reason=a.explanation,
                        agent_state_after=agent_state))
    db.commit()

    # ---- audit + broadcast ----------------------------------------------
    def rec(ev: str, reason: str, **kw: Any) -> None:
        audit.record(db, ev, agent_id=agent.id, agent_name=agent.name, session_id=sess.id,
                     action_type=action_type, risk_score=a.risk.risk_score, risk_level=a.risk.risk_level,
                     reason=reason, **kw)

    rec("ACTION_EXECUTED", f"{action_type} -> {status}" + (f" (execution {action.execution_result})" if proceeds else ""),
        decision=decision)
    if a.anomaly >= policy_engine.policy["thresholds"]["anomaly_alert"]:
        rec("ANOMALY_DETECTED", f"Behavioural anomaly score {a.anomaly:.2f} exceeds the alert threshold "
                                f"{policy_engine.policy['thresholds']['anomaly_alert']}")
    for v in a.policy.violations:
        rec("POLICY_VIOLATION", a.policy.details.get(v, v))
    for p in a.seq.patterns:
        rec("SEQUENCE_PATTERN_DETECTED", f"{p['name']}: stage {p['progress']}/{p['total']} "
            f"({' -> '.join(p['path'])}){' - COMPLETED' if p['completed'] else ''}")
    if a.seq.escalation.get("detected"):
        rec("PRIVILEGE_ESCALATION_DETECTED", a.seq.escalation["description"])
    first_drift = a.drift_alert and not db.query(Incident).filter(
        Incident.session_id == sess.id, Incident.kind == "DRIFT").count() and not any(
        json.loads(x.risk_factors_json).get("drift_alert") for x in
        db.query(Action).filter(Action.session_id == sess.id, Action.id != action.id).all())
    if first_drift:
        rec("DRIFT_DETECTED", f"Behavioural drift {a.drift['score'] * 100:.0f}% exceeds the threshold "
                              f"{a.drift_threshold * 100:.0f}% for {agent.name}.")
    rec("RISK_CALCULATED", "Risk factors: " + ", ".join(f"{k}={v:.0f}" for k, v in a.risk.factors.items()))
    if decision in ("BLOCK", "TERMINATE"):
        rec("ACTION_BLOCKED", a.explanation, decision=decision)

    # ---- incident ----------------------------------------------------------
    incident: Optional[Incident] = None
    is_new = False
    severe = a.risk.risk_level in ("HIGH", "CRITICAL") and decision != "REQUIRE_APPROVAL"
    # A drift INCIDENT needs corroboration: drift alone (e.g. a legitimate emergency burst) only
    # raises MONITOR. Drift plus no productive step, or plus intent erosion, is worth a human's time.
    corroborated = a.drift_alert and (a.seq.loop.get("observe_streak", 0) >= 5
                                      or a.features.get("window_misalignment", 0.0) >= 0.3)
    drift_incident = first_drift and corroborated
    if severe or drift_incident:
        incident = (db.query(Incident).filter(Incident.session_id == sess.id,
                                              Incident.status.in_(("OPEN", "RECOVERING")))
                      .order_by(Incident.created_at.asc()).first())
        is_new = incident is None
        sev = a.risk.risk_level if severe else "MEDIUM"
        title = (f"{action_type} attempt on {spec.resource}" if severe
                 else f"Behavioural drift ({a.drift['score'] * 100:.0f}%) for {agent.name}")
        if is_new:
            incident = Incident(reference=next_incident_reference(db), session_id=sess.id, agent_id=agent.id,
                                severity=sev, risk_score=a.risk.risk_score, title=title, reason=a.explanation,
                                trigger_action_id=action.id, status="OPEN",
                                kind="MISBEHAVIOR" if severe else "DRIFT")
            db.add(incident)
        elif severe and a.risk.risk_score >= incident.risk_score:
            incident.severity, incident.risk_score, incident.title = sev, a.risk.risk_score, title
            incident.reason, incident.trigger_action_id, incident.kind = a.explanation, action.id, "MISBEHAVIOR"
        db.commit()
        action.incident_id = incident.id
        db.commit()
        rec("INCIDENT_CREATED" if is_new else "RISK_CALCULATED",
            f"{incident.reference}: {incident.title}" if is_new else
            f"{incident.reference} escalated by {action_type} (risk {a.risk.risk_score:.0f})",
            incident_id=incident.id)
        hub.publish("incident", {"id": incident.id, "reference": incident.reference, "severity": incident.severity,
                                 "status": incident.status, "title": incident.title,
                                 "risk_score": incident.risk_score, "session_id": sess.id,
                                 "kind": incident.kind, "escalated": not is_new})
        if is_new:
            trust_svc.snapshot(db, agent.id, f"INCIDENT_{sev}", sess.id)

    if decision == "TERMINATE":
        rec("AGENT_PAUSED", "Agent halted: " + (a.matched_rules[0]["reason"] if a.matched_rules else "TERMINATE rule fired."))
        hub.publish("agent_status", {"agent_id": agent.id, "status": "PAUSED", "session_id": sess.id})

    if approval is not None:
        rec("APPROVAL_REQUESTED", f"Human approval required for {action_type}.", decision=decision)
        hub.publish("approval_requested", {
            "id": approval.id, "action_id": action.id, "session_id": sess.id, "agent_id": agent.id,
            "agent_name": agent.name, "action_type": action_type, "risk_score": a.risk.risk_score,
            "reason": a.explanation})

    out = action_to_dict(action)
    out.update(executed=executed, simulated_effects=effects, agent_status=agent_state, trust=a.trust,
               tainted=bool(sess.tainted), guard_bypassed=bool(bypass_guard and status == "BYPASSED"))
    hub.publish("action", out)

    return {"action": out, "decision": decision, "incident_id": incident.id if incident else None,
            "approval_id": approval.id if approval else None, "executed": executed,
            "analysis": payload_json}
