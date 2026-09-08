"""Populate the database with realistic demo history.

Every row is produced by running the real safety pipeline -- nothing is
fabricated, so the seeded dashboard shows genuine model output.

Usage:
    python -m backend.app.database.seed
"""
from __future__ import annotations

import random

from backend.app.database.db import init_db, session
from backend.app.database.models import (
    Action, Agent, Approval, AuditEvent, Incident, Intervention,
    RecoveryEvent, RiskAssessment, Session_, Task, utcnow,
)
from backend.app.services import recovery, sandbox, simulator
from backend.app.services.pipeline import evaluate_action

DEMO_SESSIONS = [
    ("normal", ["CHECK_SERVER_HEALTH", "CHECK_SERVICE_STATUS", "READ_LOG",
                "CLEAR_TEMP_FILES", "CREATE_TICKET"]),
    ("normal", ["CHECK_SERVER_HEALTH", "READ_LOG", "RESTART_SIMULATED_SERVICE",
                "CHECK_SERVICE_STATUS", "CREATE_TICKET"]),
    ("normal", ["CHECK_SERVICE_STATUS", "SCALE_SIMULATED_SERVICE", "CREATE_TICKET"]),
    ("abnormal", ["CHECK_SERVER_HEALTH", "READ_LOG", "ACCESS_UNAUTHORIZED_FILE",
                  "READ_SENSITIVE_DATA"]),
    ("critical", ["CHECK_SERVER_HEALTH", "MODIFY_PERMISSION", "EXPORT_DATA",
                  "DELETE_DATABASE"]),
    ("approval", ["CHECK_SERVER_HEALTH", "CHECK_SERVICE_STATUS", "FAILOVER_DATABASE"]),
]


def wipe(db) -> None:
    for model in (RecoveryEvent, Intervention, RiskAssessment, Approval, AuditEvent,
                  Incident, Action, Task, Session_, Agent):
        db.query(model).delete()
    db.commit()
    sandbox.restore(db)


def seed() -> None:
    init_db()
    db = session()
    rng = random.Random(11)
    try:
        wipe(db)
        agent = simulator.ensure_agent(db)
        sandbox.ensure_baseline(db)

        for scenario, sequence in DEMO_SESSIONS:
            agent.status = "RUNNING"
            sess = Session_(agent_id=agent.id, scenario=scenario, status="RUNNING")
            db.add(sess)
            db.commit()
            task = Task(session_id=sess.id, description=f"Seeded '{scenario}' demo session.")
            db.add(task)
            db.commit()

            prev = None
            for step, action_type in enumerate(sequence):
                evaluate_action(db, agent=agent, sess=sess, task_id=task.id,
                                action_type=action_type, step_index=step, prev_action=prev,
                                seconds_since_prev=rng.uniform(1.0, 6.0))
                prev = action_type
                db.refresh(sess)
                if sess.status in ("PAUSED", "AWAITING_APPROVAL"):
                    break

            db.refresh(sess)
            if sess.status == "RUNNING":
                sess.status = "COMPLETED"
                sess.ended_at = utcnow()
                agent.status = "IDLE"
                db.commit()

        # Resolve the critical incident so the dashboard shows a real recovery rate,
        # and leave one open so the Incident Center has something to act on.
        open_incidents = (db.query(Incident).filter(Incident.status == "OPEN")
                            .order_by(Incident.risk_score.desc()).all())
        for inc in open_incidents[:1]:
            recovery.run_recovery(db, inc)

        agent.status = "IDLE"
        db.commit()

        print(f"[seed] agents      : {db.query(Agent).count()}")
        print(f"[seed] sessions    : {db.query(Session_).count()}")
        print(f"[seed] actions     : {db.query(Action).count()}")
        print(f"[seed] incidents   : {db.query(Incident).count()} "
              f"(resolved: {db.query(Incident).filter(Incident.status == 'RESOLVED').count()})")
        print(f"[seed] approvals   : {db.query(Approval).count()} pending: "
              f"{db.query(Approval).filter(Approval.status == 'PENDING').count()}")
        print(f"[seed] audit events: {db.query(AuditEvent).count()}")
        print("[seed] done.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
