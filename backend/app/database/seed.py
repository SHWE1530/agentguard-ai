"""Populate the database with realistic demo history.

Every row is produced by running the real safety pipeline (synchronously, no
timers) -- nothing is fabricated, so the seeded dashboard shows genuine model
output, genuine trust scores and genuine drift.

Usage:
    python -m backend.app.database.seed
"""
from __future__ import annotations

from backend.app.database.db import reset_db, session
from backend.app.database.models import (
    Action, Agent, Approval, AuditEvent, Incident, Session_,
)
from backend.app.services import baseline, sandbox, simulator, trust as trust_svc

# (scenario, approve-decision-for-held-actions)
HISTORY = [
    ("normal", None), ("normal", None), ("refund_normal", None), ("legit_unusual", None),
    ("refund_normal", None), ("unauthorized_file", None), ("normal", None),
    ("sensitive_data", None), ("prompt_injection", None), ("priv_escalation", None),
]
QUICK_HISTORY = [("normal", None), ("refund_normal", None), ("sensitive_data", None), ("prompt_injection", None)]
LEAVE_PENDING = ["approval"]      # left waiting so the Approvals page is populated


def seed(verbose: bool = True, history=None) -> dict:
    reset_db()
    baseline.clear_cache()
    db = session()
    try:
        sandbox.ensure_baseline(db)
        simulator.ensure_all_agents(db)
        for key, approve in (history if history is not None else HISTORY):
            simulator.run_sync(db, key, approve=approve)
        for key in LEAVE_PENDING:
            simulator.run_sync(db, key, approve=None)
        # settle agents: nothing is "running" in a freshly seeded system
        for a in db.query(Agent).all():
            if a.status in ("RUNNING", "SUSPICIOUS"):
                a.status = "IDLE"
        db.commit()
        for a in db.query(Agent).all():
            trust_svc.snapshot(db, a.id, "SEED_COMPLETE")
        out = {
            "agents": db.query(Agent).count(), "sessions": db.query(Session_).count(),
            "actions": db.query(Action).count(), "incidents": db.query(Incident).count(),
            "resolved": db.query(Incident).filter(Incident.status == "RESOLVED").count(),
            "pending_approvals": db.query(Approval).filter(Approval.status == "PENDING").count(),
            "audit_events": db.query(AuditEvent).count(),
            "trust": {a.name: trust_svc.compute(db, a.id)["score"] for a in db.query(Agent).all()},
        }
        if verbose:
            for k, v in out.items():
                print(f"[seed] {k:<18}: {v}")
            print("[seed] done.")
        return out
    finally:
        db.close()


if __name__ == "__main__":
    seed()
