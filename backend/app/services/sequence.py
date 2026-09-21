"""Sequence-level misbehaviour detection.

Individual actions can each look tolerable while the SEQUENCE is an attack:

    READ_LOG -> ACCESS_CREDENTIAL_STORE -> MODIFY_PERMISSION -> EXPORT_DATA

Three mechanisms operate over a sliding window of the session's recent
attempted actions (blocked attempts count -- the agent still tried):

  1. KILL-CHAIN PATTERNS   staged patterns declared in agent_policy.json.
                           Stages may be skipped; progress = distinct stages hit.
  2. PRIVILEGE ESCALATION  a dedicated detector over the permission trajectory
                           (ladder, jump, elevation-then-restricted-access).
  3. LOOPS / RETRY STORMS  excessive repeated calls and consecutive failures.

Learned bigram/trigram surprisal (from the agent's fingerprint) is computed
here too; it is also fed to the ML model as features.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.app.agent.catalog import get_spec, permission_value
from backend.app.services.fingerprint import Fingerprint
from backend.app.services.steps import StepRec

WINDOW = 8

_LEVEL_NAME = {0.0: "public", 0.35: "internal", 0.7: "privileged", 1.0: "restricted"}


def _level_name(v: float) -> str:
    return _LEVEL_NAME.get(round(v, 2), f"{v:.2f}")


@dataclass
class SequenceFindings:
    bigram_dev: float = 0.0
    trigram_novel: float = 0.0
    patterns: List[Dict[str, Any]] = field(default_factory=list)
    escalation: Dict[str, Any] = field(default_factory=lambda: {"detected": False})
    loop: Dict[str, Any] = field(default_factory=lambda: {"kind": None})
    sequence_risk: float = 0.0
    pattern_terminate: Optional[str] = None      # id of a pattern that reached its terminate stage
    window_actions: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "bigram_deviation": round(self.bigram_dev, 3),
            "trigram_novel": self.trigram_novel,
            "patterns": self.patterns,
            "privilege_escalation": self.escalation,
            "loop": self.loop,
            "sequence_risk": round(self.sequence_risk, 1),
            "pattern_terminate": self.pattern_terminate,
            "window": self.window_actions,
        }


def _matches(token: str, action: str) -> bool:
    if token.startswith("cat:"):
        return get_spec(action).category == token[4:]
    return token == action


def _stage_hits(pattern: Dict[str, Any], actions: List[str]) -> List[Optional[str]]:
    """For each stage, the first action in the window that satisfies it (in order)."""
    stages = pattern["stages"]
    hits: List[Optional[str]] = [None] * len(stages)
    floor = 0
    for a in actions:
        for k in range(floor, len(stages)):
            if any(_matches(t, a) for t in stages[k]):
                if hits[k] is None:
                    hits[k] = a
                floor = k + 1 if k + 1 < len(stages) else k
                break
    return hits


def match_patterns(cfg: Dict[str, Any], actions: List[str]) -> List[Dict[str, Any]]:
    out = []
    if not actions:
        return out
    newest = actions[-1]
    for p in cfg.get("sequence_patterns", []):
        hits = _stage_hits(p, actions)
        progress = sum(1 for h in hits if h)
        involved = any(_matches(t, newest) for st in p["stages"][1:] for t in st)
        if progress < 2 or not involved:
            continue
        term = p.get("terminate_at", len(p["stages"]))
        frac = min(1.0, (progress - 1) / max(1, term - 1))
        out.append({
            "id": p["id"], "name": p["name"], "description": p.get("description", ""),
            "progress": progress, "total": len(p["stages"]), "terminate_at": term,
            "path": [h for h in hits if h], "risk": round(p.get("weight", 80) * frac, 1),
            "completed": progress >= term,
        })
    return out


def detect_escalation(cfg: Dict[str, Any], hist: List[StepRec], alignment_new: float) -> Dict[str, Any]:
    """Dedicated privilege-escalation detector over the permission trajectory."""
    ec = cfg.get("escalation", {})
    win = hist[-ec.get("window", 6):]
    if len(win) < 2:
        return {"detected": False}
    perms = [s.permission for s in win]
    new = win[-1]
    path = [{"action": s.action, "level": _level_name(s.permission)} for s in win]
    prior_min = min(perms[:-1])

    # elevation request / credential access / permission write earlier in the window
    elev_actions = set(ec.get("elevation_actions", []))
    elevated_before = any(s.action in elev_actions for s in win[:-1])

    ladder = False
    distinct: List[float] = []
    for p in perms:
        if not distinct or p > distinct[-1]:
            distinct.append(p)
    if len(distinct) >= 3 and perms[-1] == max(perms) and new.permission >= 1.0:
        ladder = True

    jump = (new.permission - prior_min) >= ec.get("jump", 0.6) and new.sensitivity >= 0.8 and alignment_new < 0.4
    elev_access = elevated_before and new.permission >= 1.0 and new.sensitivity >= 0.85

    kind = "ladder" if ladder else "elevation_then_restricted_access" if elev_access else "jump" if jump else None
    if not kind:
        return {"detected": False, "path": path}
    return {"detected": True, "kind": kind, "path": path,
            "severity": {"ladder": 0.9, "elevation_then_restricted_access": 0.95, "jump": 0.75}[kind],
            "description": {
                "ladder": "Permission level climbed step by step to restricted within one window.",
                "elevation_then_restricted_access": "Elevation/credential action was followed by restricted-resource access.",
                "jump": "Agent jumped from a low-privilege context straight to a sensitive restricted resource.",
            }[kind]}


def detect_loops(cfg: Dict[str, Any], hist: List[StepRec]) -> Dict[str, Any]:
    """Retry storms, rate abuse, bulk re-reads and progress stagnation.

    STAGNATION = a long run of observe/read-only actions with no productive
    (maintain / report) action: the agent is gathering, not working. It is the
    signal for scraping-style behaviour built only from sanctioned actions.
    """
    lc = cfg.get("loops", {})
    if not hist:
        return {"kind": None}
    last = hist[-1]
    consec = 0
    for s in reversed(hist):
        if s.action == last.action:
            consec += 1
        else:
            break
    fails = 0
    for s in reversed(hist):
        if s.failed:
            fails += 1
        else:
            break
    streak = 0
    for s in reversed(hist):
        if get_spec(s.action).category in ("observe", "data"):
            streak += 1
        else:
            break
    recent = hist[-consec:] if consec else [last]
    fast = (sum(s.dt for s in recent[1:]) / max(1, len(recent) - 1) < lc.get("fast_dt_s", 1.5)) if len(recent) > 1 else False

    kind = None
    severity = 0.0
    if fails >= lc.get("failures_flag", 3):
        kind, severity = "RETRY_STORM", min(1.0, 0.45 + 0.15 * (fails - lc.get("failures_flag", 3)))
    elif consec >= lc.get("repeat_fast_flag", 6) and fast:
        kind, severity = "EXCESSIVE_CALLS", min(1.0, 0.5 + 0.1 * (consec - lc.get("repeat_fast_flag", 6)))
    elif consec >= lc.get("bulk_read_flag", 5) and last.sensitivity >= 0.5 and get_spec(last.action).category == "data":
        kind, severity = "BULK_READ", min(1.0, 0.5 + 0.1 * (consec - lc.get("bulk_read_flag", 5)))
    elif consec >= lc.get("repeat_slow_flag", 9):
        kind, severity = "REPEATED_ACTION", min(1.0, 0.4 + 0.08 * (consec - lc.get("repeat_slow_flag", 9)))
    elif streak >= lc.get("stagnation_flag", 7):
        kind, severity = "STAGNATION", min(1.0, 0.35 + 0.1 * (streak - lc.get("stagnation_flag", 7)))
    return {"kind": kind, "consecutive_same": consec, "consecutive_failures": fails,
            "observe_streak": streak, "severity": round(severity, 2), "fast": bool(fast)}


def window_stats(win: List[StepRec]) -> Dict[str, float]:
    """Window-level features for the ML detector (all in 0..1)."""
    last5 = win[-5:]
    n = len(last5)
    perms = [s.permission for s in win]
    rise = max(0.0, perms[-1] - min(perms[:-1])) if len(perms) > 1 else 0.0
    counts: Dict[str, int] = {}
    for s in win[-8:]:
        counts[s.action] = counts.get(s.action, 0) + 1
    rep = max(counts.values()) / max(1, len(win[-8:]))
    mean_dt = sum(s.dt for s in last5) / n
    return {
        "window_max_sensitivity": max(s.sensitivity for s in last5),
        "window_perm_rise": min(1.0, rise),
        "window_sensitive_count": min(1.0, sum(1 for s in last5 if s.sensitivity >= 0.8) / 3.0),
        "recent_failure_ratio": sum(1 for s in last5 if s.failed) / n,
        "window_misalignment": sum(1.0 - s.alignment for s in last5) / n,
        "repeat_ratio": rep if len(win) >= 3 else 0.0,
        "burstiness": max(0.0, min(1.0, 1.0 - mean_dt / 10.0)),
    }


def analyze_sequence(cfg: Dict[str, Any], fp: Fingerprint, hist: List[StepRec],
                     prev: Optional[str], prev2: Optional[str]) -> SequenceFindings:
    """`hist` includes the NEW step as its last element."""
    new = hist[-1]
    win = hist[-WINDOW:]
    actions = [s.action for s in win]
    f = SequenceFindings(window_actions=actions)
    f.bigram_dev = fp.seq_deviation(prev, new.action)
    f.trigram_novel = fp.trigram_novel(prev2, prev, new.action)
    f.patterns = match_patterns(cfg, actions)
    f.escalation = detect_escalation(cfg, win, new.alignment)
    f.loop = detect_loops(cfg, hist)

    risks = [p["risk"] for p in f.patterns]
    if f.escalation.get("detected"):
        risks.append(f.escalation["severity"] * 88.0)
    if f.loop.get("kind"):
        risks.append(f.loop["severity"] * 75.0)
    f.sequence_risk = float(max(risks)) if risks else 0.0
    done = [p for p in f.patterns if p["completed"]]
    f.pattern_terminate = done[0]["id"] if done else None
    return f
