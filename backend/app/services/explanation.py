"""Human-readable explanations built from the signals that actually fired.

Nothing here is a canned string per severity: each sentence is emitted only
when its underlying signal is present, so two CRITICAL incidents with different
causes read differently.
"""
from __future__ import annotations

from typing import Any, Dict, List

from backend.app.agent.catalog import ActionSpec


def _band(v: float, lo: float, hi: float) -> str:
    return "Low" if v < lo else "Medium" if v < hi else "High"


def explain_action(a: Any) -> str:
    """`a` is a services.analysis.Analysis."""
    spec: ActionSpec = a.spec
    parts: List[str] = [f"The agent attempted {spec.action_type} against '{spec.resource}' ({spec.description.rstrip('.')})"]

    if a.alignment < 0.35:
        parts.append(f"The action does not serve the assigned task '{a.task_type}' "
                     f"(intent alignment {a.alignment:.2f}/1.00)")
    elif a.alignment >= 0.7:
        parts.append(f"The action is consistent with the assigned task '{a.task_type}' "
                     f"(intent alignment {a.alignment:.2f})")

    if a.anomaly >= 0.75:
        parts.append(f"The behavioural model scored it {a.anomaly:.2f}/1.00, far outside the agent's learned normal range")
    elif a.anomaly >= 0.4:
        parts.append(f"The behavioural model scored it {a.anomaly:.2f}/1.00, moderately outside the learned normal range")
    else:
        parts.append(f"The behavioural model scored it {a.anomaly:.2f}/1.00, consistent with learned behaviour")

    seq = a.seq
    if seq.bigram_dev >= 0.9 and len(a.history) > 1:
        parts.append(f"the transition {a.history[-2].action} -> {spec.action_type} has never occurred in this agent's fingerprint")
    for p in seq.patterns:
        parts.append(f"sequence pattern '{p['name']}' is at stage {p['progress']}/{p['total']} ({' -> '.join(p['path'])})")
    if seq.escalation.get("detected"):
        parts.append("privilege escalation detected: " + seq.escalation["description"].rstrip("."))
    if seq.loop.get("kind"):
        parts.append(f"{seq.loop['kind'].replace('_', ' ').lower()} detected "
                     f"({seq.loop['consecutive_same']} identical calls, {seq.loop['consecutive_failures']} consecutive failures)")
    if a.tainted:
        parts.append("the session previously ingested untrusted content containing injection indicators")
    if a.drift_alert:
        parts.append(f"behavioural drift is {a.drift['score'] * 100:.0f}% against a threshold of "
                     f"{a.drift_threshold * 100:.0f}%")
    for v in a.policy.violations[:4]:
        parts.append(a.policy.details.get(v, v).rstrip("."))

    if a.matched_rules:
        top = a.matched_rules[0]
        parts.append(f"Decision {a.decision} was driven by rule {top['id']}: {top['reason'].rstrip('.')}")
    outcome = {
        "TERMINATE": "The operation was blocked before execution and the agent was halted to prevent further simulated damage",
        "BLOCK": "The operation was blocked before it reached the simulated environment",
        "REQUIRE_APPROVAL": "Execution is held pending an explicit human decision",
        "MONITOR": "The action was allowed but flagged for closer monitoring",
        "ALLOW": "The action was allowed as routine, sanctioned work",
    }[a.decision]
    parts.append(outcome)
    return f"[{a.risk.risk_level} - risk {a.risk.risk_score:.0f}/100] " + ". ".join(parts) + "."


