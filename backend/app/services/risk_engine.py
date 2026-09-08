"""Risk scoring: 0-100, fusing the ML signal with contextual and policy signals.

Risk is deliberately NOT equal to the anomaly score. A statistically unusual
but harmless action (e.g. an unexpected log read) should score low; a
statistically ordinary but destructive action should score high.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from backend.app.agent.catalog import PERMISSION_LEVELS, get_spec
from backend.app.services.policy_engine import PolicyResult, policy_engine


@dataclass
class RiskAssessmentResult:
    risk_score: float
    risk_level: str
    factors: Dict[str, float]
    contributions: Dict[str, float]


def assess(action_type: str, anomaly_score: float, permission_level: str,
           task_relevance: float, policy: PolicyResult) -> RiskAssessmentResult:
    spec = get_spec(action_type)
    weights = policy_engine.policy["risk_weights"]

    # Each factor is expressed on the same 0-100 scale so the dashboard can
    # show them side by side.
    factors = {
        "behavior_anomaly": round(anomaly_score * 100, 1),
        "resource_sensitivity": round(spec.resource_sensitivity * 100, 1),
        "permission_risk": round(PERMISSION_LEVELS.get(permission_level, 0.5) * 100, 1),
        "action_severity": round(spec.severity * 100, 1),
        "task_relevance_gap": round((1.0 - max(0.0, min(1.0, task_relevance))) * 100, 1),
    }

    contributions = {k: round(factors[k] * weights[k], 2) for k in weights}
    score = sum(contributions.values())

    # Policy violations add a penalty on top of the weighted behavioural score.
    penalty = policy_engine.policy["policy_violation_penalty"]
    violation_penalty = min(len(policy.violations), 3) * (penalty / 3.0)
    score += violation_penalty
    contributions["policy_violations"] = round(violation_penalty, 2)

    # A destructive, denied operation can never be scored as merely "high".
    if policy.hard_block and spec.destructive:
        score = max(score, policy_engine.policy["destructive_action_floor"])

    score = float(max(0.0, min(100.0, round(score, 1))))
    return RiskAssessmentResult(
        risk_score=score,
        risk_level=policy_engine.risk_level(score),
        factors=factors,
        contributions=contributions,
    )
