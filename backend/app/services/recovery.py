"""Recovery and verification as an explicit, step-by-step procedure.

  1 PAUSE_AGENT             the agent must be halted before anything is touched
  2 REVERT_PERMISSIONS      permission / security-control resources first
  3 RESTORE_RESOURCES       data and services, resource by resource
  4 INTEGRITY_VERIFICATION  re-inspect EVERY resource: state and checksum

Outcome is SUCCESS, PARTIAL or FAILED and is derived from step 4, never assumed.
A fault can be injected (chaos-style) so partial and failed recoveries can be
demonstrated and retried:

  restore_failure  the primary database backup cannot be restored
  partial          roughly half of the damaged resources have no usable backup
  corruption       resources are restored but silently corrupted (checksum mismatch)

State rollback cannot recall data that has already left the environment: if an
exfiltration was executed the report says so under `residual_risk`.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.database.models import Agent, Incident, RecoveryEvent, Session_, utcnow
from backend.app.services import audit, sandbox
from backend.app.services.envsim import IRREVERSIBLE
from backend.app.services.events import hub

FAULTS = {"restore_failure", "partial", "corruption"}


def recovery_events(db: Session, incident_id: str) -> List[dict]:
    rows = (db.query(RecoveryEvent).filter(RecoveryEvent.incident_id == incident_id)
              .order_by(RecoveryEvent.timestamp.asc()).all())
    return [{"id": r.id, "incident_id": r.incident_id, "recovery_action": r.recovery_action,
             "previous_state": json.loads(r.previous_state or "{}"),
             "restored_state": json.loads(r.restored_state or "{}"),
             "recovery_status": r.recovery_status, "detail": r.detail,
             "timestamp": r.timestamp.isoformat()} for r in rows]


def _record(db: Session, inc: Incident, step: str, status: str, detail: str,
            prev: Dict[str, Any] | None = None, restored: Dict[str, Any] | None = None) -> None:
    db.add(RecoveryEvent(incident_id=inc.id, recovery_action=step, recovery_status=status, detail=detail,
                         previous_state=json.dumps(prev or {}), restored_state=json.dumps(restored or {})))
    db.commit()


def run_recovery(db: Session, incident: Incident, fault: Optional[str] = None,
                 pace_s: float = 0.0) -> Dict[str, Any]:
    if fault and fault not in FAULTS:
        raise ValueError(f"Unknown fault '{fault}'. Valid: {', '.join(sorted(FAULTS))}")
    agent = db.get(Agent, incident.agent_id)
    sess = db.get(Session_, incident.session_id)
    agent_name = agent.name if agent else None
    incident.recovery_attempts = (incident.recovery_attempts or 0) + 1
    attempt = incident.recovery_attempts
    incident.status = "RECOVERING"
    db.commit()

    before = sandbox.snapshot(db)
    steps: List[Dict[str, Any]] = []
    damaged_names = [r.name for r in sandbox.damaged(db)]
    audit.record(db, "RECOVERY_STARTED", agent_id=incident.agent_id, agent_name=agent_name,
                 session_id=incident.session_id, incident_id=incident.id,
                 reason=f"Recovery attempt {attempt} for {incident.reference}: "
                        f"{len(damaged_names)} damaged resource(s)" + (f", fault injected: {fault}" if fault else "") + ".")
    hub.publish("recovery", {"session_id": incident.session_id, "incident_id": incident.id, "reference": incident.reference,
                             "stage": "STARTED", "attempt": attempt, "fault": fault, "damaged": damaged_names})

    def emit(step: Dict[str, Any]) -> None:
        if pace_s:
            time.sleep(pace_s)      # only used off the event loop (judge mode), so viewers can follow
        steps.append(step)
        _record(db, incident, step["step"], step["status"], step["detail"],
                step.get("previous"), step.get("restored"))
        audit.record(db, "RECOVERY_STEP", agent_id=incident.agent_id, agent_name=agent_name,
                     session_id=incident.session_id, incident_id=incident.id,
                     decision=step["status"], reason=f"{step['step']}: {step['detail']}")
        hub.publish("recovery", {"session_id": incident.session_id, "incident_id": incident.id, "reference": incident.reference,
                                 "stage": "STEP", "step": step, "attempt": attempt})

    # 1 ---- pause the agent
    if agent and agent.status not in ("PAUSED", "IDLE", "STOPPED"):
        agent.status = "PAUSED"
    if sess and sess.status in ("RUNNING", "AWAITING_APPROVAL"):
        sess.status = "PAUSED"
    db.commit()
    paused = (agent is None) or agent.status in ("PAUSED", "IDLE", "STOPPED")
    emit({"step": "PAUSE_AGENT", "status": "OK" if paused else "FAILED",
          "detail": "Agent is halted; no further actions can execute." if paused else "Agent could not be paused."})

    # 2 ---- permissions and security controls first
    reverted: List[str] = []
    for r in list(sandbox.damaged(db)):
        if r.kind in ("permissions", "security"):
            sandbox.restore_resource(db, r.name)
            reverted.append(r.name)
    emit({"step": "REVERT_PERMISSIONS", "status": "OK",
          "detail": ("Reverted: " + ", ".join(reverted)) if reverted else "No permission or security-control change to revert.",
          "resources": reverted})

    # 3 ---- data and services (this is where faults bite)
    remaining = [r.name for r in sandbox.damaged(db)]
    restored: List[str] = []
    failed: List[str] = []
    skipped: List[str] = []
    for i, name in enumerate(remaining):
        if fault == "restore_failure" and (name == "db/primary" or (i == 0 and "db/primary" not in remaining)):
            failed.append(name)
            continue
        if fault == "partial" and i % 2 == 1:
            skipped.append(name)
            continue
        sandbox.restore_resource(db, name, corrupt=(fault == "corruption"))
        restored.append(name)
    if not remaining:
        st, detail = "OK", "No data or service resource had deviated from baseline."
    elif failed or skipped:
        st = "PARTIAL" if restored else "FAILED"
        detail = (f"Restored {len(restored)}/{len(remaining)}." + (f" Restore FAILED: {', '.join(failed)}." if failed else "")
                  + (f" No usable backup for: {', '.join(skipped)}." if skipped else ""))
    else:
        st, detail = "OK", f"Restored {len(restored)} resource(s): " + ", ".join(restored) + "."
    emit({"step": "RESTORE_RESOURCES", "status": st, "detail": detail, "resources": restored,
          "failed": failed + skipped, "previous": {n: before.get(n) for n in remaining}})

    # 4 ---- independent verification
    result = sandbox.verify(db)
    verified = result["verified"]
    integrity_bad = [c["resource"] for c in result["failed_checks"] if c["state_ok"] and not c["integrity_ok"]]
    emit({"step": "INTEGRITY_VERIFICATION", "status": "OK" if verified else "FAILED",
          "detail": result["summary"], "restored": sandbox.snapshot(db),
          "integrity_mismatch": integrity_bad})

    # ---- outcome
    any_restored = bool(reverted or restored)
    outcome = "SUCCESS" if verified else ("PARTIAL" if any_restored else "FAILED")
    exfil = [c for c in (before or {}).items() if c[1] in IRREVERSIBLE]
    residual = ([f"{n}: data marked {s} left the environment; rolling state back cannot recall it. "
                 "External remediation (rotate secrets, notify data owners) is required." for n, s in exfil]
                if exfil else [])

    incident.status = {"SUCCESS": "RESOLVED", "PARTIAL": "RECOVERY_PARTIAL", "FAILED": "RECOVERY_FAILED"}[outcome]
    if outcome == "SUCCESS":
        incident.resolved_at = utcnow()
    db.commit()

    ev = {"SUCCESS": "RECOVERY_VERIFIED", "PARTIAL": "RECOVERY_PARTIAL", "FAILED": "RECOVERY_FAILED"}[outcome]
    audit.record(db, ev, agent_id=incident.agent_id, agent_name=agent_name, session_id=incident.session_id,
                 incident_id=incident.id, decision=outcome,
                 reason=f"Attempt {attempt}: {outcome}. {result['summary']}")
    if outcome == "SUCCESS":
        audit.record(db, "INCIDENT_RESOLVED", agent_id=incident.agent_id, agent_name=agent_name,
                     session_id=incident.session_id, incident_id=incident.id,
                     reason=f"{incident.reference} resolved: simulated state and integrity verified.")
        if sess and sess.status == "PAUSED":
            sess.status = "STOPPED"
        if agent:
            agent.status = "IDLE"
        db.commit()
        hub.publish("agent_status", {"agent_id": incident.agent_id, "status": "IDLE",
                                     "session_id": incident.session_id})
    hub.publish("recovery", {"session_id": incident.session_id, "incident_id": incident.id, "reference": incident.reference,
                             "stage": "VERIFIED" if outcome == "SUCCESS" else outcome,
                             "outcome": outcome, "verification": result, "attempt": attempt,
                             "steps": steps, "residual_risk": residual})

    from backend.app.services import trust as trust_svc
    trust_svc.snapshot(db, incident.agent_id, f"RECOVERY_{outcome}", incident.session_id)

    return {"incident_id": incident.id, "reference": incident.reference, "status": incident.status,
            "outcome": outcome, "verified": verified, "attempt": attempt, "fault": fault,
            "steps": steps, "verification": result, "residual_risk": residual,
            "previous_state": before, "restored_state": sandbox.snapshot(db),
            "events": recovery_events(db, incident.id)}
