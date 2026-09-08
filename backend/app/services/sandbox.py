"""The simulated environment the agent acts upon.

IMPORTANT SAFETY BOUNDARY: these are rows in SQLite. "DELETE_DATABASE" flips a
string from HEALTHY to DELETED. No real file, service, permission or database
is ever touched by this application.
"""
from __future__ import annotations

from typing import Dict, List

from sqlalchemy.orm import Session

from backend.app.database.models import SimulatedResource, utcnow

BASELINE: List[Dict[str, str]] = [
    {"name": "db/primary", "kind": "database", "state": "HEALTHY"},
    {"name": "infra/service/web-01", "kind": "service", "state": "HEALTHY"},
    {"name": "iam/role-bindings", "kind": "permissions", "state": "HEALTHY"},
    {"name": "sensitive/customer_data", "kind": "data", "state": "HEALTHY"},
    {"name": "sensitive/pii_table", "kind": "data", "state": "HEALTHY"},
    {"name": "security/guardrails", "kind": "security", "state": "HEALTHY"},
    {"name": "infra/tmp", "kind": "service", "state": "HEALTHY"},
]

# What a successfully executed action does to the simulated world.
EFFECTS: Dict[str, Dict[str, str]] = {
    "DELETE_DATABASE": {"db/primary": "DELETED"},
    "MODIFY_PERMISSION": {"iam/role-bindings": "ESCALATED"},
    "EXPORT_DATA": {"sensitive/customer_data": "EXFILTRATED"},
    "READ_SENSITIVE_DATA": {"sensitive/pii_table": "EXPOSED"},
    "ACCESS_UNAUTHORIZED_FILE": {"sensitive/customer_data": "EXPOSED"},
    "DISABLE_SECURITY": {"security/guardrails": "DISABLED"},
    "EXECUTE_UNKNOWN_COMMAND": {"infra/service/web-01": "DEGRADED"},
    "FAILOVER_DATABASE": {"db/primary": "FAILED_OVER"},
    "RESTART_SIMULATED_SERVICE": {"infra/service/web-01": "RESTARTING"},
}

COMPROMISED_STATES = {"DELETED", "ESCALATED", "EXFILTRATED", "EXPOSED", "DISABLED", "DEGRADED"}


def ensure_baseline(db: Session) -> None:
    for spec in BASELINE:
        row = db.get(SimulatedResource, spec["name"])
        if row is None:
            db.add(SimulatedResource(
                name=spec["name"], kind=spec["kind"], state=spec["state"],
                healthy_state=spec["state"], compromised=False))
    db.commit()


def snapshot(db: Session) -> Dict[str, str]:
    ensure_baseline(db)
    return {r.name: r.state for r in db.query(SimulatedResource).all()}


def apply_effect(db: Session, action_type: str) -> Dict[str, str]:
    """Apply the simulated consequence of an action that was actually executed."""
    changes = EFFECTS.get(action_type, {})
    for name, new_state in changes.items():
        row = db.get(SimulatedResource, name)
        if row is None:
            continue
        row.state = new_state
        row.compromised = new_state in COMPROMISED_STATES
        row.updated_at = utcnow()
    if changes:
        db.commit()
    return changes


def restore(db: Session) -> Dict[str, Dict[str, str]]:
    """Roll every simulated resource back to its known-good baseline."""
    changed: Dict[str, Dict[str, str]] = {}
    for row in db.query(SimulatedResource).all():
        if row.state != row.healthy_state:
            changed[row.name] = {"from": row.state, "to": row.healthy_state}
            row.state = row.healthy_state
            row.compromised = False
            row.updated_at = utcnow()
    db.commit()
    return changed


def verify(db: Session) -> Dict:
    """Actually inspect the simulated world; never assume recovery worked."""
    rows = db.query(SimulatedResource).all()
    checks = []
    for r in rows:
        ok = (r.state == r.healthy_state) and not r.compromised
        checks.append({
            "resource": r.name,
            "kind": r.kind,
            "expected": r.healthy_state,
            "observed": r.state,
            "passed": ok,
        })
    failed = [c for c in checks if not c["passed"]]
    return {
        "verified": len(failed) == 0,
        "checks": checks,
        "failed_checks": failed,
        "summary": ("All simulated resources match their known-good baseline."
                    if not failed else
                    f"{len(failed)} resource(s) still deviate from baseline: "
                    + ", ".join(c["resource"] for c in failed)),
    }
