"""Authentication: real enforcement, roles, attribution, rate limiting, WebSocket."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app import config
from backend.app.main import app
from backend.app.services import auth


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    auth._attempts.clear()
    from backend.app.database.db import reset_db
    from backend.app.services import baseline
    with TestClient(app) as c:
        reset_db()
        baseline.clear_cache()
        yield c


def token(client, user="judge", pw="sentinel-demo"):
    r = client.post("/api/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_public_endpoints_and_protected_endpoints(secured):
    assert secured.get("/api/health").status_code == 200
    cfg = secured.get("/api/auth/config").json()
    assert cfg["enabled"] and cfg["demo_accounts"] and cfg["demo_hint"]
    for path in ("/api/metrics", "/api/incidents", "/api/audit", "/api/agents", "/api/evaluation"):
        assert secured.get(path).status_code == 401, path
    assert secured.post("/api/simulations/start", json={"scenario": "normal"}).status_code == 401


def test_login_and_authenticated_access(secured):
    h = token(secured)
    assert secured.get("/api/metrics", headers=h).status_code == 200
    assert secured.get("/api/auth/me", headers=h).json()["user"] == "judge"


def test_bad_credentials_and_tampered_tokens_are_rejected(secured):
    assert secured.post("/api/auth/login", json={"username": "judge", "password": "nope"}).status_code == 401
    assert secured.post("/api/auth/login", json={"username": "ghost", "password": "x"}).status_code == 401
    good = token(secured)["Authorization"][7:]
    body, sig = good.split(".")
    forged = body + "." + sig[:-2] + ("AA" if not sig.endswith("AA") else "BB")
    assert secured.get("/api/metrics", headers={"Authorization": "Bearer " + forged}).status_code == 401
    assert secured.get("/api/metrics", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_expired_token_is_rejected(secured, monkeypatch):
    monkeypatch.setattr(config, "AUTH_TOKEN_TTL_S", -10)
    h = token(secured)
    assert secured.get("/api/metrics", headers=h).status_code == 401


def test_viewer_is_read_only(secured):
    v = token(secured, "viewer", "sentinel-view")
    assert secured.get("/api/incidents", headers=v).status_code == 200
    r = secured.post("/api/simulations/start", json={"scenario": "normal"}, headers=v)
    assert r.status_code == 403 and "read-only" in r.json()["detail"]
    assert secured.post("/api/demo/reset", headers=v).status_code == 403


def test_login_is_rate_limited(secured):
    for _ in range(5):
        assert secured.post("/api/auth/login", json={"username": "judge", "password": "bad"}).status_code == 401
    r = secured.post("/api/auth/login", json={"username": "judge", "password": "sentinel-demo"})
    assert r.status_code == 429


def test_decision_is_attributed_to_the_authenticated_user_not_the_payload(secured):
    h = token(secured)
    sid = secured.post("/api/simulations/start", json={"scenario": "approval"}, headers=h).json()["session_id"]
    for a in ("CHECK_SERVER_HEALTH", "CHECK_SERVICE_STATUS", "FAILOVER_DATABASE"):
        secured.post("/api/actions/evaluate", json={"session_id": sid, "action_type": a}, headers=h)
    ap = secured.get("/api/pending-approvals", headers=h).json()[0]
    r = secured.post(f"/api/approvals/{ap['id']}/approve", json={"decided_by": "someone-else"}, headers=h)
    assert r.status_code == 200 and r.json()["decided_by"] == "judge"


def test_websocket_requires_a_valid_token(secured):
    with pytest.raises(WebSocketDisconnect):
        with secured.websocket_connect("/ws/events"):
            pass
    tok = token(secured)["Authorization"][7:]
    with secured.websocket_connect(f"/ws/events?token={tok}") as ws:
        assert ws.receive_json()["type"] == "connected"


def test_passwords_are_not_stored_in_plaintext():
    assert all(isinstance(h, bytes) and b"sentinel" not in h for h, _ in auth.USERS.values())


# ------------------------------------------------------------ SDK integration
def test_sdk_wraps_an_external_agent_dangerous_tools_never_run(secured):
    from sdk.sentinel_client import ActionBlocked, AgentTerminated, Sentinel

    ran = []
    sentinel = Sentinel(client=secured, user="judge", password="sentinel-demo")
    with sentinel.session("OpsAssist-Agent", "Perform routine maintenance.") as s:
        assert s.info["resolved_task_type"] == "routine_maintenance"
        s.guard("CHECK_SERVER_HEALTH", lambda: ran.append("health"), dt=2.0)
        s.guard("READ_LOG", lambda: ran.append("log"), dt=2.0)
        with pytest.raises(ActionBlocked) as blocked:
            s.guard("ACCESS_CREDENTIAL_STORE", lambda: ran.append("CREDENTIALS"), dt=1.5)
        assert blocked.value.alternative is not None
        with pytest.raises(AgentTerminated):
            s.guard("MODIFY_PERMISSION", lambda: ran.append("PERMISSIONS"), dt=1.2)
        sid = s.id
    assert ran == ["health", "log"], "blocked tools must never execute"
    assert secured.get(f"/api/simulations/{sid}", headers=token(secured)).json()["status"] in ("PAUSED", "STOPPED")


def test_open_session_rejects_unregistered_agents(secured):
    r = secured.post("/api/sessions/open", json={"agent_name": "RogueBot", "task": "do things"}, headers=token(secured))
    assert r.status_code == 404 and "Register it" in r.json()["detail"]
