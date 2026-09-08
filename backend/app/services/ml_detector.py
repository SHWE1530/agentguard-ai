"""Runtime wrapper around the trained Isolation Forest.

The model is loaded ONCE at import time (never retrained at startup) and used
to score every attempted agent action.
"""
from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional

import joblib

from backend.app.config import EVALUATION_PATH, MODEL_PATH
from backend.ml.features import FEATURE_NAMES, ActionContext, build_feature_vector


class MLDetector:
    def __init__(self, model_path: str = MODEL_PATH) -> None:
        self.model_path = model_path
        self.model = None
        self.t = 0.0
        self.s = 1.0
        self.feature_names: List[str] = FEATURE_NAMES
        self.load_error: Optional[str] = None
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.model_path):
            self.load_error = (
                "Model artifact not found. Run:  python -m backend.ml.generate_dataset  "
                "then  python -m backend.ml.train_model"
            )
            return
        try:
            bundle = joblib.load(self.model_path)
            self.model = bundle["model"]
            self.t = float(bundle["t"])
            self.s = float(bundle["s"])
            self.feature_names = bundle.get("feature_names", FEATURE_NAMES)
        except Exception as exc:  # pragma: no cover - defensive
            self.load_error = f"Failed to load model: {exc}"
            self.model = None

    @property
    def ready(self) -> bool:
        return self.model is not None

    def score(self, ctx: ActionContext) -> Dict[str, Any]:
        """Return the calibrated 0..1 anomaly score plus the feature vector."""
        vector = build_feature_vector(ctx)
        if not self.ready:
            # Degraded mode: the safety layer must still function without ML.
            # Fall back to a transparent heuristic and say so.
            fallback = min(1.0, 0.5 * vector[1] + 0.3 * vector[2] + 0.2 * vector[4])
            return {
                "anomaly_score": round(float(fallback), 4),
                "raw_score": None,
                "source": "heuristic_fallback",
                "features": dict(zip(self.feature_names, vector)),
            }

        raw = float(self.model.score_samples([vector])[0])
        anomaly = 1.0 / (1.0 + math.exp((raw - self.t) / self.s))
        return {
            "anomaly_score": round(float(anomaly), 4),
            "raw_score": round(raw, 6),
            "source": "isolation_forest",
            "features": dict(zip(self.feature_names, vector)),
        }

    def status(self) -> Dict[str, Any]:
        evaluation = None
        if os.path.exists(EVALUATION_PATH):
            try:
                with open(EVALUATION_PATH, encoding="utf-8") as fh:
                    evaluation = json.load(fh)
            except Exception:
                evaluation = None
        return {
            "model": "IsolationForest",
            "loaded": self.ready,
            "model_path": self.model_path,
            "error": self.load_error,
            "calibration": {"t": self.t, "s": self.s},
            "n_features": len(self.feature_names),
            "feature_names": self.feature_names,
            "evaluation": evaluation,
        }


detector = MLDetector()
