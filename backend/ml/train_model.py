"""Train the Isolation Forest behavioural detector and per-agent fingerprints.

One-class / novelty detection: the forest is fitted on NORMAL sessions only and
never sees a label. Fingerprints (bigram/trigram/tool/resource/timing profiles)
are learned from the same normal sessions.

Leakage control: training features are computed with CROSS-FITTED fingerprints
(a session is featurised with a fingerprint learned from the OTHER half), so a
session's own transitions never make it look artificially familiar.

Score calibration: raw forest scores are unbounded (higher = more normal). They
are mapped to 0..1 with  anomaly = 1 / (1 + exp((raw - t) / s))  where t is the
5th percentile of normal-training raw scores and s = std / 4. Both are stored in
the artifact so runtime scoring equals training-time scoring.

Usage:
    python -m backend.ml.generate_dataset
    python -m backend.ml.train_model
"""
from __future__ import annotations

import argparse
import json
import os
import time
from typing import Dict, List

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from backend.app.agent.profiles import AGENTS
from backend.ml.features import FEATURE_NAMES
from backend.ml.generate_dataset import OUT_PATH, load
from backend.ml.replay import fit_fingerprint, session_features

HERE = os.path.dirname(__file__)
MODEL_DIR = os.path.join(HERE, "models")
MODEL_PATH = os.path.join(MODEL_DIR, "agent_behavior_model.joblib")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contamination", type=float, default=0.02)
    ap.add_argument("--n-estimators", type=int, default=120)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--skip-eval", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(OUT_PATH):
        raise SystemExit("Corpus missing. Run: python -m backend.ml.generate_dataset")
    sessions = load()
    train = [s for s in sessions if s["split"] == "train" and s["label"] == 0]
    val = [s for s in sessions if s["split"] == "val" and s["label"] == 0]
    print(f"[train] {len(train)} normal training sessions, {len(val)} validation sessions")

    # ---- fingerprints (final: all training sessions) ----
    fingerprints = {a: fit_fingerprint(a, train) for a in AGENTS}
    for a, fp in fingerprints.items():
        print(f"[train] fingerprint {a}: {fp.n_sessions:.0f} sessions, ref drift mean="
              f"{fp.ref_drift['mean']:.3f} p95={fp.ref_drift['p95']:.3f}")

    # ---- cross-fitted training features ----
    X: List[List[float]] = []
    for agent in AGENTS:
        mine = [s for s in train if s["agent"] == agent]
        half = len(mine) // 2
        for fold_a, fold_b in ((mine[:half], mine[half:]), (mine[half:], mine[:half])):
            fp = fit_fingerprint(agent, fold_b)
            for s in fold_a:
                rows, _ = session_features(s, fp)
                X.extend(rows)
    Xn = np.array(X)
    print(f"[train] fitting IsolationForest on {Xn.shape[0]} normal actions x {Xn.shape[1]} features")

    model = IsolationForest(n_estimators=args.n_estimators, contamination=args.contamination,
                            max_samples=512, random_state=7, n_jobs=-1).fit(Xn)
    raw = model.score_samples(Xn)
    t = float(np.percentile(raw, 5))
    s_ = float(max(np.std(raw) / 4.0, 1e-3))
    print(f"[train] calibration t={t:.5f} s={s_:.5f}")

    os.makedirs(MODEL_DIR, exist_ok=True)
    bundle = {"model": model, "t": t, "s": s_, "threshold": args.threshold,
              "feature_names": FEATURE_NAMES,
              "fingerprints": {a: fp.to_dict() for a, fp in fingerprints.items()},
              "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "n_train_actions": int(Xn.shape[0])}
    joblib.dump(bundle, MODEL_PATH)
    print(f"[train] model -> {MODEL_PATH}")

    if not args.skip_eval:
        from backend.ml.evaluate import run_and_save
        run_and_save()


if __name__ == "__main__":
    main()
