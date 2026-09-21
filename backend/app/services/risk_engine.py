"""Multi-layer risk score, 0..100.

Risk is NOT the anomaly score rescaled. It fuses eight independent signals with
weights that live in agent_policy.json:

  behavior_anomaly       ML deviation from learned behaviour
  resource_sensitivity   how sensitive the touched resource is
  permission_risk        privilege level requested
  action_severity        blast radius of the action
  intent_misalignment    1 - alignment with the assigned task
  sequence_risk          kill-chain / escalation / loop evidence
  behavior_context       low trust, behavioural drift, tainted session
  counterfactual_impact  simulated damage if the action were allowed

plus a penalty per policy violation, plus floors for irreversible operations
and completed attack chains. False-positive protection comes from the weights
themselves: intent alignment, low sensitivity and the absence of sequence
signals keep a sanctioned-but-unusual action below the intervention thresholds
(measured in the evaluation, not asserted). An earlier explicit 'dampener' cap
was removed because it never fired on the test data.

Every contribution is returned so the UI can show exactly how the number was
composed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from backend.app.agent.catalog import ActionSpec, permission_value
from backend.app.services.policy_engine import PolicyResult, policy_engine
from backend.app.services.sequence import SequenceFindings


@dataclass
class RiskAssessmentResult:
    risk_score: float
    risk_level: str
    factors: Dict[str, float]
    contributions: Dict[str, float]
    floors: List[str] = field(default_factory=list)


def behavior_context(trust: float, drift_excess: float, tainted: bool) -> float:
    return float(min(100.0, max((100.0 - trust) * 0.6, drift_excess * 100.0 * 0.8, 70.0 if tainted else 0.0)))


def assess(spec: ActionSpec, anomaly: float, alignment: float, seq: SequenceFindings,
           pol: PolicyResult, trust: float, drift_excess: float, tainted: bool,
           cf_impact: float) -> RiskAssessmentResult:
    cfg = policy_engine.policy
    w = cfg["risk_weights"]

    factors = {
        "behavior_anomaly": anomaly * 100.0,
        "resource_sensitivity": spec.resource_sensitivity * 100.0,
        "permission_risk": permission_value(spec.permission_level) * 100.0,
        "action_severity": spec.severity * 100.0,
        "intent_misalignment": (1.0 - max(0.0, min(1.0, alignment))) * 100.0,
        "sequence_risk": seq.sequence_risk,
        "behavior_context": behavior_context(trust, drift_excess, tainted),
        "counterfactual_impact": cf_impact,
    }
    factors = {k: round(v, 1) for k, v in factors.items()}
    contributions = {k: round(factors[k] * w[k], 2) for k in w}
    score = sum(contributions.values())

    penalty = cfg["policy_violation_penalty"]
    vpen = min(len(pol.violations), 3) * (penalty / 3.0)
    contributions["policy_violations"] = round(vpen, 2)
    score += vpen

    floors: List[str] = []
    if spec.destructive and not pol.allowed:
        score = max(score, cfg["destructive_action_floor"])
        floors.append(f"destructive operation outside capability set (floor {cfg['destructive_action_floor']})")
    if seq.pattern_terminate:
        score = max(score, 90.0)
        floors.append(f"attack chain {seq.pattern_terminate} reached its termination stage (floor 90)")
    if seq.escalation.get("detected"):
        score = max(score, 70.0)
        floors.append("privilege-escalation pattern (floor 70)")
    if tainted and alignment < cfg["global"]["min_intent_alignment"]:
        score = max(score, 70.0)
        floors.append("tainted session deviating from task (floor 70)")

    score = float(max(0.0, min(100.0, round(score, 1))))
    return RiskAssessmentResult(score, policy_engine.risk_level(score), factors, contributions, floors)
