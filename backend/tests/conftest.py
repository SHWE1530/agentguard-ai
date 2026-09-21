"""Shared test setup.

DATABASE_URL must be set before anything imports the app, because the SQLAlchemy
engine is created at import time. SIMULATION_STEP_DELAY is huge so background
simulations started through the API never race the test that started them;
tests that need a full run use simulator.run_sync (no timers).
"""
from __future__ import annotations

import os
import tempfile

import pytest

_TMP = os.path.join(tempfile.gettempdir(), "sentinel_pytest.db")
if os.path.exists(_TMP):
    try:
        os.remove(_TMP)
    except OSError:
        pass
os.environ["DATABASE_URL"] = "sqlite:///" + _TMP
os.environ["SIMULATION_STEP_DELAY"] = "3600"
os.environ["SENTINEL_AUTH"] = "off"      # auth has its own tests (test_auth.py) that switch it on


@pytest.fixture
def db():
    """A fresh, seeded-with-nothing database for every test."""
    from backend.app.database.db import reset_db, session
    from backend.app.services import baseline, sandbox, simulator

    reset_db()
    baseline.clear_cache()
    s = session()
    sandbox.ensure_baseline(s)
    simulator.ensure_all_agents(s)
    yield s
    s.close()
