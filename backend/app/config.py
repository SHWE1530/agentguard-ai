"""Runtime configuration. No secrets are required to run this prototype."""
from __future__ import annotations

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "sentinel.db"))
MODEL_PATH = os.getenv("MODEL_PATH", os.path.join(BASE_DIR, "ml", "models", "agent_behavior_model.joblib"))
EVALUATION_PATH = os.getenv("EVALUATION_PATH", os.path.join(BASE_DIR, "ml", "models", "evaluation.json"))
POLICY_PATH = os.getenv("POLICY_PATH", os.path.join(BASE_DIR, "app", "policies", "agent_policy.json"))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
SIMULATION_STEP_DELAY = float(os.getenv("SIMULATION_STEP_DELAY", "1.1"))
