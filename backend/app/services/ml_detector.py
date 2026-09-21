"""Runtime wrapper around the trained Isolation Forest.

The model is loaded ONCE at import time and never retrained at startup. It
scores a behavioural feature vector (see backend/ml/features.py) and returns a
calibrated 0..1 anomaly score:

    anomaly = 1 / (1 + exp((raw - t) / s))

where `raw` is the forest's unbounded score (higher = more normal) and (t, s)
were fitted on the NORMAL training data and stored inside the artifact.
"""
from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional, Sequence

import joblib
import numpy as np

from backend.app.config import EVALUATION_PATH, MODEL_PATH
from backend.app.services.fingerprint import Fingerprint
from backend.ml.features import FEATURE_NAMES


class MLDetector:
    def __init__(self, model_path: str = MODEL_PATH) -> None:
        self.model_path = model_path
        self.model = None
        self.t = 0.0
        self.s = 1.0
        self.feature_names: List[str] = FEATURE_NAMES
        self.fingerprints: Dict[str, dict] = {}
        self.load_error: Optional[str] = None
        self.threshold = 0.5
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.model_path):
            self.load_error = ("Model artifact not found. Run: python -m backend.ml.generate_dataset  "
                               "then  python -m backend.ml.train_model")
            return
        try:
            bundle = joblib.load(self.model_path)
            self.model = bundle["model"]
            self.model.n_jobs = 1          # single-sample scoring: threading overhead only hurts
            self.t, self.s = float(bundle["t"]), float(bundle["s"])
            self.feature_names = bundle.get("feature_names", FEATURE_NAMES)
            self.fingerprints = bundle.get("fingerprints", {})
            self.threshold = float(bundle.get("threshold", 0.5))
            if list(self.feature_names) != list(FEATURE_NAMES):
                self.model = None
                self.load_error = ("Model was trained with a different feature set. "
                                   "Re-run: python -m backend.ml.train_model")
        except Exception as exc:  # pragma: no cover - defensive
            self.load_error = f"Failed to load model: {exc}"
            self.model = None

    @property
    def ready(self) -> bool:
        return self.model is not None

    def bootstrap_fingerprint(self, agent: str) -> Fingerprint:
        d = self.fingerprints.get(agent)
        if d:
            return Fingerprint.from_dict(d)
        return Fingerprint(agent)

    def _norm(self, raw: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp((raw - self.t) / self.s))

    def score_vector(self, vec: Sequence[float]) -> Dict[str, Any]:
        """Score one feature vector (live path)."""
        if not self.ready:
            # Degraded mode: the safety layer must still function without ML.
            # Use a transparent heuristic and say so in the output.
            v = dict(zip(FEATURE_NAMES, vec))
            h = min(1.0, 0.35 * v["seq_bigram_deviation"] + 0.3 * (1 - v["intent_alignment"])
                    + 0.2 * v["resource_sensitivity"] + 0.15 * v["window_misalignment"])
            return {"anomaly_score": round(float(h), 4), "raw_score": None, "source": "heuristic_fallback"}
        raw = float(self.model.score_samples([list(vec)])[0])
        return {"anomaly_score": round(float(self._norm(np.array([raw]))[0]), 4),
                "raw_score": round(raw, 6), "source": "isolation_forest"}

    def score_matrix(self, X: np.ndarray) -> np.ndarray:
        """Batch scoring (evaluation path)."""
        if not self.ready:
            raise RuntimeError("model not loaded")
        return self._norm(self.model.score_samples(X))

    def status(self) -> Dict[str, Any]:
        evaluation = None
        if os.path.exists(EVALUATION_PATH):
            try:
                with open(EVALUATION_PATH, encoding="utf-8") as fh:
                    evaluation = json.load(fh)
            except Exception:
                evaluation = None
        return {
            "model": "IsolationForest", "loaded": self.ready, "model_path": self.model_path,
            "error": self.load_error, "calibration": {"t": self.t, "s": self.s},
            "threshold": self.threshold, "n_features": len(self.feature_names),
            "feature_names": self.feature_names, "evaluation": evaluation,
        }


detector = MLDetector()
