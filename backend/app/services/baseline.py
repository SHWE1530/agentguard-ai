"""Adaptive, poisoning-resistant behavioural baseline.

"Normal" is not frozen: the fingerprint is versioned and can be updated from
VERIFIED-SAFE sessions. Suspicious behaviour must never be learned as normal, so
a session is only eligible if ALL of these hold:

  * it completed (was not paused, stopped or held for approval)
  * enough steps (min_steps)
  * no BLOCK / TERMINATE / REQUIRE_APPROVAL decision anywhere in it
  * no incident, not tainted by untrusted content
  * peak risk <= max_peak_risk and peak drift <= max_peak_drift
  * at most max_failures failed actions

and, even when eligible, the candidate fingerprint must stay close to BOTH the
current version (max_step_divergence) and the ORIGINAL v1 anchor
(max_anchor_divergence). The anchor check is what defeats slow poisoning: many
individually-acceptable small shifts cannot walk the baseline away from where
it started.

Every accept/reject is written to the audit trail with its reasons.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.agent.catalog import get_spec, permission_value
from backend.app.database.models import Action, Agent, AgentBaseline, Incident, Session_
from backend.app.services import audit
from backend.app.services.fingerprint import Fingerprint
from backend.app.services.ml_detector import detector
from backend.app.services.policy_engine import policy_engine
from backend.app.services.steps import StepRec

_cache: Dict[str, Fingerprint] = {}


def _active_row(db: Session, agent_id: str) -> Optional[AgentBaseline]:
    return (db.query(AgentBaseline).filter(AgentBaseline.agent_id == agent_id, AgentBaseline.active.is_(True))
              .order_by(AgentBaseline.version.desc()).first())


def ensure(db: Session, agent: Agent) -> AgentBaseline:
    row = _active_row(db, agent.id)
    if row is None:
        fp = detector.bootstrap_fingerprint(agent.name)
        row = AgentBaseline(agent_id=agent.id, version=1, source="bootstrap", active=True,
                            data_json=json.dumps(fp.to_dict()), anchor_divergence=0.0,
                            note="Learned from the synthetic normal-behaviour training corpus.")
        db.add(row)
        db.commit()
    return row


def active_fingerprint(db: Session, agent: Agent) -> Fingerprint:
    row = ensure(db, agent)
    key = f"{agent.id}:{row.version}"
    fp = _cache.get(key)
    if fp is None:
        fp = Fingerprint.from_dict(json.loads(row.data_json))
        _cache.clear()
        _cache[key] = fp
    return fp


def anchor_fingerprint(db: Session, agent: Agent) -> Fingerprint:
    row = (db.query(AgentBaseline).filter(AgentBaseline.agent_id == agent.id, AgentBaseline.version == 1).first())
    return Fingerprint.from_dict(json.loads(row.data_json)) if row else detector.bootstrap_fingerprint(agent.name)


def clear_cache() -> None:
    _cache.clear()


def history(db: Session, agent_id: str) -> List[Dict[str, Any]]:
    rows = db.query(AgentBaseline).filter(AgentBaseline.agent_id == agent_id).order_by(AgentBaseline.version.asc()).all()
    return [{"version": r.version, "source": r.source, "active": r.active,
             "anchor_divergence": round(r.anchor_divergence, 4), "note": r.note,
             "created_at": r.created_at.isoformat()} for r in rows]


def session_steps(db: Session, sess: Session_) -> List[StepRec]:
    acts = db.query(Action).filter(Action.session_id == sess.id).order_by(Action.step_index.asc()).all()
    out = []
    for a in acts:
        spec = get_spec(a.action_type)
        out.append(StepRec(a.action_type, a.interval_s, permission_value(spec.permission_level),
                           spec.resource_sensitivity, spec.resource, spec.tool_name, a.task_relevance,
                           a.execution_result == "FAILED", a.decision in ("BLOCK", "TERMINATE")))
    return out


def eligibility(db: Session, sess: Session_) -> Dict[str, Any]:
    cfg = policy_engine.policy["baseline"]
    acts = db.query(Action).filter(Action.session_id == sess.id).all()
    reasons: List[str] = []
    if sess.status != "COMPLETED":
        reasons.append(f"session ended {sess.status}, not COMPLETED")
    if len(acts) < cfg["min_steps"]:
        reasons.append(f"only {len(acts)} step(s); need at least {cfg['min_steps']}")
    bad = [a for a in acts if a.decision in ("BLOCK", "TERMINATE", "REQUIRE_APPROVAL")]
    if bad:
        reasons.append(f"{len(bad)} action(s) were blocked or held ({', '.join(sorted({a.action_type for a in bad}))})")
    if sess.tainted:
        reasons.append("session ingested untrusted content with injection indicators")
    if db.query(Incident).filter(Incident.session_id == sess.id).count():
        reasons.append("an incident was raised in this session")
    peak_risk = max((a.risk_score for a in acts), default=0.0)
    if peak_risk > cfg["max_peak_risk"]:
        reasons.append(f"peak risk {peak_risk:.0f} exceeds {cfg['max_peak_risk']}")
    peak_drift = 0.0
    for a in acts:
        try:
            peak_drift = max(peak_drift, json.loads(a.risk_factors_json).get("drift", {}).get("score", 0.0))
        except Exception:
            pass
    if peak_drift > cfg["max_peak_drift"]:
        reasons.append(f"peak drift {peak_drift:.2f} exceeds {cfg['max_peak_drift']}")
    fails = sum(1 for a in acts if a.execution_result == "FAILED")
    if fails > cfg["max_failures"]:
        reasons.append(f"{fails} failed actions (max {cfg['max_failures']})")
    return {"eligible": not reasons, "reasons": reasons, "peak_risk": peak_risk, "peak_drift": round(peak_drift, 3)}


def check_candidate(cur: Fingerprint, anchor: Fingerprint, steps: List[List[StepRec]],
                    cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Pure poisoning check: would learning these sessions move the baseline too far?

    Two independent limits: one update may not shift the baseline by more than
    max_step_divergence, and the result may never sit further than
    max_anchor_divergence from the ORIGINAL anchor. The second stops slow
    poisoning, where every individual step is small.
    """
    cand = cur.updated(steps, decay=cfg["decay"])
    step_div, anchor_div = cur.divergence(cand), anchor.divergence(cand)
    reasons = []
    if step_div > cfg["max_step_divergence"]:
        reasons.append(f"update would shift the baseline by {step_div:.3f} (max {cfg['max_step_divergence']})")
    if anchor_div > cfg["max_anchor_divergence"]:
        reasons.append(f"baseline would drift {anchor_div:.3f} from its original anchor (max {cfg['max_anchor_divergence']})")
    return {"candidate": cand, "step_divergence": step_div, "anchor_divergence": anchor_div, "reasons": reasons}


