"""Dynamic agent trust score, 0..100, computed from recorded history.

    trust = 100
            - recency-weighted incident penalties     (severity x recovery outcome)
            - policy-violation rate     x violation_rate_weight
            - anomaly rate (>= 0.6)     x anomaly_rate_weight
            - blocked-action rate       x block_rate_weight
            - latest behavioural drift  x drift_weight
            + credit for clean completed sessions     (bounded)

Sessions are weighted by recency (decay^i, i = sessions ago), so trust recovers
as an agent behaves, and an incident that was fully recovered costs less than
one that was not. All weights live in agent_policy.json. Nothing is random.

Trust feeds back into enforcement: it contributes to the risk score
(behavior_context) and rule R13 asks for human approval for medium-risk actions
from a low-trust agent. That is a zero-trust property: an agent's past does not
grant it a free pass, and a bad past tightens its future.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.database.models import (
    Action, Agent, DriftSnapshot, Incident, Session_, TrustSnapshot,
)
from backend.app.services import audit
from backend.app.services.policy_engine import policy_engine


def band(score: float) -> str:
    return "TRUSTED" if score >= 80 else "WATCH" if score >= 60 else "RESTRICTED" if score >= 40 else "UNTRUSTED"


def compute(db: Session, agent_id: str) -> Dict[str, Any]:
    cfg = policy_engine.policy["trust"]
    sessions: List[Session_] = (db.query(Session_).filter(Session_.agent_id == agent_id)
                                  .order_by(Session_.started_at.desc()).limit(cfg["window_sessions"]).all())
    if not sessions:
        return {"score": 100.0, "band": "TRUSTED", "n_sessions": 0, "components": {}, "note": "No history yet."}

    inc_pen = 0.0
    w_sum = v_sum = a_sum = b_sum = 0.0
    clean = 0
    for i, s in enumerate(sessions):
        d = cfg["recency_decay"] ** i
        acts = db.query(Action).filter(Action.session_id == s.id).all()
        incs = db.query(Incident).filter(Incident.session_id == s.id).all()
        for inc in incs:
            f = {"RESOLVED": cfg["recovered_factor"], "RECOVERED": cfg["recovered_factor"],
                 "RECOVERY_PARTIAL": cfg["partial_factor"], "RECOVERY_FAILED": cfg["failed_recovery_factor"]}.get(inc.status, 1.0)
            inc_pen += d * cfg["incident_weight"].get(inc.severity, 5) * f
        for a in acts:
            w_sum += d
            v_sum += d * (1 if a.policy_violation else 0)
            a_sum += d * (1 if a.anomaly_score >= 0.6 else 0)
            b_sum += d * (1 if a.decision in ("BLOCK", "TERMINATE") else 0)
        if s.status == "COMPLETED" and not incs and not any(a.decision in ("BLOCK", "TERMINATE") for a in acts):
            clean += 1

    v_rate = v_sum / w_sum if w_sum else 0.0
    a_rate = a_sum / w_sum if w_sum else 0.0
    b_rate = b_sum / w_sum if w_sum else 0.0

    last_drift = (db.query(DriftSnapshot).filter(DriftSnapshot.agent_id == agent_id)
                    .order_by(DriftSnapshot.created_at.desc()).first())
    drift_excess = 0.0
    if last_drift:
        drift_excess = max(0.0, (last_drift.peak - last_drift.reference_mean) / max(1e-6, 1 - last_drift.reference_mean))

    credit = min(cfg["max_credit"], clean * cfg["clean_session_credit"])
    comps = {
        "incident_penalty": round(-inc_pen, 1),
        "violation_penalty": round(-v_rate * cfg["violation_rate_weight"], 1),
        "anomaly_penalty": round(-a_rate * cfg["anomaly_rate_weight"], 1),
        "block_penalty": round(-b_rate * cfg["block_rate_weight"], 1),
        "drift_penalty": round(-drift_excess * cfg["drift_weight"], 1),
        "clean_session_credit": round(credit, 1),
    }
    score = max(0.0, min(100.0, 100.0 + sum(comps.values())))
    return {"score": round(score, 1), "band": band(score), "n_sessions": len(sessions), "components": comps,
            "rates": {"violation": round(v_rate, 3), "anomaly": round(a_rate, 3), "blocked": round(b_rate, 3)},
            "clean_sessions": clean}


def snapshot(db: Session, agent_id: str, event: str, session_id: Optional[str] = None,
             broadcast: bool = True) -> Dict[str, Any]:
    t = compute(db, agent_id)
    prev = (db.query(TrustSnapshot).filter(TrustSnapshot.agent_id == agent_id)
              .order_by(TrustSnapshot.created_at.desc()).first())
    db.add(TrustSnapshot(agent_id=agent_id, session_id=session_id, score=t["score"], event=event,
                         components_json=json.dumps(t["components"])))
    db.commit()
    if prev is None or abs(prev.score - t["score"]) >= 0.5:
        agent = db.get(Agent, agent_id)
        audit.record(db, "TRUST_CHANGED", agent_id=agent_id, agent_name=agent.name if agent else None,
                     session_id=session_id, broadcast=broadcast,
                     reason=f"Trust {prev.score:.0f} -> {t['score']:.0f} ({event})" if prev
                            else f"Initial trust {t['score']:.0f} ({event})",
                     extra={"trust": t["score"]})
    return t


def history(db: Session, agent_id: str, limit: int = 60) -> List[Dict[str, Any]]:
    rows = (db.query(TrustSnapshot).filter(TrustSnapshot.agent_id == agent_id)
              .order_by(TrustSnapshot.created_at.asc()).all())[-limit:]
    return [{"t": r.created_at.isoformat(), "score": r.score, "event": r.event, "session_id": r.session_id}
            for r in rows]
