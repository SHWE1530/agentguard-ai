"""A toy 'existing agent' wrapped with the Sentinel guard.

    python -m sdk.example_agent

Requires the backend running. The tools are stand-ins that only print; the point is that
the dangerous ones never execute. Watch the dashboard (Agent Monitor / Incidents) while it runs.
"""
from __future__ import annotations

import sys

from sdk.sentinel_client import ActionBlocked, AgentTerminated, ApprovalRequired, Sentinel

PLAN = ["CHECK_SERVER_HEALTH", "READ_LOG", "ACCESS_CREDENTIAL_STORE", "MODIFY_PERMISSION", "EXPORT_DATA"]


def tool(name: str):
    return lambda: print(f"      [tool executed] {name}")


def main() -> int:
    sentinel = Sentinel("http://127.0.0.1:8000", user="judge", password="sentinel-demo")
    with sentinel.session("OpsAssist-Agent", "Perform routine maintenance.") as s:
        print(f"session {s.id}: task resolved to '{s.info['resolved_task_type']}'")
        for step in PLAN:
            try:
                s.guard(step, tool(step), dt=2.0)
                print(f"  ALLOWED     {step}")
            except AgentTerminated as e:
                print(f"  TERMINATED  {step}\n      {e.explanation[:140]}...")
                break
            except ActionBlocked as e:
                print(f"  BLOCKED     {step}  (safer alternative: {e.alternative['action'] if e.alternative else 'none'})")
            except ApprovalRequired as e:
                print(f"  HELD        {step}  waiting for a human ({e.approval_id})")
                break
    return 0


if __name__ == "__main__":
    sys.exit(main())
