"""End-to-end tests for the safety pipeline, run against a temporary database."""
from __future__ import annotations

import pytest

# DATABASE_URL is configured in conftest.py, before the app is imported.
from backend.app.database.db import init_db, session  # noqa: E402
from backend.app.database.models import (  # noqa: E402
    Action, Approval, AuditEvent, Incident, Intervention, Session_, Task,
)
from backend.app.services import recovery, sandbox, simulator  # noqa: E402
from backend.app.services.ml_detector import detector  # noqa: E402
from backend.app.services.pipeline import evaluate_action  # noqa: E402
from backend.app.services.policy_engine import policy_engine  # noqa: E402


@pytest.fixture(scope="module")
def db():
    init_db()
    s = session()
    sandbox.ensure_baseline(s)
    sandbox.restore(s)   # start from a known-good simulated world
    yield s
    s.close()


@pytest.fixture
def ctx(db):
    """A fresh agent session + task to attach actions to."""
    agent = simulator.ensure_agent(db)
    agent.status = "RUNNING"
    sess = Session_(agent_id=agent.id, scenario="test", status="RUNNING")
    db.add(sess)
    db.commit()
    task = Task(session_id=sess.id, description="test task")
    db.add(task)
    db.commit()
    return agent, sess, task


def run(db, ctx, action_type, step=0, prev=None):
    agent, sess, task = ctx
    return evaluate_action(db, agent=agent, sess=sess, task_id=task.id,
                           action_type=action_type, step_index=step, prev_action=prev)


# ----------------------------------------------------------------- ML model
def test_model_is_loaded():
    assert detector.ready, detector.load_error


def test_normal_action_scores_low_and_is_allowed(db, ctx):
    r = run(db, ctx, "CHECK_SERVER_HEALTH")
    a = r["action"]
    assert r["decision"] == "ALLOW"
    assert a["action_status"] == "ALLOWED"
    assert a["risk_level"] == "LOW"
    assert a["anomaly_score"] < 0.5
    assert a["policy_violation"] is None
    assert r["executed"] is True


def test_suspicious_action_is_detected_and_scored_high(db, ctx):
    r = run(db, ctx, "ACCESS_UNAUTHORIZED_FILE", step=1, prev="READ_LOG")
    a = r["action"]
    assert a["anomaly_score"] > 0.6
    assert a["risk_level"] in ("HIGH", "CRITICAL")
    assert a["policy_violation"] is not None
    assert r["decision"] in ("BLOCK", "BLOCK_AND_STOP", "REQUIRE_APPROVAL")
    assert r["incident_id"] is not None


def test_critical_destructive_action_is_blocked_and_stops_agent(db, ctx):
    agent, sess, _ = ctx
    r = run(db, ctx, "DELETE_DATABASE", step=2, prev="EXPORT_DATA")
    a = r["action"]
    assert r["decision"] == "BLOCK_AND_STOP"
    assert a["action_status"] == "BLOCKED"
    assert a["risk_level"] == "CRITICAL"
    assert a["risk_score"] >= 85
    assert r["executed"] is False
    db.refresh(agent)
    db.refresh(sess)
    assert agent.status == "PAUSED"
    assert sess.status == "PAUSED"
    # The blocked action must NOT have touched the simulated database.
    assert sandbox.snapshot(db)["db/primary"] == "HEALTHY"


def test_risk_is_not_merely_the_anomaly_score(db, ctx):
    r = run(db, ctx, "DELETE_DATABASE", step=3, prev="CHECK_SERVER_HEALTH")
    factors = r["action"]["risk_factors"]["factors"]
    assert set(factors) == {"behavior_anomaly", "resource_sensitivity",
                            "permission_risk", "action_severity", "task_relevance_gap"}
    assert r["action"]["risk_score"] != r["action"]["anomaly_score"] * 100


def test_policy_violations_are_specific(db, ctx):
    r = run(db, ctx, "MODIFY_PERMISSION", step=4, prev="CHECK_SERVER_HEALTH")
    violations = r["action"]["risk_factors"]["policy_violations"]
    assert "EXPLICITLY_DENIED_ACTION" in violations
    assert "RESOURCE_OUTSIDE_TASK_SCOPE" in violations
    assert "PERMISSION_CEILING_EXCEEDED" in violations
    assert "LOW_TASK_RELEVANCE" in violations
    # Escalation is reversible, so it must not be flagged as destructive.
    assert "DESTRUCTIVE_OPERATION" not in violations


def test_destructive_operations_are_flagged_as_such(db, ctx):
    r = run(db, ctx, "DELETE_DATABASE", step=0, prev="EXPORT_DATA")
    assert "DESTRUCTIVE_OPERATION" in r["action"]["risk_factors"]["policy_violations"]


