"""Configurable, rule-based policy engine.

The ML model reports how *unusual* an action is. The policy engine reports
whether it is *permitted*, and what to do about it. Neither is sufficient
alone: unusual != dangerous, and dangerous can look ordinary.

Two phases per action:

  evaluate()  ->  invariant checks (capability set, deny-list, task scope,
                  intent, privilege ceiling, destructiveness, taint). These
                  produce named VIOLATIONS that feed the risk score.
  decide()    ->  the ordered rules in agent_policy.json are matched against
                  the action's "facts" (identity, task, tool, resource,
                  permission, severity, risk, trust, drift, sequence...).
                  The most severe matching effect wins:

                  ALLOW < MONITOR < REQUIRE_APPROVAL < BLOCK < TERMINATE

Every matched rule id is returned, so a decision is always attributable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.app.agent.catalog import ActionSpec, PERMISSION_LEVELS
from backend.app.config import POLICY_PATH
from backend.app.services.intent import TaskProfile

EFFECT_ORDER = ["ALLOW", "MONITOR", "REQUIRE_APPROVAL", "BLOCK", "TERMINATE"]


@dataclass
class PolicyResult:
    violations: List[str] = field(default_factory=list)
    details: Dict[str, str] = field(default_factory=dict)
    allowed: bool = True
    always_block: bool = False
    needs_approval: bool = False

    @property
    def primary_violation(self) -> Optional[str]:
        return self.violations[0] if self.violations else None

    def add(self, code: str, detail: str) -> None:
        if code not in self.violations:
            self.violations.append(code)
        self.details[code] = detail


class PolicyEngine:
    def __init__(self, path: str = POLICY_PATH) -> None:
        self.path = path
        self.policy: Dict[str, Any] = {}
        self.reload()

    def reload(self) -> Dict[str, Any]:
        with open(self.path, encoding="utf-8") as fh:
            self.policy = json.load(fh)
        return self.policy

    # ------------------------------------------------------------- lookups
    def agent_cfg(self, agent: str) -> Dict[str, Any]:
        return self.policy["agents"].get(agent) or {
            "allowed_actions": [], "max_permission_level": "internal", "require_human_approval": []}

    def allowed_actions(self, agent: str) -> List[str]:
        return list(self.agent_cfg(agent)["allowed_actions"])

    # ----------------------------------------------------------- invariants
    def evaluate(self, agent: str, task: TaskProfile, spec: ActionSpec, alignment: float,
                 tainted: bool, seq: Optional[Dict[str, Any]] = None) -> PolicyResult:
        acfg = self.agent_cfg(agent)
        g = self.policy["global"]
        res = PolicyResult()
        action = spec.action_type

        if action not in acfg["allowed_actions"]:
            res.allowed = False
            res.add("ACTION_NOT_IN_CAPABILITY_SET", f"{action} is not a sanctioned capability for {agent}.")
        if action in g["always_block"]:
            res.always_block = True
            res.add("EXPLICITLY_DENIED_ACTION", f"{action} is on the permanent deny-list.")
        if not task.in_scope(spec.resource):
            res.add("RESOURCE_OUTSIDE_TASK_SCOPE",
                    f"Resource '{spec.resource}' is outside the scope of task '{task.task_type}' "
                    f"({', '.join(task.scope_prefixes)}).")
        if alignment < g["min_intent_alignment"]:
            res.add("LOW_INTENT_ALIGNMENT",
                    f"Intent alignment {alignment:.2f} is below the required {g['min_intent_alignment']:.2f} "
                    f"for task '{task.task_type}'.")
        ceiling = PERMISSION_LEVELS[acfg["max_permission_level"]]
        if PERMISSION_LEVELS.get(spec.permission_level, 0.0) > ceiling:
            res.add("PERMISSION_CEILING_EXCEEDED",
                    f"Action needs '{spec.permission_level}' privilege; {agent} is capped at "
                    f"'{acfg['max_permission_level']}'.")
        if spec.destructive and not res.allowed:
            res.add("DESTRUCTIVE_OPERATION",
                    f"{action} is destructive and irreversible against '{spec.resource}' in the simulated environment.")
        if action in acfg["require_human_approval"]:
            res.needs_approval = True
        if tainted and alignment < g["min_intent_alignment"]:
            res.add("TAINTED_SESSION_DEVIATION",
                    "The session ingested untrusted content with injection indicators and this action departs from the task.")
        if seq:
            done = [p for p in seq.get("patterns", []) if p["completed"]]
            for p in done:
                res.add("SEQUENCE_KILL_CHAIN", f"{p['name']} reached stage {p['progress']}/{p['total']}: "
                        + " -> ".join(p["path"]))
            if seq.get("privilege_escalation", {}).get("detected"):
                pe = seq["privilege_escalation"]
                res.add("PRIVILEGE_ESCALATION_PATTERN", pe["description"])
            lp = seq.get("loop", {})
            if lp.get("kind"):
                res.add(lp["kind"], f"{lp['kind'].replace('_', ' ').title()}: "
                        f"{lp['consecutive_same']} identical calls, {lp['consecutive_failures']} consecutive failures.")
        return res

    # ------------------------------------------------------------ risk level
    def risk_level(self, score: float) -> str:
        th = self.policy["thresholds"]["risk_levels"]
        if score >= th["critical"]:
            return "CRITICAL"
        if score >= th["high"]:
            return "HIGH"
        if score >= th["medium"]:
            return "MEDIUM"
        return "LOW"

    # ----------------------------------------------------------------- rules
    @staticmethod
    def _matches(when: Dict[str, Any], f: Dict[str, Any], provisional: str) -> bool:
        for key, want in when.items():
            if key == "provisional_effect_gte":
                if EFFECT_ORDER.index(provisional) < EFFECT_ORDER.index(want):
                    return False
            elif key.endswith("_gte"):
                if not (f.get(key[:-4], 0) is not None and f.get(key[:-4], 0) >= want):
                    return False
            elif key.endswith("_lt"):
                if not (f.get(key[:-3], 0) is not None and f.get(key[:-3], 0) < want):
                    return False
            elif key == "resource_prefix":
                if not str(f.get("resource", "")).startswith(want):
                    return False
            elif key == "pattern_terminate":
                if bool(f.get("pattern_terminate")) != bool(want):
                    return False
            elif key == "loop_kind":
                lk = f.get("loop_kind")
                if lk not in (want if isinstance(want, list) else [want]):
                    return False
            elif isinstance(want, list):
                if f.get(key) not in want:
                    return False
            else:
                if f.get(key) != want:
                    return False
        return True

    def decide(self, facts: Dict[str, Any]) -> Tuple[str, List[Dict[str, str]]]:
        """Return (decision, matched rules). Two passes so a rule can key on the provisional effect."""
        rules = self.policy["rules"]
        matched: List[Dict[str, str]] = []
        best = "ALLOW"

        def run(provisional: str, only_provisional: bool) -> None:
            nonlocal best
            for r in rules:
                uses_prov = "provisional_effect_gte" in r["when"]
                if uses_prov != only_provisional:
                    continue
                if self._matches(r["when"], facts, provisional):
                    if not any(m["id"] == r["id"] for m in matched):
                        matched.append({"id": r["id"], "effect": r["effect"], "reason": r["reason"]})
                    if EFFECT_ORDER.index(r["effect"]) > EFFECT_ORDER.index(best):
                        best = r["effect"]

        run("ALLOW", only_provisional=False)
        run(best, only_provisional=True)
        # the default rule is only informative when nothing else matched
        if len(matched) > 1:
            matched = [m for m in matched if m["id"] != "R99-DEFAULT-ALLOW"]
        matched.sort(key=lambda m: -EFFECT_ORDER.index(m["effect"]))
        return best, matched

    def alternative(self, action: str) -> Optional[Dict[str, str]]:
        return self.policy.get("safe_alternatives", {}).get(action)


policy_engine = PolicyEngine()
