"""Append-only audit trail. Every safety-relevant event lands here and is
simultaneously broadcast to connected dashboards.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.app.database.models import AuditEvent
from backend.app.services.events import hub

# Canonical event vocabulary (also used by the audit-page filters).
EVENT_TYPES = [
    "AGENT_STARTED", "TASK_STARTED", "ACTION_EXECUTED", "ANOMALY_DETECTED", "POLICY_VIOLATION",
    "SEQUENCE_PATTERN_DETECTED", "PRIVILEGE_ESCALATION_DETECTED", "INJECTION_INDICATOR_DETECTED",
    "DRIFT_DETECTED", "RISK_CALCULATED", "ACTION_BLOCKED", "AGENT_PAUSED", "APPROVAL_REQUESTED",
    "EVIDENCE_REQUESTED", "HUMAN_APPROVAL", "HUMAN_REJECTION", "INCIDENT_CREATED", "RECOVERY_STARTED",
    "RECOVERY_STEP", "RECOVERY_VERIFIED", "RECOVERY_PARTIAL", "RECOVERY_FAILED", "INCIDENT_RESOLVED",
    "TRUST_CHANGED", "BASELINE_UPDATED", "BASELINE_UPDATE_REJECTED", "SESSION_COMPLETED", "DEMO_RESET",
]


def record(db: Session, event_type: str, *, reason: str = "",
           agent_id: Optional[str] = None, agent_name: Optional[str] = None,
           session_id: Optional[str] = None, incident_id: Optional[str] = None,
           action_type: Optional[str] = None, risk_score: Optional[float] = None,
           risk_level: Optional[str] = None, decision: Optional[str] = None,
           broadcast: bool = True, extra: Optional[Dict[str, Any]] = None) -> AuditEvent:
    ev = AuditEvent(
        event_type=event_type, reason=reason, agent_id=agent_id, agent_name=agent_name,
        session_id=session_id, incident_id=incident_id, action_type=action_type,
        risk_score=risk_score, risk_level=risk_level, decision=decision,
    )
    db.add(ev)
    db.commit()

    if broadcast:
        payload: Dict[str, Any] = {
            "id": ev.id,
            "event_type": event_type,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "session_id": session_id,
            "incident_id": incident_id,
            "action_type": action_type,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "decision": decision,
            "reason": reason,
            "timestamp": ev.timestamp.isoformat(),
        }
        if extra:
            payload.update(extra)
        hub.publish("audit", payload)
    return ev