def consider_session(db: Session, sess: Session_) -> Dict[str, Any]:
    """Learn from a session iff it passes every safeguard. Always audited."""
    agent = db.get(Agent, sess.agent_id)
    cfg = policy_engine.policy["baseline"]
    el = eligibility(db, sess)
    result: Dict[str, Any] = {"session_id": sess.id, "accepted": False, "reasons": list(el["reasons"]),
                              "peak_risk": el["peak_risk"], "peak_drift": el["peak_drift"]}
    cur_row = ensure(db, agent)
    cur = active_fingerprint(db, agent)
    if el["eligible"]:
        chk = check_candidate(cur, anchor_fingerprint(db, agent), [session_steps(db, sess)], cfg)
        result.update(step_divergence=round(chk["step_divergence"], 4), anchor_divergence=round(chk["anchor_divergence"], 4))
        result["reasons"] += chk["reasons"]
        if not result["reasons"]:
            cand = chk["candidate"]
            cur_row.active = False
            db.add(AgentBaseline(agent_id=agent.id, version=cand.version, source="adaptive", active=True,
                                 data_json=json.dumps(cand.to_dict()), anchor_divergence=chk["anchor_divergence"],
                                 note=f"Learned from verified-safe session {sess.id}."))
            db.commit()
            clear_cache()
            result.update(accepted=True, version=cand.version)
    ev = "BASELINE_UPDATED" if result["accepted"] else "BASELINE_UPDATE_REJECTED"
    audit.record(db, ev, agent_id=agent.id, agent_name=agent.name, session_id=sess.id,
                 decision="ACCEPTED" if result["accepted"] else "REJECTED",
                 reason=(f"Baseline v{result['version']} created from verified-safe session."
                         if result["accepted"] else "Not learned as normal: " + "; ".join(result["reasons"]) + "."))
    return result