def test_blocking_an_action_differs_from_halting_the_agent(db, ctx):
    """A denied-but-reversible action is blocked; the agent keeps running."""
    agent, sess, _ = ctx
    r = run(db, ctx, "MODIFY_PERMISSION", step=1, prev="CHECK_SERVER_HEALTH")
    assert r["decision"] == "BLOCK"
    assert r["action"]["action_status"] == "BLOCKED"
    db.refresh(agent)
    db.refresh(sess)
    assert agent.status == "SUSPICIOUS"
    assert sess.status == "RUNNING"


def test_repeated_blocks_pause_the_agent(db, ctx):
    """One block is not proof of compromise; a pattern of them is."""
    agent, sess, _ = ctx
    limit = policy_engine.policy["max_blocked_actions_per_session"]
    for i, action in enumerate(
        ["ACCESS_UNAUTHORIZED_FILE", "READ_SENSITIVE_DATA", "EXPORT_DATA"][:limit]
    ):
        run(db, ctx, action, step=i, prev="READ_LOG")
    db.refresh(agent)
    db.refresh(sess)
    assert agent.status == "PAUSED"
    assert sess.status == "PAUSED"


def test_explanations_differ_between_incidents(db, ctx):
    a = run(db, ctx, "DELETE_DATABASE", step=5, prev="EXPORT_DATA")["action"]["explanation"]
    b = run(db, ctx, "READ_SENSITIVE_DATA", step=6, prev="READ_LOG")["action"]["explanation"]
    assert a != b
    assert "DELETE_DATABASE" in a and "READ_SENSITIVE_DATA" in b


# ------------------------------------------------------------ human approval
def test_high_risk_action_requires_human_approval(db, ctx):
    r = run(db, ctx, "FAILOVER_DATABASE", step=7, prev="CHECK_SERVICE_STATUS")
    assert r["decision"] == "REQUIRE_APPROVAL"
    assert r["action"]["action_status"] == "PENDING_APPROVAL"
    assert r["approval_id"] is not None
    assert r["executed"] is False
    ap = db.get(Approval, r["approval_id"])
    assert ap.status == "PENDING"


# ---------------------------------------------------------------- recovery
def test_recovery_restores_and_verifies_state(db, ctx):
    # Simulate damage that slipped through, then recover from it.
    sandbox.apply_effect(db, "MODIFY_PERMISSION")
    sandbox.apply_effect(db, "EXPORT_DATA")
    assert sandbox.verify(db)["verified"] is False

    inc = db.query(Incident).filter(Incident.status == "OPEN").first()
    assert inc is not None
    result = recovery.run_recovery(db, inc)

    assert result["verified"] is True
    assert result["status"] == "RESOLVED"
    assert sandbox.snapshot(db)["iam/role-bindings"] == "HEALTHY"
    stages = [e["recovery_status"] for e in result["events"]]
    assert stages == ["STARTED", "COMPLETED", "VERIFIED"]


def test_verification_reports_failure_honestly(db):
    """State verification must not claim success when the world is still broken."""
    sandbox.apply_effect(db, "DELETE_DATABASE")
    result = sandbox.verify(db)
    assert result["verified"] is False
    assert any(c["resource"] == "db/primary" for c in result["failed_checks"])
    sandbox.restore(db)
    assert sandbox.verify(db)["verified"] is True


# ------------------------------------------------------------------- audit
def test_audit_trail_records_the_full_story(db, ctx):
    _, sess, _ = ctx
    run(db, ctx, "CHECK_SERVER_HEALTH", step=0)
    run(db, ctx, "DELETE_DATABASE", step=1, prev="CHECK_SERVER_HEALTH")
    events = {e.event_type for e in
              db.query(AuditEvent).filter(AuditEvent.session_id == sess.id).all()}
    for expected in ("ACTION_EXECUTED", "ANOMALY_DETECTED", "POLICY_VIOLATION",
                     "RISK_CALCULATED", "ACTION_BLOCKED", "INCIDENT_CREATED",
                     "AGENT_PAUSED"):
        assert expected in events, f"missing audit event {expected}"


def test_every_action_has_an_intervention_record(db):
    assert db.query(Intervention).count() == db.query(Action).count()


def test_policy_thresholds_match_spec():
    th = policy_engine.policy["thresholds"]["risk_levels"]
    assert (th["low"], th["medium"], th["high"], th["critical"]) == (0, 30, 60, 85)
    assert policy_engine.risk_level(10) == "LOW"
    assert policy_engine.risk_level(45) == "MEDIUM"
    assert policy_engine.risk_level(70) == "HIGH"
    assert policy_engine.risk_level(95) == "CRITICAL"