def allow_rationale(a: Any) -> Dict[str, Any] | None:
    """'Why was this action allowed?' -- shown for borderline allowed actions."""
    if a.decision not in ("ALLOW", "MONITOR"):
        return None
    if a.anomaly < 0.3 and not a.drift_alert:
        return None
    spec = a.spec
    overrides: List[str] = []
    if a.anomaly >= 0.3:
        overrides.append(f"the model found it {'highly' if a.anomaly >= 0.75 else 'moderately'} unusual ({a.anomaly:.2f})")
    if a.drift_alert:
        overrides.append("behavioural drift is elevated")
    counter: List[str] = []
    if a.policy.allowed:
        counter.append("it is inside this agent's capability set")
    if a.alignment >= 0.7:
        counter.append(f"it directly serves the task (alignment {a.alignment:.2f})")
    if spec.resource_sensitivity <= 0.5:
        counter.append(f"the resource is low-sensitivity ({spec.resource_sensitivity:.2f})")
    if not a.seq.patterns and not a.seq.escalation.get("detected"):
        counter.append("no attack-chain or escalation pattern is forming")
    return {
        "anomaly": f"{_band(a.anomaly, 0.4, 0.75)} ({a.anomaly:.2f})",
        "policy": "Allowed" if a.policy.allowed and not a.policy.violations else "Allowed with flags",
        "intent_alignment": f"{'High' if a.alignment >= 0.7 else 'Medium' if a.alignment >= 0.4 else 'Low'} ({a.alignment:.2f})",
        "resource_sensitivity": f"{_band(spec.resource_sensitivity, 0.4, 0.75)} ({spec.resource_sensitivity:.2f})",
        "sequence": "No chain forming" if not a.seq.patterns else f"{len(a.seq.patterns)} pattern(s) in progress",
        "final_decision": a.decision,
        "why": ("Although " + " and ".join(overrides) + ", " + "; ".join(counter)
                + f". Unusual is not the same as dangerous, so the action was {a.decision.lower().replace('_', ' ')}ed."
                if overrides else "Allowed."),
    }


def zero_trust(a: Any) -> List[Dict[str, Any]]:
    """Six per-action questions. Approval of an agent never implies approval of its actions."""
    spec = a.spec
    cf = a.counterfactual["allow"]
    top = sorted(a.risk.factors.items(), key=lambda kv: -kv[1])[:2]
    return [
        {"question": "Who is acting?",
         "answer": f"{a.agent} - trust {a.trust:.0f}/100, fingerprint v{a.fp_version}. Being an approved agent is not sufficient.",
         "ok": a.trust >= 50},
        {"question": "What is it trying to do?",
         "answer": f"{spec.action_type}: {spec.description}", "ok": spec.severity < 0.5},
        {"question": "Which resource?",
         "answer": f"'{spec.resource}' (sensitivity {spec.resource_sensitivity:.2f}, "
                   f"{'inside' if a.in_scope else 'OUTSIDE'} the task scope)",
         "ok": a.in_scope and spec.resource_sensitivity < 0.8},
        {"question": "Why is it required?",
         "answer": f"Intent alignment {a.alignment:.2f} with task '{a.task_type}'"
                   + ("" if a.alignment >= 0.35 else " - this action does not serve the task"),
         "ok": a.alignment >= 0.35},
        {"question": "What is the risk?",
         "answer": f"{a.risk.risk_score:.0f}/100 {a.risk.risk_level}; driven by "
                   + ", ".join(f"{k.replace('_', ' ')} {v:.0f}" for k, v in top),
         "ok": a.risk.risk_level in ("LOW", "MEDIUM")},
        {"question": "What happens if it fails or is allowed?",
         "answer": (f"{len(cf['resources_impacted'])} resource(s) affected, ~{cf['est_recovery_minutes']} min modelled recovery"
                    + (", irreversible" if cf["irreversible"] else "")) if cf["resources_impacted"]
                   else "No modelled change to the environment.",
         "ok": not cf["resources_impacted"]},
    ]


def explain_incident(actions: List[Dict[str, Any]]) -> str:
    """Narrative for an incident, derived from the sequence that produced it."""
    if not actions:
        return "No actions recorded for this incident."
    flagged = [x for x in actions if x["risk_level"] in ("HIGH", "CRITICAL")]
    if not flagged:
        return "The session completed without a high-risk action."
    first, worst = flagged[0], max(flagged, key=lambda x: x["risk_score"])
    chain = " -> ".join(x["action_type"] for x in actions)
    lines = [
        f"The agent began the session inside its sanctioned scope, then deviated at "
        f"{first['action_type']} (risk {first['risk_score']:.0f}).",
        f"The highest-risk attempt was {worst['action_type']} against '{worst['resource']}' at risk "
        f"{worst['risk_score']:.0f}/100 with a behavioural anomaly score of {worst['anomaly_score']:.2f}.",
    ]
    pats = worst.get("risk_factors", {}).get("sequence", {}).get("patterns", [])
    if pats:
        lines.append("Sequence evidence: " + "; ".join(f"{p['name']} ({p['progress']}/{p['total']})" for p in pats) + ".")
    violations = sorted({x["policy_violation"] for x in flagged if x.get("policy_violation")})
    if violations:
        lines.append("Primary policy violations: " + ", ".join(violations) + ".")
    lines.append(f"Observed action chain: {chain}.")
    return " ".join(lines)
