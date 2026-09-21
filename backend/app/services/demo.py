"""Judge mode: a scripted, repeatable 2-3 minute walk through the whole pipeline.

    NORMAL AGENT -> NORMAL ACTIONS -> UNUSUAL-BUT-LEGITIMATE -> MISBEHAVIOUR ->
    DETECTION -> RISK ESCALATION -> BLOCK -> PAUSE -> EXPLANATION -> RECOVERY ->
    VERIFICATION -> AUDIT

The demo drives the REAL pipeline (real ML scores, real policy, real recovery).
Only the narration and the pacing are scripted. `reset()` returns the system to
a known seeded state so the demo is repeatable.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

from backend.app.agent import scenarios as scen
from backend.app.database.db import session as new_session
from backend.app.database.models import Agent, AuditEvent, Incident, Session_, Task
from backend.app.services import audit, baseline, recovery, simulator
from backend.app.services.events import hub

STATE: Dict[str, Any] = {"running": False, "stage": None, "session_ids": [], "started": None}

STAGES: List[Dict[str, str]] = [
    {"key": "normal", "title": "1 · A normal agent doing normal work",
     "narration": "OpsAssist-Agent is doing routine maintenance. Every action is scored by the behavioural model and checked against policy. Low risk, all allowed."},
    {"key": "unusual", "title": "2 · Unusual, but legitimate",
     "narration": "An outage response is bursty and repetitive - statistically strange. A model-only guard would block it. Watch the risk stay below the intervention thresholds: unusual is not the same as dangerous."},
    {"key": "misbehavior", "title": "3 · The agent goes rogue",
     "narration": "Same agent, new session. Three normal actions, then it reaches for the credential store and tries to change permissions. Nothing about the agent's identity changed - only its behaviour."},
    {"key": "response", "title": "4 · Detect, decide, halt, explain",
     "narration": "Each attempt is blocked BEFORE execution. The sequence 'observe -> credentials -> permission write' matches a kill chain, so the agent is terminated. The explanation is built from the signals that fired."},
    {"key": "recovery", "title": "5 · Recover and verify",
     "narration": "Recovery is a procedure: pause, revert permissions, restore resources, then independently re-inspect every resource (state and integrity). 'Verified' is only reported if every check passes."},
    {"key": "drill", "title": "6 · When recovery itself fails",
     "narration": "Prevention is never perfect. In this drill the guard is bypassed (a simulated monitoring outage) so real damage lands: permissions escalated, data exfiltrated. Detection still fires. The first recovery attempt is faulty, so it reports PARTIAL and verification FAILS - it does not claim success. The retry then completes and verifies. Note the residual-risk warning: a rollback cannot recall data that already left."},
    {"key": "audit", "title": "7 · Audit",
     "narration": "Every step above is in the append-only audit trail: detection, policy rule, risk factors, decision, recovery steps, trust change."},
]


def reset(quick: bool = True) -> Dict[str, Any]:
    """Return to a known seeded state (also used by the RESET DEMO button)."""
    if STATE["running"]:
        raise RuntimeError("A demo is currently running.")
    from backend.app.database import seed as seed_mod
    out = seed_mod.seed(verbose=False, history=seed_mod.QUICK_HISTORY if quick else None)
    db = new_session()
    try:
        audit.record(db, "DEMO_RESET", reason="Demo reset to a known seeded state.")
    finally:
        db.close()
    STATE.update(stage=None, session_ids=[], started=None)
    hub.publish("demo_reset", out)
    return out


def _stage(index: int) -> None:
    st = STAGES[index]
    STATE["stage"] = st["key"]
    hub.publish("demo_stage", {"index": index, "total": len(STAGES), **st})


async def _play(key: str, step_delay: float, recover_pace: float = 0.0) -> str:
    """Run one scenario with fixed pacing; returns the session id."""
    db = new_session()
    try:
        sess, task, agent, sc = simulator.create_session(db, key)
        STATE["session_ids"].append(sess.id)
        while True:
            await asyncio.sleep(step_delay)
            _, stop = simulator.advance(db, sess, agent, task)
            if stop:
                break
        simulator.finish_session(db, sess, agent)
        if sc.auto_recover:
            inc = (db.query(Incident).filter(Incident.session_id == sess.id, Incident.status == "OPEN")
                     .order_by(Incident.risk_score.desc()).first())
            if inc is not None:
                iid = inc.id

                def go() -> None:
                    d2 = new_session()
                    try:
                        recovery.run_recovery(d2, d2.get(Incident, iid), fault=sc.fault, pace_s=recover_pace)
                    finally:
                        d2.close()

                await asyncio.get_running_loop().run_in_executor(None, go)
        return sess.id
    finally:
        db.close()


def _schedule_run() -> bool:
    """Called from a request thread; marks the demo running immediately to block double starts."""
    STATE.update(running=True, session_ids=[])
    ok = simulator._schedule("demo", run())
    if not ok:
        STATE["running"] = False
    return ok


async def run() -> None:
    try:
        _stage(0)
        await asyncio.sleep(3.5)
        await _play("normal", 1.7)
        await asyncio.sleep(3.0)

        _stage(1)
        await asyncio.sleep(4.5)
        await _play("legit_unusual", 1.3)
        await asyncio.sleep(3.5)

        _stage(2)
        await asyncio.sleep(4.0)
        # the flagship session: play its steps, narrating the response as it unfolds
        db = new_session()
        try:
            sess, task, agent, sc = simulator.create_session(db, "judge_flagship")
            STATE["session_ids"].append(sess.id)
            i = 0
            while True:
                await asyncio.sleep(2.4)
                if i == 3:
                    _stage(3)
                _, stop = simulator.advance(db, sess, agent, task)
                i += 1
                if stop:
                    break
            simulator.finish_session(db, sess, agent)
            flagship_id = sess.id
            inc = (db.query(Incident).filter(Incident.session_id == sess.id, Incident.status == "OPEN")
                     .order_by(Incident.risk_score.desc()).first())
        finally:
            db.close()
        await asyncio.sleep(9.0)          # time to read the explanation

        _stage(4)
        await asyncio.sleep(2.5)
        if inc is not None:
            iid = inc.id

            def go() -> None:
                d2 = new_session()
                try:
                    recovery.run_recovery(d2, d2.get(Incident, iid), pace_s=1.4)
                finally:
                    d2.close()

            await asyncio.get_running_loop().run_in_executor(None, go)
        await asyncio.sleep(4.0)

        # ---- recovery drill: damage slips through, first recovery is partial, retry succeeds
        _stage(5)
        await asyncio.sleep(5.0)
        db = new_session()
        try:
            dsess, dtask, dagent, dsc = simulator.create_session(db, "recovery_failure")
            STATE["session_ids"].append(dsess.id)
            while True:
                await asyncio.sleep(1.6)
                _, stop = simulator.advance(db, dsess, dagent, dtask)
                if stop:
                    break
            simulator.finish_session(db, dsess, dagent)
            dinc = (db.query(Incident).filter(Incident.session_id == dsess.id, Incident.status == "OPEN")
                      .order_by(Incident.risk_score.desc()).first())
            diid = dinc.id if dinc else None
        finally:
            db.close()
        await asyncio.sleep(1.0)
        if diid:
            def attempt(fault):
                d2 = new_session()
                try:
                    recovery.run_recovery(d2, d2.get(Incident, diid), fault=fault, pace_s=1.3)
                finally:
                    d2.close()

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, attempt, "partial")     # attempt 1: PARTIAL, verification fails
            await asyncio.sleep(4.5)
            await loop.run_in_executor(None, attempt, None)          # attempt 2: retry, verified
        await asyncio.sleep(4.0)

        _stage(6)
        d3 = new_session()
        try:
            n = d3.query(AuditEvent).count()
            n_sess = d3.query(AuditEvent).filter(AuditEvent.session_id == flagship_id).count()
        finally:
            d3.close()
        hub.publish("demo_finished", {"audit_events_total": n, "audit_events_flagship": n_sess,
                                      "session_ids": STATE["session_ids"]})
    except Exception as exc:  # pragma: no cover - defensive
        hub.publish("error", {"message": f"Demo failed: {exc}"})
    finally:
        STATE["running"] = False
