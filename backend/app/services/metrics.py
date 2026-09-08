"""Dashboard metrics -- all computed from the database, none hard-coded."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.app.database.models import (
    Action, Agent, Approval, Incident, RecoveryEvent, Session_,
)
from backend.app.services import sandbox

SUSPICIOUS_LEVELS = {"HIGH", "CRITICAL"}


def compute(db: Session) -> Dict[str, Any]:
    actions: List[Action] = db.query(Action).all()
    incidents: List[Incident] = db.query(Incident).all()
    approvals: List[Approval] = db.query(Approval).all()

    total = len(actions)
    blocked = [a for a in actions if a.action_status == "BLOCKED"]
    suspicious = [a for a in actions if a.risk_level in SUSPICIOUS_LEVELS]
    normal = total - len(suspicious)

    recovered = [i for i in incidents if i.status in ("RECOVERED", "RESOLVED")]
    attempted_recovery = [i for i in incidents
                          if i.status in ("RECOVERED", "RESOLVED", "RECOVERY_FAILED")]

    decided = [a for a in approvals if a.status in ("APPROVED", "REJECTED")]
    approved = [a for a in approvals if a.status == "APPROVED"]

    risk_distribution = Counter(a.risk_level for a in actions)
    incidents_by_severity = Counter(i.severity for i in incidents)

    # Agent activity over time, bucketed per minute.
    buckets: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"total": 0, "blocked": 0, "suspicious": 0})
    for a in actions:
        key = a.timestamp.strftime("%H:%M")
        buckets[key]["total"] += 1
        if a.action_status == "BLOCKED":
            buckets[key]["blocked"] += 1
        if a.risk_level in SUSPICIOUS_LEVELS:
            buckets[key]["suspicious"] += 1
    activity = [{"bucket": k, **v} for k, v in sorted(buckets.items())][-20:]

    agents = db.query(Agent).all()

    return {
        "total_actions": total,
        "normal_actions": normal,
        "suspicious_actions": len(suspicious),
        "blocked_actions": len(blocked),
        "total_incidents": len(incidents),
        "critical_incidents": incidents_by_severity.get("CRITICAL", 0),
        "active_incidents": len([i for i in incidents
                                 if i.status in ("OPEN", "RECOVERING", "RECOVERY_FAILED")]),
        "recovered_incidents": len(recovered),
        "recovery_success_rate": round(
            100.0 * len(recovered) / len(attempted_recovery), 1) if attempted_recovery else None,
        "avg_anomaly_score": round(sum(a.anomaly_score for a in actions) / total, 3) if total else 0.0,
        "avg_risk_score": round(sum(a.risk_score for a in actions) / total, 1) if total else 0.0,
        "pending_approvals": len([a for a in approvals if a.status == "PENDING"]),
        "human_approval_rate": round(
            100.0 * len(approved) / len(decided), 1) if decided else None,
        "active_agents": len([a for a in agents if a.status in ("RUNNING", "SUSPICIOUS")]),
        "paused_agents": len([a for a in agents if a.status == "PAUSED"]),
        "total_sessions": db.query(Session_).count(),
        "recovery_events": db.query(RecoveryEvent).count(),
        "risk_distribution": [
            {"level": lvl, "count": risk_distribution.get(lvl, 0)}
            for lvl in ("LOW", "MEDIUM", "HIGH", "CRITICAL")],
        "incidents_by_severity": [
            {"severity": s, "count": incidents_by_severity.get(s, 0)}
            for s in ("MEDIUM", "HIGH", "CRITICAL")],
        "normal_vs_suspicious": [
            {"name": "Normal", "value": normal},
            {"name": "Suspicious", "value": len(suspicious)},
        ],
        "activity": activity,
        "environment": sandbox.snapshot(db),
    }
