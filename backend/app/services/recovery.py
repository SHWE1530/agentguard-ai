"""Recovery and state verification.

Recovery restores the simulated environment to its known-good baseline.
Verification then re-inspects that environment and reports the truth --
"RECOVERY VERIFIED" is only emitted when every check actually passes.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from sqlalchemy.orm import Session

from backend.app.database.models import (
    Agent, Incident, RecoveryEvent, Session_, utcnow,
)
from backend.app.services import audit, sandbox
from backend.app.services.events import hub


def recovery_events(db: Session, incident_id: str) -> list[dict]:
    rows = (db.query(RecoveryEvent)
              .filter(RecoveryEvent.incident_id == incident_id)
              .order_by(RecoveryEvent.timestamp.asc()).all())
    return [{
        "id": r.id, "incident_id": r.incident_id, "recovery_action": r.recovery_action,
        "previous_state": json.loads(r.previous_state or "{}"),
        "restored_state": json.loads(r.restored_state or "{}"),
        "recovery_status": r.recovery_status, "detail": r.detail,
        "timestamp": r.timestamp.isoformat(),
    } for r in rows]


def run_recovery(db: Session, incident: Incident) -> Dict[str, Any]:
    """Roll back the simulated world, then verify it. Returns the outcome."""
    agent = db.get(Agent, incident.agent_id)
    agent_name = agent.name if agent else None

    previous = sandbox.snapshot(db)
    incident.status = "RECOVERING"
    db.commit()

    db.add(RecoveryEvent(
        incident_id=incident.id, recovery_action="SNAPSHOT_AND_ROLLBACK_INITIATED",
        previous_state=json.dumps(previous), restored_state=json.dumps({}),
        recovery_status="STARTED",
        detail="Captured the compromised simulated state before rollback."))
    db.commit()
    audit.record(db, "RECOVERY_STARTED", agent_id=incident.agent_id, agent_name=agent_name,
                 session_id=incident.session_id, incident_id=incident.id,
                 reason=f"Recovery started for {incident.reference}.")
    hub.publish("recovery", {"incident_id": incident.id, "reference": incident.reference,
                             "stage": "STARTED", "previous_state": previous})

    # ---- rollback --------------------------------------------------------
    changed = sandbox.restore(db)
    restored = sandbox.snapshot(db)
    db.add(RecoveryEvent(
        incident_id=incident.id, recovery_action="RESTORE_BASELINE_STATE",
        previous_state=json.dumps(previous), restored_state=json.dumps(restored),
        recovery_status="COMPLETED",
        detail=(f"Restored {len(changed)} simulated resource(s): "
                + ", ".join(f"{k} {v['from']}->{v['to']}" for k, v in changed.items())
                if changed else "No simulated resource had deviated from baseline.")))
    db.commit()
    audit.record(db, "RECOVERY_COMPLETED", agent_id=incident.agent_id, agent_name=agent_name,
                 session_id=incident.session_id, incident_id=incident.id,
                 reason=f"{len(changed)} simulated resource(s) rolled back to baseline.")
    hub.publish("recovery", {"incident_id": incident.id, "reference": incident.reference,
                             "stage": "RESTORED", "changed": changed,
                             "restored_state": restored})

    # ---- verification ----------------------------------------------------
    result = sandbox.verify(db)
    verified = result["verified"]
    db.add(RecoveryEvent(
        incident_id=incident.id, recovery_action="STATE_VERIFICATION",
        previous_state=json.dumps(previous), restored_state=json.dumps(restored),
        recovery_status="VERIFIED" if verified else "VERIFICATION_FAILED",
        detail=result["summary"]))

    incident.status = "RECOVERED" if verified else "RECOVERY_FAILED"
    if verified:
        incident.resolved_at = utcnow()
    db.commit()

    audit.record(db, "RECOVERY_VERIFIED" if verified else "RECOVERY_FAILED",
                 agent_id=incident.agent_id, agent_name=agent_name,
                 session_id=incident.session_id, incident_id=incident.id,
                 reason=result["summary"])
    hub.publish("recovery", {"incident_id": incident.id, "reference": incident.reference,
                             "stage": "VERIFIED" if verified else "VERIFICATION_FAILED",
                             "verification": result})

    if verified:
        incident.status = "RESOLVED"
        db.commit()
        audit.record(db, "INCIDENT_RESOLVED", agent_id=incident.agent_id,
                     agent_name=agent_name, session_id=incident.session_id,
                     incident_id=incident.id,
                     reason=f"{incident.reference} resolved: simulated state verified healthy.")
        sess = db.get(Session_, incident.session_id)
        if sess and sess.status == "PAUSED":
            sess.status = "STOPPED"
        if agent:
            agent.status = "IDLE"
        db.commit()
        hub.publish("agent_status", {"agent_id": incident.agent_id, "status": "IDLE",
                                     "session_id": incident.session_id})

    return {
        "incident_id": incident.id,
        "reference": incident.reference,
        "status": incident.status,
        "verified": verified,
        "verification": result,
        "previous_state": previous,
        "restored_state": restored,
        "changed": changed,
        "events": recovery_events(db, incident.id),
    }
