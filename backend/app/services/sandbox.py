"""The persistent simulated environment the agent acts upon.

IMPORTANT SAFETY BOUNDARY: these are rows in SQLite. "DELETE_DATABASE" flips a
string from HEALTHY to DELETED. No real file, service, permission or database
is ever touched by this application.

Each resource carries a state AND an integrity checksum. Recovery must restore
both; verification checks both, so a resource that merely LOOKS healthy but was
silently corrupted is caught.
"""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.app.database.models import SimulatedResource, utcnow
from backend.app.services import envsim
from backend.app.services.envsim import BASELINE, COMPROMISED_STATES, HEALTHY, checksum


def ensure_baseline(db: Session) -> None:
    for name, meta in BASELINE.items():
        row = db.get(SimulatedResource, name)
        if row is None:
            good = checksum(name, HEALTHY, 0)
            db.add(SimulatedResource(name=name, kind=meta["kind"], state=HEALTHY, healthy_state=HEALTHY,
                                     checksum=good, healthy_checksum=good, content_version=0,
                                     compromised=False))
    db.commit()


def snapshot(db: Session) -> Dict[str, str]:
    ensure_baseline(db)
    return {r.name: r.state for r in db.query(SimulatedResource).all()}


def apply_effect(db: Session, action_type: str) -> Dict[str, str]:
    """Apply the simulated consequence (including cascades) of an executed action."""
    before = snapshot(db)
    after, changes = envsim.apply(before, action_type)
    out: Dict[str, str] = {}
    for c in changes:
        row = db.get(SimulatedResource, c["resource"])
        if row is None:
            continue
        row.state = c["to"]
        row.compromised = c["to"] in COMPROMISED_STATES
        row.checksum = checksum(row.name, row.state, row.content_version)
        row.updated_at = utcnow()
        out[c["resource"]] = c["to"] + (" (cascade)" if c["cascade"] else "")
    if changes:
        db.commit()
    return out


def damaged(db: Session) -> List[SimulatedResource]:
    return [r for r in db.query(SimulatedResource).all()
            if r.state != r.healthy_state or r.checksum != r.healthy_checksum]


def restore_resource(db: Session, name: str, corrupt: bool = False) -> Dict[str, str]:
    """Roll one resource back to baseline. `corrupt` simulates a silent restore fault:
    the state string looks healthy but the content checksum does not match."""
    row = db.get(SimulatedResource, name)
    prev = row.state
    row.state = row.healthy_state
    row.compromised = False
    if corrupt:
        row.content_version = (row.content_version or 0) + 1
        row.checksum = checksum(row.name, row.state, row.content_version)
    else:
        row.content_version = 0
        row.checksum = row.healthy_checksum
    row.updated_at = utcnow()
    db.commit()
    return {"from": prev, "to": row.state}


def restore(db: Session) -> Dict[str, Dict[str, str]]:
    """Restore every damaged resource (used by seeding and tests; recovery uses steps)."""
    changed: Dict[str, Dict[str, str]] = {}
    for r in damaged(db):
        changed[r.name] = restore_resource(db, r.name)
    return changed


def verify(db: Session) -> Dict[str, Any]:
    """Actually inspect the world; never assume recovery worked."""
    checks = []
    for r in db.query(SimulatedResource).order_by(SimulatedResource.name).all():
        state_ok = r.state == r.healthy_state
        sum_ok = r.checksum == r.healthy_checksum
        checks.append({"resource": r.name, "kind": r.kind, "expected": r.healthy_state,
                       "observed": r.state, "state_ok": state_ok, "integrity_ok": sum_ok,
                       "passed": state_ok and sum_ok})
    failed = [c for c in checks if not c["passed"]]
    if not failed:
        summary = "All simulated resources match their known-good baseline (state and integrity)."
    else:
        bits = [f"{c['resource']} ({c['observed']}{'' if c['integrity_ok'] else ', integrity mismatch'})" for c in failed]
        summary = f"{len(failed)} resource(s) still deviate from baseline: " + ", ".join(bits)
    return {"verified": not failed, "checks": checks, "failed_checks": failed, "summary": summary}
