"""Minimal client for putting an EXISTING agent behind Agent Sentinel.

    from sdk.sentinel_client import Sentinel, ActionBlocked

    sentinel = Sentinel("http://127.0.0.1:8000", user="judge", password="sentinel-demo")
    with sentinel.session("OpsAssist-Agent", "Perform routine maintenance.") as s:
        s.guard("CHECK_SERVER_HEALTH", tool=check_health)          # runs the tool only if allowed
        s.guard("EXPORT_DATA", tool=export)                        # raises ActionBlocked, tool never runs

The contract is one HTTP call BEFORE each tool call:

    POST /api/actions/evaluate  ->  {"decision": ALLOW|MONITOR|REQUIRE_APPROVAL|BLOCK|TERMINATE, ...}

ALLOW / MONITOR   run the tool.
REQUIRE_APPROVAL  do not run it yet; the request waits for a human (poll `wait_for_approval`).
BLOCK             do not run it; the agent may continue with other work.
TERMINATE         stop the agent; the session is halted server-side.

Context (history, task, trust, environment) is always read from Sentinel's database, so
an agent cannot lower its own risk by misreporting. Limitations: the agent must be
registered in agent/profiles.py and policies/agent_policy.json; Sentinel decides, but the
CALLING code is what enforces, so the guard must wrap every tool the agent can reach.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional


class SentinelError(Exception):
    pass


class ActionBlocked(SentinelError):
    def __init__(self, decision: str, action: str, explanation: str, alternative: Optional[dict] = None):
        super().__init__(f"{decision}: {action}")
        self.decision, self.action, self.explanation, self.alternative = decision, action, explanation, alternative


class AgentTerminated(ActionBlocked):
    pass


class ApprovalRequired(SentinelError):
    def __init__(self, approval_id: str, action: str):
        super().__init__(f"approval required for {action}")
        self.approval_id, self.action = approval_id, action


class Sentinel:
    def __init__(self, base_url: str = "http://127.0.0.1:8000", user: str = "", password: str = "",
                 client: Any = None) -> None:
        if client is None:
            import httpx
            client = httpx.Client(base_url=base_url, timeout=15.0)
        self.http = client
        if user:
            r = self.http.post("/api/auth/login", json={"username": user, "password": password})
            if r.status_code != 200:
                raise SentinelError(f"login failed: {r.json().get('detail', r.status_code)}")
            self.http.headers["Authorization"] = "Bearer " + r.json()["token"]

    def session(self, agent_name: str, task: str) -> "Session":
        r = self.http.post("/api/sessions/open", json={"agent_name": agent_name, "task": task})
        if r.status_code != 200:
            raise SentinelError(r.json().get("detail", r.text))
        return Session(self, r.json())


class Session:
    def __init__(self, sentinel: Sentinel, info: Dict[str, Any]) -> None:
        self.s, self.info, self.id = sentinel, info, info["session_id"]
        self.last: Optional[Dict[str, Any]] = None

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            self.s.http.post(f"/api/sessions/{self.id}/close")
        except Exception:
            pass
        return False

    def check(self, action: str, dt: float = 3.0, failed: bool = False, content: Optional[str] = None) -> Dict[str, Any]:
        """Ask Sentinel about an action WITHOUT running anything."""
        r = self.s.http.post("/api/actions/evaluate", json={
            "session_id": self.id, "action_type": action, "dt": dt, "failed": failed, "content": content})
        if r.status_code != 200:
            raise SentinelError(r.json().get("detail", r.text))
        self.last = r.json()
        return self.last

    def guard(self, action: str, tool: Optional[Callable[[], Any]] = None, dt: float = 3.0,
              content: Optional[str] = None) -> Any:
        """Evaluate, then run `tool()` only if the decision permits it."""
        res = self.check(action, dt=dt, content=content)
        d, a = res["decision"], res["action"]
        if d in ("ALLOW", "MONITOR"):
            return tool() if tool else res
        alt = res.get("analysis", {}).get("alternative")
        if d == "REQUIRE_APPROVAL":
            raise ApprovalRequired(res["approval_id"], action)
        if d == "TERMINATE":
            raise AgentTerminated(d, action, a["explanation"], alt)
        raise ActionBlocked(d, action, a["explanation"], alt)

    def wait_for_approval(self, approval_id: str, timeout: float = 60.0, poll: float = 1.0) -> str:
        """Block until a human decides. Returns APPROVED or REJECTED."""
        end = time.time() + timeout
        while time.time() < end:
            for a in self.s.http.get("/api/approvals").json():
                if a["id"] == approval_id and a["status"] != "PENDING":
                    return a["status"]
            time.sleep(poll)
        raise SentinelError("timed out waiting for a human decision")
