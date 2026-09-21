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
API_KEY = os.getenv("SENTINEL_API_KEY", "")   # optional; when set, write endpoints require X-API-Key

# ---- authentication -------------------------------------------------------
# Signed-token login for the dashboard/API. On by default; tests turn it off.
AUTH_ENABLED = os.getenv("SENTINEL_AUTH", "on").lower() not in ("off", "0", "false", "no")
AUTH_SECRET = os.getenv("SENTINEL_SECRET", "")            # empty -> random per process (tokens die on restart)
AUTH_TOKEN_TTL_S = int(os.getenv("SENTINEL_TOKEN_TTL", "28800"))
# "user:password:role,user2:password2:role2"; roles: operator (full) | viewer (read-only)
AUTH_USERS = os.getenv("SENTINEL_USERS", "")
DEMO_USERS = "judge:sentinel-demo:operator,viewer:sentinel-view:viewer"   # used only when SENTINEL_USERS is unset
