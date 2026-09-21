"""Evidence bundles for the human-approval workflow.

An approval is not a bare Approve/Reject: the operator sees the action, the
risk and why, the evidence behind it, the modelled impact, and a safer
alternative. They can also REQUEST MORE EVIDENCE, which runs additional
diagnostics against the current simulated environment and the agent's record
and appends the findings before anything is decided.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.app.agent.catalog import get_spec
from backend.app.database.models import Action, Approval, Incident, Session_
from backend.app.services import envsim, sandbox, trust as trust_svc
from backend.app.services.policy_engine import policy_engine


def initial(a: Any) -> Dict[str, Any]:
    """Evidence captured at the moment the action was held. `a` is an Analysis."""
    top = sorted(a.risk.factors.items(), key=lambda kv: -kv[1])[:4]
    return {
        "round": 0,
        "top_risk_factors": [{"factor": k, "value": v, "contribution": a.risk.contributions.get(k)} for k, v in top],
        "intent": {"task_type": a.task_type, "alignment": round(a.alignment, 3)},
        "anomaly": a.anomaly,
        "sequence_patterns": a.seq.patterns,
        "matched_rules": a.matched_rules,
        "policy_violations": [{"code": v, "detail": a.policy.details.get(v, "")} for v in a.policy.violations],
        "recent_actions": [{"action": s.action, "alignment": round(s.alignment, 2), "blocked": s.blocked}
                           for s in a.history[-6:]],
        "trust": a.trust,
        "drift": round(a.drift["score"], 3),
        "findings": [],
    }


def gather(db: Session, approval: Approval) -> Dict[str, Any]:
    """Run additional diagnostics and append them as a new evidence round."""
    ev = json.loads(approval.evidence_json or "{}")
    rnd = int(approval.evidence_rounds or 0) + 1
    spec = get_spec(approval.action_type)
    env = sandbox.snapshot(db)
    findings: List[Dict[str, str]] = []

    state = env.get(spec.resource, "n/a (resource is not tracked by the sandbox)")
    findings.append({
        "source": "Target health probe (simulated)",
        "finding": (f"'{spec.resource}' reports state {state}."),
        "signal": "supports_approval" if state != "HEALTHY" and spec.action_type == "FAILOVER_DATABASE"
        else "supports_rejection" if state == "HEALTHY" and spec.action_type == "FAILOVER_DATABASE" else "neutral",
    })
    if spec.action_type == "FAILOVER_DATABASE":
        findings.append({
            "source": "Failover precondition",
            "finding": ("Primary is HEALTHY: failing over now would take a working primary offline."
                        if env.get("db/primary") == "HEALTHY" else
                        f"Primary is {env.get('db/primary')}: failover is a plausible remedy."),
            "signal": "supports_rejection" if env.get("db/primary") == "HEALTHY" else "supports_approval"})

    prior = db.query(Approval).filter(Approval.action_type == approval.action_type, Approval.id != approval.id,
                                      Approval.status.in_(("APPROVED", "REJECTED"))).all()
    ap = sum(1 for p in prior if p.status == "APPROVED")
    findings.append({"source": "Precedent",
                     "finding": f"{len(prior)} earlier decision(s) on {approval.action_type}: {ap} approved, {len(prior) - ap} rejected.",
                     "signal": "neutral"})

    t = trust_svc.compute(db, approval.agent_id)
    findings.append({"source": "Agent record",
                     "finding": f"Trust {t['score']:.0f}/100 ({t['band']}); {t['n_sessions']} recent session(s), "
                                f"{t.get('clean_sessions', 0)} clean.",
                     "signal": "supports_approval" if t["score"] >= 80 else "supports_rejection" if t["score"] < 50 else "neutral"})

    incs = (db.query(Incident).filter(Incident.agent_id == approval.agent_id)
              .order_by(Incident.created_at.desc()).limit(3).all())
    findings.append({"source": "Recent incidents",
                     "finding": ("; ".join(f"{i.reference} {i.severity} ({i.status})" for i in incs) or "None on record."),
                     "signal": "supports_rejection" if incs and any(i.status != "RESOLVED" for i in incs) else "neutral"})

    cf = envsim.counterfactual(env, approval.action_type, 1.0, [], None)
    findings.append({"source": "Counterfactual re-run (current environment)",
                     "finding": (f"If executed now: {len(cf['allow']['resources_impacted'])} resource(s) change, "
                                 f"~{cf['allow']['est_recovery_minutes']} min modelled recovery."),
                     "signal": "neutral"})

    ev.setdefault("rounds", []).append({"round": rnd, "findings": findings})
    ev["round"] = rnd
    approval.evidence_json = json.dumps(ev)
    approval.evidence_rounds = rnd
    db.commit()
    return ev
