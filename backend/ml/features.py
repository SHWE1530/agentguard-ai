"""Behavioural feature extraction for the anomaly detector.

Every agent action is turned into a fixed-length numeric vector. The same
function is used by the dataset generator, the training script and the live
backend, so training and inference can never drift apart.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from backend.app.agent.catalog import (
    CATEGORY_INDEX,
    PERMISSION_LEVELS,
    get_spec,
    sequence_deviation,
)

# Names must stay aligned with build_feature_vector()
FEATURE_NAMES: List[str] = [
    "permission_level",       # 0..1 ordinal encoding of the requested privilege
    "resource_sensitivity",   # 0..1 how sensitive the touched resource is
    "action_severity",        # 0..1 blast radius of the action
    "task_relevance",         # 0..1 how well the action serves the assigned task
    "sequence_deviation",     # 0..1 unlikelihood of prev_action -> action
    "repeated_action_count",  # normalised count of identical actions in session
    "time_since_prev",        # normalised seconds since previous action
    "tool_rarity",            # 0..1 how unusual this tool is for the agent
    "step_position",          # normalised position of the action in the session
    "is_destructive",         # 0/1
] + [f"cat_{c}" for c in CATEGORY_INDEX]   # one-hot action category

FEATURE_DIM = len(FEATURE_NAMES)

# Tool frequency profile observed during sanctioned operation.
NORMAL_TOOL_FREQUENCY = {
    "ops.health_probe": 0.22,
    "ops.log_reader": 0.20,
    "ops.service_probe": 0.20,
    "ops.ticketing": 0.15,
    "ops.disk_janitor": 0.12,
    "ops.service_control": 0.06,
    "ops.autoscaler": 0.05,
}


@dataclass
class ActionContext:
    """Everything the feature extractor needs about one attempted action."""
    action_type: str
    prev_action: Optional[str] = None
    repeated_count: int = 0          # identical actions already seen this session
    seconds_since_prev: float = 3.0
    step_index: int = 0              # 0-based position in the session
    task_relevance: Optional[float] = None   # override; defaults to catalog value
    resource: Optional[str] = None
    permission_level: Optional[str] = None


def tool_rarity(tool_name: str) -> float:
    freq = NORMAL_TOOL_FREQUENCY.get(tool_name, 0.0)
    if freq <= 0.0:
        return 1.0
    return float(max(0.0, min(1.0, 1.0 - freq / 0.22)))


def build_feature_vector(ctx: ActionContext) -> List[float]:
    spec = get_spec(ctx.action_type)
    perm = ctx.permission_level or spec.permission_level
    relevance = spec.base_relevance if ctx.task_relevance is None else ctx.task_relevance

    vec = [
        PERMISSION_LEVELS.get(perm, 0.5),
        spec.resource_sensitivity,
        spec.severity,
        float(max(0.0, min(1.0, relevance))),
        sequence_deviation(ctx.prev_action, ctx.action_type),
        float(min(1.0, ctx.repeated_count / 5.0)),
        float(min(1.0, ctx.seconds_since_prev / 30.0)),
        tool_rarity(spec.tool_name),
        float(min(1.0, ctx.step_index / 12.0)),
        1.0 if spec.destructive else 0.0,
    ]
    onehot = [0.0] * len(CATEGORY_INDEX)
    onehot[CATEGORY_INDEX[spec.category]] = 1.0
    vec.extend(onehot)
    assert len(vec) == FEATURE_DIM
    return vec
