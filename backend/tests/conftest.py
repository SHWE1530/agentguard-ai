"""Shared test setup.

The DATABASE_URL must be set before anything imports the app, because the
SQLAlchemy engine is created at import time. conftest.py is imported by pytest
before any test module, so this is the right place for it.
"""
from __future__ import annotations

import os
import tempfile

_TMP = os.path.join(tempfile.gettempdir(), "sentinel_pytest.db")
if os.path.exists(_TMP):
    try:
        os.remove(_TMP)
    except OSError:
        pass
os.environ["DATABASE_URL"] = "sqlite:///" + _TMP
os.environ.setdefault("SIMULATION_STEP_DELAY", "0.01")
