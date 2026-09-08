"""Human-readable explanations built from the actual detected factors.

Nothing here is a canned string per severity: each sentence is emitted only
when the corresponding signal actually fired, so two CRITICAL incidents with
different causes read differently.
"""
from __future__ import annotations

from typing import Dict, List

from backend.app.agent.catalog import get_spec
from backend.app.services.policy_engine import PolicyResult


def explain_action(action_type: str, resource: str, anomaly_score: float,
                   risk_score: float, risk_level: str, decision: str,
                   policy: PolicyResult, factors: Dict[str, float],
                   prev_action: str | None, sequence_deviation: float) -> str:
    spec = get_spec(action_type)
    parts: List[str] = []

    # 1. What was attempted.
    parts.append(f"The agent attempted {action_type} against '{resource}' ({spec.description})")

    # 2. Behavioural evidence from the model.
    if anomaly_score >= 0.75:
        parts.append(
            f"The behavioural model scored this action {anomaly_score:.2f}/1.00, far outside "
            f"the range learned from sanctioned operation")
    elif anomaly_score >= 0.4:
        parts.append(
            f"The behavioural model scored this action {anomaly_score:.2f}/1.00, mildly "
            f"outside the learned normal range")
    else:
        parts.append(
            f"The behavioural model scored this action {anomaly_score:.2f}/1.00, consistent "
            f"with learned normal behaviour")

    # 3. Sequence evidence.
    if sequence_deviation >= 0.9 and prev_action:
        parts.append(
            f"the transition {prev_action} -> {action_type} never occurs in the agent's "
            f"normal action sequence")
    elif sequence_deviation >= 0.5 and prev_action:
        parts.append(f"the transition {prev_action} -> {action_type} is unusual")

    # 4. Policy evidence -- only violations that actually fired.
    for v in policy.violations:
        parts.append(policy.details.get(v, v).rstrip("."))

    # 5. What was done about it.
    if decision == "BLOCK_AND_STOP":
        parts.append(
            "The operation was blocked before execution and the agent was stopped to "
            "prevent further simulated damage")
    elif decision == "BLOCK":
        parts.append("The operation was blocked before it reached the simulated environment")
    elif decision == "REQUIRE_APPROVAL":
        parts.append(
            "Execution is held pending explicit human approval because the action affects "
            "critical simulated infrastructure")
    elif decision == "MONITOR":
        parts.append("The action was allowed but flagged for continued monitoring")
    else:
        parts.append("The action was allowed as routine, sanctioned work")

    body = ". ".join(parts) + "."
    return f"[{risk_level} - risk {risk_score:.0f}/100] {body}"


def explain_incident(actions: List[Dict]) -> str:
    """Narrative for an incident, derived from the sequence that produced it."""
    if not actions:
        return "No actions recorded for this incident."
    flagged = [a for a in actions if a["risk_level"] in ("HIGH", "CRITICAL")]
    if not flagged:
        return "The session completed without a high-risk action."

    first, worst = flagged[0], max(flagged, key=lambda a: a["risk_score"])
    chain = " -> ".join(a["action_type"] for a in actions)
    lines = [
        f"The agent began the session inside its sanctioned scope, then deviated at "
        f"{first['action_type']} (risk {first['risk_score']:.0f}).",
        f"The highest-risk attempt was {worst['action_type']} against "
        f"'{worst['resource']}' at risk {worst['risk_score']:.0f}/100 with a behavioural "
        f"anomaly score of {worst['anomaly_score']:.2f}.",
    ]
    violations = sorted({a["policy_violation"] for a in flagged if a.get("policy_violation")})
    if violations:
        lines.append("Policy violations recorded: " + ", ".join(violations) + ".")
    lines.append(f"Observed action chain: {chain}.")
    return " ".join(lines)
