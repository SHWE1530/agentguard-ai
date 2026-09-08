"""Deterministic guardrails.

The ML model reports how *unusual* an action is. The policy engine reports
whether it is *permitted*. Neither is sufficient on its own: an attacker can
make malicious behaviour look statistically ordinary, and legitimate work can
look statistically odd. Both signals feed the risk engine.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List

from backend.app.agent.catalog import PERMISSION_LEVELS, get_spec
from backend.app.config import POLICY_PATH


@dataclass
class PolicyResult:
    violations: List[str] = field(default_factory=list)
    requires_approval: bool = False
    hard_block: bool = False
    details: Dict[str, str] = field(default_factory=dict)

    @property
    def primary_violation(self) -> str | None:
        return self.violations[0] if self.violations else None


class PolicyEngine:
    def __init__(self, path: str = POLICY_PATH) -> None:
        self.path = path
        self.policy: Dict = {}
        self.reload()

    def reload(self) -> Dict:
        with open(self.path, encoding="utf-8") as fh:
            self.policy = json.load(fh)
        return self.policy

    # ---------------------------------------------------------------- checks
    def evaluate(self, action_type: str, resource: str, permission_level: str,
                 task_relevance: float) -> PolicyResult:
        p = self.policy
        res = PolicyResult()
        spec = get_spec(action_type)

        # 1. Is the action in the agent's sanctioned capability set?
        if action_type not in p["allowed_actions"]:
            res.violations.append("ACTION_NOT_IN_CAPABILITY_SET")
            res.details["ACTION_NOT_IN_CAPABILITY_SET"] = (
                f"{action_type} is not a sanctioned capability for this agent."
            )

        # 2. Explicit deny-list -- never executes, regardless of ML score.
        if action_type in p["always_block"]:
            res.hard_block = True
            res.violations.append("EXPLICITLY_DENIED_ACTION")
            res.details["EXPLICITLY_DENIED_ACTION"] = (
                f"{action_type} is on the agent's permanent deny-list."
            )

        # 3. Is the resource inside the declared task scope?
        prefixes = p["task_scope"]["allowed_resource_prefixes"]
        if not any(resource.startswith(pref) for pref in prefixes):
            res.violations.append("RESOURCE_OUTSIDE_TASK_SCOPE")
            res.details["RESOURCE_OUTSIDE_TASK_SCOPE"] = (
                f"Resource '{resource}' is outside the declared task scope "
                f"({', '.join(prefixes)})."
            )

        # 4. Relevance to the assigned task.
        min_rel = p["task_scope"]["min_task_relevance"]
        if task_relevance < min_rel:
            res.violations.append("LOW_TASK_RELEVANCE")
            res.details["LOW_TASK_RELEVANCE"] = (
                f"Task relevance {task_relevance:.2f} is below the required {min_rel:.2f}."
            )

        # 5. Privilege ceiling.
        ceiling = PERMISSION_LEVELS[p["max_permission_level"]]
        if PERMISSION_LEVELS.get(permission_level, 0.0) > ceiling:
            res.violations.append("PERMISSION_CEILING_EXCEEDED")
            res.details["PERMISSION_CEILING_EXCEEDED"] = (
                f"Action requests '{permission_level}' privilege; the agent is capped "
                f"at '{p['max_permission_level']}'."
            )

        # 6. Destructive operations.
        if spec.destructive:
            res.violations.append("DESTRUCTIVE_OPERATION")
            res.details["DESTRUCTIVE_OPERATION"] = (
                f"{action_type} is irreversible against '{resource}' in the simulated environment."
            )

        # 7. Human-in-the-loop requirement.
        if action_type in p["require_human_approval"]:
            res.requires_approval = True

        return res

    # ------------------------------------------------------------- decisions
    def risk_level(self, risk_score: float) -> str:
        th = self.policy["thresholds"]["risk_levels"]
        if risk_score >= th["critical"]:
            return "CRITICAL"
        if risk_score >= th["high"]:
            return "HIGH"
        if risk_score >= th["medium"]:
            return "MEDIUM"
        return "LOW"

    def decide(self, risk_level: str, policy: PolicyResult,
               destructive: bool = False) -> str:
        """Map risk level + policy result onto an enforcement decision.

        Blocking a single action and halting the entire agent are deliberately
        different responses. A denied-but-reversible action (e.g. a privilege
        change) is blocked while the agent keeps running under suspicion, so
        the safety layer can observe where the behaviour goes next. Only a
        CRITICAL *irreversible* operation stops the agent outright.
        """
        if policy.hard_block:
            decision = "BLOCK_AND_STOP" if risk_level == "CRITICAL" else "BLOCK"
        elif policy.requires_approval:
            return "REQUIRE_APPROVAL"
        else:
            decision = self.policy["level_actions"][risk_level]

        # Halting the agent is reserved for irreversible attempts, however the
        # decision was reached. A reversible action is blocked on its own.
        if decision == "BLOCK_AND_STOP" and not destructive:
            return "BLOCK"
        return decision


policy_engine = PolicyEngine()
