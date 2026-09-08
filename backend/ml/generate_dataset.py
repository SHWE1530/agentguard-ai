"""Generate a SYNTHETIC agent-behaviour dataset.

This dataset is entirely artificial. It is produced by sampling from a
hand-written behavioural model of the OpsAssist agent and is used only to
train and evaluate the prototype's anomaly detector. It is NOT real-world
telemetry and must not be presented as such.

Usage:
    python -m backend.ml.generate_dataset
"""
from __future__ import annotations

import argparse
import os
import random
from typing import Dict, List

import pandas as pd

from backend.app.agent.catalog import (
    ALLOWED_ACTIONS,
    NORMAL_TRANSITIONS,
    RESTRICTED_ACTIONS,
    get_spec,
)
from backend.ml.features import FEATURE_NAMES, ActionContext, build_feature_vector

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _weighted_choice(row: Dict[str, float], rng: random.Random) -> str:
    keys = list(row)
    weights = [row[k] for k in keys]
    return rng.choices(keys, weights=weights, k=1)[0]


def _emit(rows: List[dict], ctx: ActionContext, label: int, session: str) -> None:
    vec = build_feature_vector(ctx)
    rec = dict(zip(FEATURE_NAMES, vec))
    rec["label"] = label                       # 0 = normal, 1 = misbehaviour
    rec["action_type"] = ctx.action_type
    rec["session_id"] = session
    rows.append(rec)


def normal_session(rows: List[dict], sid: str, rng: random.Random) -> None:
    """A sanctioned maintenance session."""
    length = rng.randint(4, 10)
    prev = None
    counts: Dict[str, int] = {}
    for step in range(length):
        row = NORMAL_TRANSITIONS.get(prev or "<START>")
        action = _weighted_choice(row, rng) if row else rng.choice(ALLOWED_ACTIONS)
        spec = get_spec(action)
        ctx = ActionContext(
            action_type=action,
            prev_action=prev,
            repeated_count=counts.get(action, 0),
            seconds_since_prev=rng.uniform(1.0, 12.0),
            step_index=step,
            # normal agents stay on task; small honest jitter
            task_relevance=min(1.0, max(0.0, spec.base_relevance + rng.gauss(0, 0.05))),
        )
        _emit(rows, ctx, 0, sid)
        counts[action] = counts.get(action, 0) + 1
        prev = action


def drift_session(rows: List[dict], sid: str, rng: random.Random) -> None:
    """Starts sanctioned, then drifts to out-of-scope reconnaissance."""
    prev = None
    counts: Dict[str, int] = {}
    step = 0
    for _ in range(rng.randint(2, 4)):
        row = NORMAL_TRANSITIONS.get(prev or "<START>")
        action = _weighted_choice(row, rng) if row else rng.choice(ALLOWED_ACTIONS)
        spec = get_spec(action)
        ctx = ActionContext(action, prev, counts.get(action, 0),
                            rng.uniform(1.0, 10.0), step,
                            min(1.0, max(0.0, spec.base_relevance + rng.gauss(0, 0.05))))
        _emit(rows, ctx, 0, sid)
        counts[action] = counts.get(action, 0) + 1
        prev, step = action, step + 1

    for _ in range(rng.randint(2, 5)):
        action = rng.choice(RESTRICTED_ACTIONS)
        spec = get_spec(action)
        ctx = ActionContext(action, prev, counts.get(action, 0),
                            rng.uniform(0.2, 4.0), step,
                            max(0.0, spec.base_relevance + rng.gauss(0, 0.02)))
        _emit(rows, ctx, 1, sid)
        counts[action] = counts.get(action, 0) + 1
        prev, step = action, step + 1


def loop_session(rows: List[dict], sid: str, rng: random.Random) -> None:
    """A stuck agent hammering the same action -- abnormal but not restricted."""
    action = rng.choice(ALLOWED_ACTIONS)
    spec = get_spec(action)
    prev = None
    for step in range(rng.randint(7, 14)):
        ctx = ActionContext(action, prev, step, rng.uniform(0.05, 0.6), step,
                            max(0.0, spec.base_relevance - 0.04 * step))
        _emit(rows, ctx, 1, sid)
        prev = action


def escalation_session(rows: List[dict], sid: str, rng: random.Random) -> None:
    """Privilege escalation followed by exfiltration / destruction."""
    chain = ["CHECK_SERVER_HEALTH", "MODIFY_PERMISSION", "DISABLE_SECURITY",
             "EXPORT_DATA", "DELETE_DATABASE"]
    prev = None
    for step, action in enumerate(chain):
        spec = get_spec(action)
        ctx = ActionContext(action, prev, 0, rng.uniform(0.3, 3.0), step,
                            max(0.0, spec.base_relevance + rng.gauss(0, 0.02)))
        _emit(rows, ctx, 0 if spec.allowed else 1, sid)
        prev = action


def generate(n_sessions: int = 1200, seed: int = 42) -> pd.DataFrame:
    rng = random.Random(seed)
    rows: List[dict] = []
    for i in range(n_sessions):
        sid = f"synthetic-{i:05d}"
        r = rng.random()
        if r < 0.72:
            normal_session(rows, sid, rng)
        elif r < 0.85:
            drift_session(rows, sid, rng)
        elif r < 0.93:
            loop_session(rows, sid, rng)
        else:
            escalation_session(rows, sid, rng)
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic agent behaviour data.")
    ap.add_argument("--sessions", type=int, default=1200)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    df = generate(args.sessions, args.seed)
    out = os.path.join(DATA_DIR, "agent_behavior_synthetic.csv")
    df.to_csv(out, index=False)
    print(f"[dataset] SYNTHETIC data written to {out}")
    print(f"[dataset] {len(df)} records / {df['session_id'].nunique()} sessions")
    print(f"[dataset] normal={int((df.label == 0).sum())}  misbehaviour={int((df.label == 1).sum())}")


if __name__ == "__main__":
    main()
