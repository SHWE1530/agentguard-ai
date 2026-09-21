"""Per-agent behavioural fingerprint.

A fingerprint is a compact statistical profile of how one agent normally
behaves, LEARNED from verified-safe sessions:

  * action frequencies            * tool usage
  * bigram transition counts      * trigram (sequence) counts
  * resource-prefix usage         * permission-level mean
  * inter-action timing (log-normal summary)

It powers three things:
  1. sequence surprisal (how unlikely is  prev -> action  for THIS agent),
  2. novelty flags (tool / resource this agent has never used),
  3. DRIFT: how far a recent window of behaviour has moved from the profile.

The fingerprint is versioned. Adaptive updates (see baseline.py) create a new
version only from sessions that pass safeguards against baseline poisoning.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, Iterable, List, Optional

import numpy as np

from backend.app.agent.catalog import VOCAB_SIZE
from backend.app.services.steps import StepRec

START = "<START>"
ALPHA = 0.3                     # additive smoothing for transition probabilities
DRIFT_WEIGHTS = {"action_mix": 0.35, "novel_transitions": 0.25, "novel_resources": 0.15,
                 "permission_shift": 0.10, "timing_shift": 0.15}


def _js(p: Dict[str, float], q: Dict[str, float]) -> float:
    """Jensen-Shannon divergence, base 2, in [0, 1]."""
    keys = set(p) | set(q)
    ps = sum(p.values()) or 1.0
    qs = sum(q.values()) or 1.0
    d = 0.0
    for k in keys:
        a = p.get(k, 0.0) / ps
        b = q.get(k, 0.0) / qs
        m = 0.5 * (a + b)
        if a > 0:
            d += 0.5 * a * math.log2(a / m)
        if b > 0:
            d += 0.5 * b * math.log2(b / m)
    return float(max(0.0, min(1.0, d)))


class Fingerprint:
    def __init__(self, agent: str, version: int = 1, source: str = "bootstrap") -> None:
        self.agent = agent
        self.version = version
        self.source = source
        self.n_sessions = 0.0
        self.n_actions = 0.0
        self.action: Dict[str, float] = defaultdict(float)
        self.trans: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.tri: Dict[str, float] = defaultdict(float)
        self.tool: Dict[str, float] = defaultdict(float)
        self.prefix: Dict[str, float] = defaultdict(float)
        self.perm_sum = 0.0
        self.logdt_sum = 0.0
        self.ref_drift: Dict[str, float] = {"mean": 0.2, "p95": 0.4}

    # -------------------------------------------------------------- learning
    def observe_session(self, steps: Iterable[StepRec], weight: float = 1.0) -> None:
        steps = list(steps)
        if not steps:
            return
        self.n_sessions += weight
        prev2 = prev1 = None
        for s in steps:
            self.n_actions += weight
            self.action[s.action] += weight
            self.trans[prev1 or START][s.action] += weight
            if prev2 and prev1:
                self.tri[f"{prev2}|{prev1}|{s.action}"] += weight
            self.tool[s.tool] += weight
            self.prefix[s.prefix] += weight
            self.perm_sum += weight * s.permission
            self.logdt_sum += weight * math.log(s.dt + 0.1)
            prev2, prev1 = prev1, s.action

    def updated(self, sessions: List[List[StepRec]], decay: float = 0.9, source: str = "adaptive") -> "Fingerprint":
        """New version = decayed old counts + newly verified sessions."""
        nf = Fingerprint(self.agent, self.version + 1, source)
        nf.ref_drift = dict(self.ref_drift)

        def scale(d: Dict[str, float]) -> Dict[str, float]:
            return {k: v * decay for k, v in d.items()}

        nf.n_sessions = self.n_sessions * decay
        nf.n_actions = self.n_actions * decay
        nf.action.update(scale(self.action))
        for k, row in self.trans.items():
            nf.trans[k].update(scale(row))
        nf.tri.update(scale(self.tri))
        nf.tool.update(scale(self.tool))
        nf.prefix.update(scale(self.prefix))
        nf.perm_sum = self.perm_sum * decay
        nf.logdt_sum = self.logdt_sum * decay
        for s in sessions:
            nf.observe_session(s)
        return nf

    def rescaled(self, target_actions: float) -> "Fingerprint":
        """Cap the effective sample size so new verified sessions carry real weight.

        A fingerprint learned from thousands of synthetic actions would otherwise
        be immovable (one session = 0.05%), which makes "adaptive" meaningless.
        Probabilities are unchanged; only the confidence is reduced.
        """
        if self.n_actions <= target_actions:
            return self
        f = target_actions / self.n_actions
        nf = Fingerprint(self.agent, self.version, self.source)
        nf.ref_drift = dict(self.ref_drift)
        nf.n_sessions, nf.n_actions = self.n_sessions * f, target_actions
        nf.action.update({k: v * f for k, v in self.action.items()})
        for k, row in self.trans.items():
            nf.trans[k].update({a: v * f for a, v in row.items()})
        nf.tri.update({k: v * f for k, v in self.tri.items()})
        nf.tool.update({k: v * f for k, v in self.tool.items()})
        nf.prefix.update({k: v * f for k, v in self.prefix.items()})
        nf.perm_sum, nf.logdt_sum = self.perm_sum * f, self.logdt_sum * f
        return nf

    # ------------------------------------------------------------- queries
    def bigram_p(self, prev: Optional[str], action: str) -> float:
        row = self.trans.get(prev or START, {})
        total = sum(row.values())
        return (row.get(action, 0.0) + ALPHA) / (total + ALPHA * VOCAB_SIZE)

    def seq_deviation(self, prev: Optional[str], action: str) -> float:
        """0 = ordinary follow-up for this agent, 1 = never-seen transition."""
        p = self.bigram_p(prev, action)
        s = -math.log(p)
        s0, smax = -math.log(0.5), -math.log(0.004)
        return float(max(0.0, min(1.0, (s - s0) / (smax - s0))))

    def trigram_novel(self, a: Optional[str], b: Optional[str], c: str) -> float:
        if not a or not b:
            return 0.0
        return 0.0 if self.tri.get(f"{a}|{b}|{c}", 0.0) >= 0.5 else 1.0

    def tool_rarity(self, tool: str) -> float:
        tot = sum(self.tool.values()) or 1.0
        freq = self.tool.get(tool, 0.0) / tot
        return float(1.0 - min(1.0, freq / 0.15))

    def prefix_freq(self, prefix: str) -> float:
        tot = sum(self.prefix.values()) or 1.0
        return self.prefix.get(prefix, 0.0) / tot

    def novel_resource(self, prefix: str) -> float:
        return 1.0 if self.prefix_freq(prefix) < 0.01 else 0.0

    @property
    def mean_perm(self) -> float:
        return self.perm_sum / max(1e-9, self.n_actions)

    @property
    def mean_logdt(self) -> float:
        return self.logdt_sum / max(1e-9, self.n_actions)

    # --------------------------------------------------------------- drift
    def drift(self, window: List[StepRec]) -> Dict[str, float]:
        """Compare a recent window of behaviour to the learned fingerprint."""
        if len(window) < 3:
            return {"score": 0.0, "insufficient": 1.0, **{k: 0.0 for k in DRIFT_WEIGHTS}}
        win: Dict[str, float] = defaultdict(float)
        for s in window:
            win[s.action] += 1.0
        action_mix = _js(win, self.action)

        novel_t = 0.0
        prev = None
        for s in window:
            if self.trans.get(prev or START, {}).get(s.action, 0.0) < 0.5:
                novel_t += 1.0
            prev = s.action
        novel_transitions = novel_t / len(window)

        novel_resources = sum(1.0 for s in window if self.prefix_freq(s.prefix) < 0.01) / len(window)
        perm = abs(float(np.mean([s.permission for s in window])) - self.mean_perm)
        permission_shift = min(1.0, perm / 0.5)
        ld = float(np.mean([math.log(s.dt + 0.1) for s in window]))
        timing_shift = min(1.0, abs(ld - self.mean_logdt) / 1.5)

        comps = {"action_mix": action_mix, "novel_transitions": novel_transitions,
                 "novel_resources": novel_resources, "permission_shift": permission_shift,
                 "timing_shift": timing_shift}
        score = sum(DRIFT_WEIGHTS[k] * v for k, v in comps.items())
        return {"score": float(min(1.0, score)), "insufficient": 0.0, **comps}

    @property
    def drift_threshold(self) -> float:
        return float(max(0.30, self.ref_drift.get("p95", 0.4) + 0.08))

    def calibrate_reference(self, sessions: List[List[StepRec]], window: int = 8) -> None:
        """Measure what drift looks like for genuinely normal sessions."""
        vals: List[float] = []
        for st in sessions:
            for i in range(3, len(st) + 1):
                vals.append(self.drift(st[max(0, i - window): i])["score"])
        if vals:
            self.ref_drift = {"mean": float(np.mean(vals)), "p95": float(np.percentile(vals, 95))}

    # ----------------------------------------------------------- divergence
    def divergence(self, other: "Fingerprint") -> float:
        """Distance between two fingerprints (actions + transitions), 0..1."""
        d_action = _js(self.action, other.action)
        keys = set(self.trans) | set(other.trans)
        d_trans = 0.0
        w_tot = 0.0
        for k in keys:
            w = sum(self.trans.get(k, {}).values()) + sum(other.trans.get(k, {}).values())
            d_trans += w * _js(self.trans.get(k, {}), other.trans.get(k, {}))
            w_tot += w
        d_trans = d_trans / w_tot if w_tot else 0.0
        return float(0.5 * d_action + 0.5 * d_trans)

    # ----------------------------------------------------------- persistence
    def to_dict(self) -> dict:
        return {"agent": self.agent, "version": self.version, "source": self.source,
                "n_sessions": self.n_sessions, "n_actions": self.n_actions,
                "action": dict(self.action), "trans": {k: dict(v) for k, v in self.trans.items()},
                "tri": dict(self.tri), "tool": dict(self.tool), "prefix": dict(self.prefix),
                "perm_sum": self.perm_sum, "logdt_sum": self.logdt_sum, "ref_drift": self.ref_drift}

    @classmethod
    def from_dict(cls, d: dict) -> "Fingerprint":
        f = cls(d["agent"], d.get("version", 1), d.get("source", "bootstrap"))
        f.n_sessions, f.n_actions = d["n_sessions"], d["n_actions"]
        f.action.update(d["action"])
        for k, v in d["trans"].items():
            f.trans[k].update(v)
        f.tri.update(d["tri"])
        f.tool.update(d["tool"])
        f.prefix.update(d["prefix"])
        f.perm_sum, f.logdt_sum = d["perm_sum"], d["logdt_sum"]
        f.ref_drift = d.get("ref_drift", f.ref_drift)
        return f

    def summary(self) -> dict:
        tot_a = sum(self.action.values()) or 1.0
        tot_t = sum(self.tool.values()) or 1.0
        top_tr = sorted(((k, a, v) for k, row in self.trans.items() for a, v in row.items()),
                        key=lambda x: -x[2])[:10]
        return {
            "agent": self.agent, "version": self.version, "source": self.source,
            "n_sessions": round(self.n_sessions, 1), "n_actions": round(self.n_actions, 1),
            "top_actions": [{"action": k, "share": round(v / tot_a, 3)}
                            for k, v in sorted(self.action.items(), key=lambda x: -x[1])[:8]],
            "top_tools": [{"tool": k, "share": round(v / tot_t, 3)}
                          for k, v in sorted(self.tool.items(), key=lambda x: -x[1])[:6]],
            "resource_prefixes": [{"prefix": k, "share": round(self.prefix_freq(k), 3)}
                                  for k in sorted(self.prefix, key=lambda x: -self.prefix[x])],
            "top_transitions": [{"from": k, "to": a, "count": round(v, 1)} for k, a, v in top_tr],
            "mean_permission": round(self.mean_perm, 3),
            "typical_interval_s": round(math.exp(self.mean_logdt) - 0.1, 2),
            "reference_drift": {k: round(v, 3) for k, v in self.ref_drift.items()},
            "drift_threshold": round(self.drift_threshold, 3),
        }
