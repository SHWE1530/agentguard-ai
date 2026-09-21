"""Behavioural feature extraction for the anomaly detector (v2).

One fixed-length vector per attempted action. The SAME function is used by the
dataset pipeline, the trainer, the evaluator and the live backend, so training
and inference cannot drift apart.

v2 adds what v1 lacked: sequence context (learned bigram/trigram surprisal from
the agent's OWN fingerprint, not a hand-written table), window statistics,
intent alignment, and agent-specific novelty. Everything is scaled to 0..1.
"""
from __future__ import annotations

from typing import Dict, List

from backend.app.agent.catalog import CATEGORIES, CATEGORY_INDEX, ActionSpec, permission_value
from backend.app.services.fingerprint import Fingerprint
from backend.app.services.sequence import window_stats
from backend.app.services.steps import StepRec

FEATURE_NAMES: List[str] = [
    "permission_level", "resource_sensitivity", "action_severity", "intent_alignment",
    "seq_bigram_deviation", "seq_trigram_novel", "repeat_ratio", "time_since_prev",
    "burstiness", "tool_rarity", "novel_resource", "step_position", "is_destructive",
    "window_max_sensitivity", "window_perm_rise", "window_sensitive_count",
    "recent_failure_ratio", "window_misalignment",
] + [f"cat_{c}" for c in CATEGORIES]

FEATURE_DIM = len(FEATURE_NAMES)


def build_feature_vector(spec: ActionSpec, hist: List[StepRec], fp: Fingerprint) -> List[float]:
    """`hist` includes the NEW step as its last element."""
    new = hist[-1]
    prev = hist[-2].action if len(hist) > 1 else None
    prev2 = hist[-3].action if len(hist) > 2 else None
    w = window_stats(hist)
    vec: List[float] = [
        permission_value(spec.permission_level),
        spec.resource_sensitivity,
        spec.severity,
        new.alignment,
        fp.seq_deviation(prev, spec.action_type),
        fp.trigram_novel(prev2, prev, spec.action_type),
        w["repeat_ratio"],
        min(1.0, new.dt / 30.0),
        w["burstiness"],
        fp.tool_rarity(spec.tool_name),
        fp.novel_resource(new.prefix),
        min(1.0, (len(hist) - 1) / 12.0),
        1.0 if spec.destructive else 0.0,
        w["window_max_sensitivity"],
        w["window_perm_rise"],
        w["window_sensitive_count"],
        w["recent_failure_ratio"],
        w["window_misalignment"],
    ]
    onehot = [0.0] * len(CATEGORIES)
    onehot[CATEGORY_INDEX[spec.category]] = 1.0
    vec.extend(onehot)
    assert len(vec) == FEATURE_DIM
    return vec


def as_named(vec: List[float]) -> Dict[str, float]:
    return dict(zip(FEATURE_NAMES, vec))
