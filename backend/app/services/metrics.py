"""Dashboard metrics -- all computed from the database, none hard-coded."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.app.database.models import (
    Action, Agent, Approval, DriftSnapshot, Incident, RecoveryEvent, Session_,
)
from backend.app.services import baseline, sandbox, trust as trust_svc

SUSPICIOUS_LEVELS = {"HIGH", "CRITICAL"}
ACTIVE_INCIDENT = ("OPEN", "RECOVERING", "RECOVERY_PARTIAL", "RECOVERY_FAILED")


def agent_summaries(db: Session) -> List[Dict[str, Any]]:
    out = []
    for a in db.query(Agent).order_by(Agent.name).all():
        t = trust_svc.compute(db, a.id)
        fp = baseline.active_fingerprint(db, a)
        last = (db.query(DriftSnapshot).filter(DriftSnapshot.agent_id == a.id)
                  .order_by(DriftSnapshot.created_at.desc()).first())
        out.append({
            "id": a.id, "name": a.name, "status": a.status, "purpose": a.purpose,
            "trust": t["score"], "trust_band": t["band"],
            "baseline_version": fp.version, "drift_threshold": round(fp.drift_threshold, 3),
            "reference_drift": round(fp.ref_drift.get("mean", 0.0), 3),
            "last_drift_peak": round(last.peak, 3) if last else None,
            "active_incidents": db.query(Incident).filter(Incident.agent_id == a.id,
                                                          Incident.status.in_(ACTIVE_INCIDENT)).count(),
        })
    return out


def compute(db: Session) -> Dict[str, Any]:
    actions: List[Action] = db.query(Action).all()
    incidents: List[Incident] = db.query(Incident).all()
    approvals: List[Approval] = db.query(Approval).all()

    total = len(actions)
    blocked = [a for a in actions if a.action_status == "BLOCKED"]
    suspicious = [a for a in actions if a.risk_level in SUSPICIOUS_LEVELS]
    normal = total - len(suspicious)

    attempted = [i for i in incidents if i.status in ("RESOLVED", "RECOVERY_PARTIAL", "RECOVERY_FAILED")]
    resolved = [i for i in attempted if i.status == "RESOLVED"]
    decided = [a for a in approvals if a.status in ("APPROVED", "REJECTED")]
    approved = [a for a in decided if a.status == "APPROVED"]

    by_sev = Counter(i.severity for i in incidents)
    by_status = Counter(i.status for i in incidents)
    risk_dist = Counter(a.risk_level for a in actions)
    decisions = Counter(a.decision for a in actions)

    buckets: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "blocked": 0, "suspicious": 0})
    for a in actions:
        k = a.timestamp.strftime("%H:%M")
        buckets[k]["total"] += 1
        buckets[k]["blocked"] += int(a.action_status == "BLOCKED")
        buckets[k]["suspicious"] += int(a.risk_level in SUSPICIOUS_LEVELS)
    activity = [{"bucket": k, **v} for k, v in sorted(buckets.items())][-20:]

    # measured decision latency (context + analysis), from stored per-action timings
    lat: Dict[str, List[float]] = defaultdict(list)
    for a in actions[-300:]:
        try:
            for k, v in json.loads(a.risk_factors_json).get("latency_ms", {}).items():
                lat[k].append(v)
        except Exception:
            pass
    latency = {k: round(sum(v) / len(v), 2) for k, v in lat.items()} if lat else {}

    drift_rows = (db.query(DriftSnapshot).order_by(DriftSnapshot.created_at.asc()).all())[-24:]
    drift_history = []
    for d in drift_rows:
        ag = db.get(Agent, d.agent_id)
        drift_history.append({"agent": ag.name if ag else d.agent_id, "session_id": d.session_id,
                              "peak": round(d.peak, 3), "final": round(d.final, 3),
                              "threshold": round(d.threshold, 3), "reference": round(d.reference_mean, 3),
                              "t": d.created_at.isoformat()})

    agents = agent_summaries(db)
    return {
        "total_actions": total, "normal_actions": normal, "suspicious_actions": len(suspicious),
        "blocked_actions": len(blocked),
        "total_incidents": len(incidents), "critical_incidents": by_sev.get("CRITICAL", 0),
        "active_incidents": sum(1 for i in incidents if i.status in ACTIVE_INCIDENT),
        "recovered_incidents": len(resolved),
        "recovery_success_rate": round(100.0 * len(resolved) / len(attempted), 1) if attempted else None,
        "recovery_partial": by_status.get("RECOVERY_PARTIAL", 0), "recovery_failed": by_status.get("RECOVERY_FAILED", 0),
        "avg_anomaly_score": round(sum(a.anomaly_score for a in actions) / total, 3) if total else 0.0,
        "avg_risk_score": round(sum(a.risk_score for a in actions) / total, 1) if total else 0.0,
        "pending_approvals": sum(1 for a in approvals if a.status == "PENDING"),
        "human_approval_rate": round(100.0 * len(approved) / len(decided), 1) if decided else None,
        "active_agents": sum(1 for a in agents if a["status"] in ("RUNNING", "SUSPICIOUS")),
        "paused_agents": sum(1 for a in agents if a["status"] == "PAUSED"),
        "total_sessions": db.query(Session_).count(), "recovery_events": db.query(RecoveryEvent).count(),
        "min_trust": min((a["trust"] for a in agents), default=100.0),
        "agents": agents,
        "decisions": [{"decision": d, "count": decisions.get(d, 0)}
                      for d in ("ALLOW", "MONITOR", "REQUIRE_APPROVAL", "BLOCK", "TERMINATE")],
        "risk_distribution": [{"level": l, "count": risk_dist.get(l, 0)} for l in ("LOW", "MEDIUM", "HIGH", "CRITICAL")],
        "incidents_by_severity": [{"severity": s, "count": by_sev.get(s, 0)} for s in ("MEDIUM", "HIGH", "CRITICAL")],
        "normal_vs_suspicious": [{"name": "Normal", "value": normal}, {"name": "Suspicious", "value": len(suspicious)}],
        "activity": activity, "drift_history": drift_history, "latency_ms": latency,
        "environment": sandbox.snapshot(db),
    }
