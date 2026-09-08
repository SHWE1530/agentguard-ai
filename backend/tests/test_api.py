"""API-surface tests using FastAPI's TestClient against a throwaway database."""
from __future__ import annotations

import pytest

# DATABASE_URL is configured in conftest.py, before the app is imported.
from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["model_loaded"] is True


def test_ml_status_exposes_real_evaluation(client):
    body = client.get("/api/ml/status").json()
    assert body["model"] == "IsolationForest"
    assert body["loaded"] is True
    m = body["evaluation"]["metrics"]
    assert 0.0 <= m["precision"] <= 1.0
    assert 0.0 <= m["recall"] <= 1.0
    assert body["evaluation"]["dataset"].startswith("SYNTHETIC")


def test_scenarios_listed(client):
    keys = {s["key"] for s in client.get("/api/scenarios").json()}
    assert keys == {"normal", "abnormal", "critical", "approval"}


def test_agent_is_seeded(client):
    agents = client.get("/api/agents").json()
    assert any(a["name"] == "OpsAssist-Agent" for a in agents)


def test_invalid_scenario_is_rejected(client):
    r = client.post("/api/simulations/start", json={"scenario": "does-not-exist"})
    assert r.status_code == 400
    assert "Unknown scenario" in r.json()["detail"]


def test_malformed_payload_is_rejected(client):
    assert client.post("/api/simulations/start", json={}).status_code == 422


def test_missing_incident_returns_404(client):
    r = client.get("/api/incidents/nope")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]


def test_unknown_action_type_is_rejected(client):
    sess = client.post("/api/simulations/start", json={"scenario": "normal"}).json()
    r = client.post("/api/actions/evaluate",
                    json={"session_id": sess["session_id"], "action_type": "RM_RF_SLASH"})
    assert r.status_code == 400


def test_full_critical_flow_over_http(client):
    """Blocked destructive action -> incident -> recovery -> verified, via the API."""
    sess = client.post("/api/simulations/start", json={"scenario": "critical"}).json()
    sid = sess["session_id"]

    # Drive the sequence deterministically rather than waiting on the timer.
    prev = None
    for action in sess["planned_sequence"]:
        r = client.post("/api/actions/evaluate",
                        json={"session_id": sid, "action_type": action, "prev_action": prev})
        assert r.status_code == 200, r.text
        prev = action
    body = r.json()
    assert body["decision"] == "BLOCK_AND_STOP"
    assert body["action"]["action_status"] == "BLOCKED"
    assert body["executed"] is False

    incidents = client.get(f"/api/incidents").json()
    critical = [i for i in incidents if i["severity"] == "CRITICAL"]
    assert critical, "a CRITICAL incident should have been raised"
    inc_id = critical[0]["id"]

    detail = client.get(f"/api/incidents/{inc_id}").json()
    assert detail["ai_explanation"]
    assert detail["timeline"]
    assert detail["risk_factors"]["factors"]["action_severity"] == 100.0

    rec = client.post(f"/api/incidents/{inc_id}/recover").json()
    assert rec["verified"] is True
    assert rec["status"] == "RESOLVED"

    # Recovering twice must not silently "succeed".
    assert client.post(f"/api/incidents/{inc_id}/recover").status_code == 409

    env = client.get("/api/environment").json()
    assert env["verification"]["verified"] is True


def test_approval_flow_and_duplicate_decision(client):
    sess = client.post("/api/simulations/start", json={"scenario": "approval"}).json()
    sid = sess["session_id"]
    client.post("/api/actions/evaluate",
                json={"session_id": sid, "action_type": "FAILOVER_DATABASE"})

    pending = client.get("/api/pending-approvals").json()
    assert pending, "FAILOVER_DATABASE should require human approval"
    ap_id = pending[0]["id"]
    assert pending[0]["action"]["action_status"] == "PENDING_APPROVAL"

    ok = client.post(f"/api/approvals/{ap_id}/approve",
                     json={"decided_by": "judge", "note": "verified maintenance window"})
    assert ok.status_code == 200
    assert ok.json()["status"] == "APPROVED"

    dup = client.post(f"/api/approvals/{ap_id}/reject", json={"decided_by": "judge"})
    assert dup.status_code == 409

    audit = client.get("/api/audit", params={"event_type": "HUMAN_APPROVAL"}).json()
    assert any("judge" in e["reason"] for e in audit)


def test_metrics_are_computed_not_hardcoded(client):
    m = client.get("/api/metrics").json()
    actions = client.get("/api/actions", params={"limit": 500}).json()
    assert m["total_actions"] == len(actions)
    assert m["normal_actions"] + m["suspicious_actions"] == m["total_actions"]
    assert 0.0 <= m["avg_anomaly_score"] <= 1.0
    assert m["recovery_success_rate"] is not None


def test_audit_filters(client):
    blocked = client.get("/api/audit", params={"event_type": "ACTION_BLOCKED"}).json()
    assert blocked and all(e["event_type"] == "ACTION_BLOCKED" for e in blocked)
    crit = client.get("/api/audit", params={"risk_level": "CRITICAL"}).json()
    assert all(e["risk_level"] == "CRITICAL" for e in crit)


def test_websocket_receives_live_events(client):
    with client.websocket_connect("/ws/events") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "connected"
        sess = client.post("/api/simulations/start", json={"scenario": "normal"}).json()
        client.post("/api/actions/evaluate",
                    json={"session_id": sess["session_id"],
                          "action_type": "CHECK_SERVER_HEALTH"})
        types = [ws.receive_json()["type"] for _ in range(3)]
        assert "action" in types or "audit" in types
