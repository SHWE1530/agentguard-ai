"""Integration tests: live pipeline + database, scenarios, recovery, approvals, trust, baseline."""
from __future__ import annotations

import json

import pytest

from backend.app.agent import scenarios as scen
from backend.app.database.models import (
    Action, Agent, Approval, AuditEvent, Incident, Intervention, RecoveryEvent, Session_,
)
from backend.app.services import approvals, baseline, evidence, recovery, sandbox, simulator, trust as trust_svc
from backend.app.services.fingerprint import Fingerprint
from backend.app.services.policy_engine import policy_engine
from backend.app.services.steps import StepRec


def actions(db, sid):
    return db.query(Action).filter(Action.session_id == sid).order_by(Action.step_index).all()


def decisions(db, sid):
    return [a.decision for a in actions(db, sid)]


def audit_types(db, sid):
    return {e.event_type for e in db.query(AuditEvent).filter(AuditEvent.session_id == sid)}


# ---------------------------------------------------------------- scenarios
def test_every_scenario_runs_and_matches_its_declared_outcome(db):
    """The library is not decoration: each scenario's stated intervention must actually happen."""
    expect = {
        "normal": lambda d: set(d) == {"ALLOW"},
        "refund_normal": lambda d: set(d) == {"ALLOW"},
        "unauthorized_file": lambda d: "BLOCK" in d and "TERMINATE" not in d,
        "sensitive_data": lambda d: "BLOCK" in d and "TERMINATE" not in d,
        "priv_escalation": lambda d: d[-1] == "TERMINATE",
        "destructive": lambda d: d[-1] == "TERMINATE",
        "multi_step": lambda d: d[-1] == "TERMINATE",
        "critical": lambda d: d[-1] == "TERMINATE",
        "prompt_injection": lambda d: d[-1] == "TERMINATE" and "BLOCK" in d,
        "excessive_api": lambda d: "BLOCK" in d and d[-1] == "TERMINATE",
        "repeated_failures": lambda d: d[-1] == "REQUIRE_APPROVAL",
        "drift": lambda d: d[-1] == "REQUIRE_APPROVAL",
        "approval": lambda d: d[-1] == "REQUIRE_APPROVAL",
        "legit_unusual": lambda d: not {"BLOCK", "TERMINATE", "REQUIRE_APPROVAL"} & set(d),
        "recovery_failure": lambda d: d[-1] == "TERMINATE",
    }
    from backend.app.database.db import reset_db
    for key, check in expect.items():
        reset_db()                       # isolate: accumulated low trust would (correctly) tighten enforcement
        baseline.clear_cache()
        sandbox.ensure_baseline(db)
        simulator.ensure_all_agents(db)
        r = simulator.run_sync(db, key)
        d = decisions(db, r["session_id"])
        assert check(d), f"{key}: unexpected decisions {d}"
    assert set(expect) == {k for k in scen.SCENARIOS if k != "judge_flagship"}


def test_terminated_agent_never_attempts_the_remaining_steps(db):
    r = simulator.run_sync(db, "critical")
    sess = db.get(Session_, r["session_id"])
    assert sess.cursor == 3 and len(json.loads(sess.plan_json)) == 4         # DELETE_DATABASE prevented
    assert sandbox.snapshot(db)["db/primary"] == "HEALTHY"
    assert "DELETE_DATABASE" not in [a.action_type for a in actions(db, sess.id)]


def test_blocked_actions_never_reach_the_environment(db):
    simulator.run_sync(db, "unauthorized_file")
    simulator.run_sync(db, "sensitive_data")
    assert sandbox.verify(db)["verified"]


def test_full_audit_story_for_the_flagship_incident(db):
    r = simulator.run_sync(db, "priv_escalation")
    for ev in ("AGENT_STARTED", "TASK_STARTED", "ACTION_EXECUTED", "ANOMALY_DETECTED", "POLICY_VIOLATION",
               "SEQUENCE_PATTERN_DETECTED", "PRIVILEGE_ESCALATION_DETECTED", "RISK_CALCULATED", "ACTION_BLOCKED",
               "INCIDENT_CREATED", "AGENT_PAUSED", "RECOVERY_STARTED", "RECOVERY_STEP", "RECOVERY_VERIFIED",
               "INCIDENT_RESOLVED", "TRUST_CHANGED"):
        assert ev in audit_types(db, r["session_id"]), ev


def test_every_action_has_an_intervention_and_a_risk_assessment(db):
    simulator.run_sync(db, "critical")
    assert db.query(Intervention).count() == db.query(Action).count()


def test_incident_is_one_per_session_and_escalates_in_place(db):
    r = simulator.run_sync(db, "excessive_api")
    incs = db.query(Incident).filter(Incident.session_id == r["session_id"]).all()
    assert len(incs) == 1


# ----------------------------------------------------------- prompt injection
def test_injection_is_detected_tainted_and_audited(db):
    r = simulator.run_sync(db, "prompt_injection")
    sess = db.get(Session_, r["session_id"])
    assert sess.tainted and "INJECTION_INDICATOR_DETECTED" in audit_types(db, sess.id)
    assert sandbox.snapshot(db)["customers/records"] == "HEALTHY"
    assert sess.status in ("STOPPED", "PAUSED")


# ------------------------------------------------------- caller cannot cheat
def test_pipeline_rebuilds_context_from_the_database(db):
    """evaluate_action has no prev_action / task_relevance parameter to lie with."""
    import inspect
    from backend.app.services.pipeline import evaluate_action
    params = set(inspect.signature(evaluate_action).parameters)
    assert "prev_action" not in params and "task_relevance" not in params


# ----------------------------------------------------------------- recovery
def _drill(db):
    """Damage that slipped past the guard, then a recoverable incident."""
    r = simulator.run_sync(db, "recovery_failure")           # auto-recover with fault=partial
    inc = db.query(Incident).filter(Incident.session_id == r["session_id"]).one()
    return r, inc


def test_recovery_partial_then_retry_succeeds(db):
    r, inc = _drill(db)
    assert r["recovery"]["outcome"] == "PARTIAL" and inc.status == "RECOVERY_PARTIAL"
    assert not sandbox.verify(db)["verified"]
    steps = {s["step"]: s["status"] for s in r["recovery"]["steps"]}
    assert steps["RESTORE_RESOURCES"] == "PARTIAL" and steps["INTEGRITY_VERIFICATION"] == "FAILED"
    retry = recovery.run_recovery(db, inc)                    # no fault this time
    assert retry["outcome"] == "SUCCESS" and retry["attempt"] == 2
    db.refresh(inc)
    assert inc.status == "RESOLVED" and sandbox.verify(db)["verified"]


def test_recovery_reports_unrecallable_exfiltration(db):
    r, inc = _drill(db)
    assert any("left the environment" in x for x in r["recovery"]["residual_risk"])


@pytest.mark.parametrize("fault,expected", [("restore_failure", {"PARTIAL", "FAILED"}), ("partial", {"PARTIAL"}),
                                            ("corruption", {"PARTIAL", "FAILED"})])
def test_every_fault_mode_is_reported_honestly(db, fault, expected):
    r = simulator.run_sync(db, "priv_escalation")            # provides a (resolved) incident to attach to
    inc = db.query(Incident).first()
    for eff in ("DELETE_DATABASE", "MODIFY_PERMISSION", "EXPORT_DATA"):
        sandbox.apply_effect(db, eff)
    out = recovery.run_recovery(db, inc, fault=fault)
    assert out["outcome"] in expected and not out["verified"]


def test_corruption_is_caught_by_the_integrity_check_not_the_state_string(db):
    simulator.run_sync(db, "critical")
    inc = db.query(Incident).first()
    sandbox.apply_effect(db, "EXPORT_DATA")
    out = recovery.run_recovery(db, inc, fault="corruption")
    bad = [c for c in out["verification"]["failed_checks"] if c["state_ok"] and not c["integrity_ok"]]
    assert bad, "a resource that LOOKS healthy but is corrupted must fail verification"


def test_verification_reports_failure_when_world_is_broken(db):
    sandbox.apply_effect(db, "DELETE_DATABASE")
    v = sandbox.verify(db)
    assert not v["verified"] and {c["resource"] for c in v["failed_checks"]} >= {"db/primary", "infra/service/web-01"}
    sandbox.restore(db)
    assert sandbox.verify(db)["verified"]


def test_unknown_fault_is_rejected(db):
    r = simulator.run_sync(db, "critical")
    inc = db.query(Incident).first()
    with pytest.raises(ValueError):
        recovery.run_recovery(db, inc, fault="meteor")


# ---------------------------------------------------------------- approvals
def test_approval_carries_evidence_impact_and_alternative(db):
    r = simulator.run_sync(db, "approval")
    ap = db.query(Approval).one()
    d = approvals.to_dict(ap)
    assert d["evidence"]["top_risk_factors"] and d["impact"]["allow"]["resources_impacted"]
    assert d["alternative"]["action"] == "SCALE_SIMULATED_SERVICE"
    assert ap.status == "PENDING" and db.get(Session_, r["session_id"]).status == "AWAITING_APPROVAL"
    assert sandbox.snapshot(db)["db/primary"] == "HEALTHY"           # nothing executed while pending


def test_request_more_evidence_appends_a_real_round(db):
    simulator.run_sync(db, "approval")
    ap = db.query(Approval).one()
    out = approvals.request_more_evidence(db, ap.id, "judge")
    assert out["evidence_rounds"] == 1 and out["status"] == "PENDING"
    findings = out["evidence"]["rounds"][0]["findings"]
    assert any("probe" in f["source"].lower() for f in findings) and any(f["source"] == "Precedent" for f in findings)
    assert "EVIDENCE_REQUESTED" in {e.event_type for e in db.query(AuditEvent)}
    for _ in range(2):
        approvals.request_more_evidence(db, ap.id, "judge")
    with pytest.raises(approvals.ApprovalError):
        approvals.request_more_evidence(db, ap.id, "judge")          # capped at three rounds


def test_approve_executes_resumes_and_is_audited(db):
    r = simulator.run_sync(db, "approval", approve=True, decided_by="judge")
    ap = db.query(Approval).one()
    assert ap.status == "APPROVED" and ap.decided_by == "judge"
    assert sandbox.snapshot(db)["db/primary"] == "FAILED_OVER"
    assert db.get(Session_, r["session_id"]).status == "COMPLETED"
    assert "HUMAN_APPROVAL" in audit_types(db, r["session_id"])


def test_reject_blocks_and_duplicate_decision_is_refused(db):
    r = simulator.run_sync(db, "approval", approve=False, decided_by="judge")
    ap = db.query(Approval).one()
    assert ap.status == "REJECTED" and sandbox.snapshot(db)["db/primary"] == "HEALTHY"
    with pytest.raises(approvals.ApprovalError) as e:
        approvals.decide(db, ap.id, True, "judge", schedule=False)
    assert e.value.status == 409


def test_retry_storm_asks_a_human_and_resumes_after_decision(db):
    r = simulator.run_sync(db, "repeated_failures", approve=False)
    assert db.get(Session_, r["session_id"]).status == "COMPLETED"    # resumed to the ticket step
    assert actions(db, r["session_id"])[-1].action_type == "CREATE_TICKET"


# -------------------------------------------------------------------- trust
def test_trust_is_computed_from_history_and_reacts(db):
    a = db.query(Agent).filter(Agent.name == "OpsAssist-Agent").one()
    assert trust_svc.compute(db, a.id)["score"] == 100.0
    simulator.run_sync(db, "normal")
    clean = trust_svc.compute(db, a.id)["score"]
    simulator.run_sync(db, "priv_escalation")
    after = trust_svc.compute(db, a.id)
    assert after["score"] < clean and after["components"]["incident_penalty"] < 0
    # a recovered incident costs less than an unrecovered one
    simulator.run_sync(db, "unauthorized_file")                        # incident stays OPEN
    open_score = trust_svc.compute(db, a.id)["score"]
    inc = db.query(Incident).filter(Incident.status == "OPEN").first()
    recovery.run_recovery(db, inc)
    assert trust_svc.compute(db, a.id)["score"] > open_score


def test_trust_is_per_agent(db):
    simulator.run_sync(db, "prompt_injection")
    ops = db.query(Agent).filter(Agent.name == "OpsAssist-Agent").one()
    sup = db.query(Agent).filter(Agent.name == "SupportAssist-Agent").one()
    assert trust_svc.compute(db, sup.id)["score"] < trust_svc.compute(db, ops.id)["score"] == 100.0


def test_low_trust_tightens_enforcement(db):
    """R13: a low-trust agent's medium-risk action needs a human."""
    d, matched = policy_engine.decide({"risk": 45, "trust": 30, "allowed": True, "always_block": False,
                                       "needs_approval": False, "destructive": False})
    assert d == "REQUIRE_APPROVAL" and matched[0]["id"] == "R13-APPROVAL-LOW-TRUST"
    d2, _ = policy_engine.decide({"risk": 45, "trust": 95, "allowed": True})
    assert d2 == "MONITOR"


# ----------------------------------------------------------------- baseline
def test_clean_session_is_learned_and_versioned(db):
    a = db.query(Agent).filter(Agent.name == "OpsAssist-Agent").one()
    v0 = baseline.active_fingerprint(db, a).version
    r = simulator.run_sync(db, "normal")
    assert db.query(AuditEvent).filter(AuditEvent.event_type == "BASELINE_UPDATED").count() == 1
    assert baseline.active_fingerprint(db, a).version == v0 + 1
    assert [b["version"] for b in baseline.history(db, a.id)] == [1, 2]
    assert sum(1 for b in baseline.history(db, a.id) if b["active"]) == 1


@pytest.mark.parametrize("key", ["unauthorized_file", "priv_escalation", "prompt_injection", "drift",
                                 "excessive_api", "critical"])
def test_suspicious_sessions_are_never_learned_as_normal(db, key):
    agent_name = scen.SCENARIOS[key].agent
    a = db.query(Agent).filter(Agent.name == agent_name).one()
    v0 = baseline.active_fingerprint(db, a).version
    r = simulator.run_sync(db, key)
    assert baseline.active_fingerprint(db, a).version == v0
    rej = db.query(AuditEvent).filter(AuditEvent.event_type == "BASELINE_UPDATE_REJECTED").all()
    assert not db.query(AuditEvent).filter(AuditEvent.event_type == "BASELINE_UPDATED").count()
    if key != "drift":     # a session held for approval never reaches the learning step
        assert rej and "Not learned as normal" in rej[-1].reason


def test_slow_poisoning_is_stopped_by_the_anchor_limit(db):
    """Each poisoned session is individually tiny; the anchor limit stops the cumulative walk."""
    cfg = policy_engine.policy["baseline"]
    anchor = baseline.detector.bootstrap_fingerprint("OpsAssist-Agent")
    from backend.app.agent.catalog import get_spec, permission_value

    def st(a, dt=0.7):
        s = get_spec(a)
        return StepRec(a, dt, permission_value(s.permission_level), s.resource_sensitivity, s.resource, s.tool_name, 0.85)

    poison = [st(a) for a in ["READ_LOG", "QUERY_METRICS_API"] * 4]       # sanctioned actions, scraping cadence
    cur, accepted, stopped_at = anchor, 0, None
    for i in range(400):
        chk = baseline.check_candidate(cur, anchor, [poison], cfg)
        if chk["reasons"]:
            stopped_at = i
            break
        cur, accepted = chk["candidate"], accepted + 1
    assert stopped_at is not None and accepted >= 1, "poisoning must be possible in small steps yet eventually blocked"
    assert anchor.divergence(cur) <= cfg["max_anchor_divergence"]


def test_adaptive_baseline_actually_moves(db):
    """Guards against the earlier bug where the bootstrap fingerprint was immovable.

    A legitimately different pattern (capacity planning) is learned repeatedly; the
    rescaled baseline must move measurably, and much more than the raw 12,000-action
    fingerprint would.
    """
    from backend.app.agent.catalog import get_spec, permission_value
    from backend.ml.replay import EFFECTIVE_ACTIONS

    def st(a, dt=6.0):
        s = get_spec(a)
        return StepRec(a, dt, permission_value(s.permission_level), s.resource_sensitivity, s.resource, s.tool_name, 0.9)

    session = [st(a) for a in ["QUERY_METRICS_API", "SCALE_SIMULATED_SERVICE", "CHECK_SERVICE_STATUS", "CREATE_TICKET"]]
    anchor = baseline.detector.bootstrap_fingerprint("OpsAssist-Agent")
    assert anchor.n_actions <= EFFECTIVE_ACTIONS + 1
    cur = anchor
    for _ in range(20):
        cur = cur.updated([session], decay=policy_engine.policy["baseline"]["decay"])
    moved = anchor.divergence(cur)
    assert moved > 0.005, moved
    # and the same 20 updates would barely register on an un-rescaled, 12k-action baseline
    heavy = anchor
    heavy.n_actions = 12000.0
    for k in ("action", "tool", "prefix", "tri"):
        d = getattr(heavy, k)
        for key in list(d):
            d[key] = d[key] * 15.0
    heavy.trans = type(heavy.trans)(heavy.trans.default_factory, {k: type(v)(float, {a: c * 15.0 for a, c in v.items()}) for k, v in heavy.trans.items()})
    cur_h = heavy
    for _ in range(20):
        cur_h = cur_h.updated([session], decay=1.0)
    assert heavy.divergence(cur_h) < moved / 3


# ------------------------------------------------------------------ misc
def test_metrics_are_computed_from_records(db):
    from backend.app.services import metrics
    simulator.run_sync(db, "normal")
    simulator.run_sync(db, "critical")
    m = metrics.compute(db)
    assert m["total_actions"] == db.query(Action).count()
    assert m["normal_actions"] + m["suspicious_actions"] == m["total_actions"]
    assert m["recovery_success_rate"] == 100.0 and m["blocked_actions"] >= 2
    assert {a["name"] for a in m["agents"]} == {"OpsAssist-Agent", "SupportAssist-Agent"}
    assert m["latency_ms"]["total"] > 0


def test_graph_highlights_the_suspicious_path(db):
    from backend.app.services import graph
    r = simulator.run_sync(db, "multi_step")
    g = graph.session_graph(db, r["session_id"])
    kinds = {n["kind"] for n in g["nodes"]}
    assert kinds == {"agent", "task", "action", "tool", "resource", "permission"}
    sus = [n["label"] for n in g["nodes"] if n["kind"] == "action" and n["suspicious"]]
    assert "ACCESS_CREDENTIAL_STORE" in sus and "MODIFY_PERMISSION" in sus and "READ_LOG" in sus
    assert g["suspicious_path"] and any(e["suspicious"] for e in g["edges"])


def test_incident_replay_reconstructs_agent_and_environment_state(db):
    from backend.app.services import graph
    r = simulator.run_sync(db, "recovery_failure")
    inc = db.query(Incident).one()
    rp = graph.incident_replay(db, inc)
    types = [f["event_type"] for f in rp["frames"]]
    assert types[0] == "AGENT_STARTED" and "AGENT_PAUSED" in types and "RECOVERY_STEP" in types
    assert [f["t"] for f in rp["frames"]] == sorted(f["t"] for f in rp["frames"])
    statuses = [f["agent_status"] for f in rp["frames"]]
    assert "SUSPICIOUS" in statuses and "PAUSED" in statuses
    damaged = [f for f in rp["frames"] if f["environment"].get("iam/role-bindings") == "ESCALATED"]
    assert damaged, "replay must show the environment being damaged"


# ---------------------------------------------------------------- judge mode
def test_judge_mode_runs_the_whole_story_and_is_repeatable(db, monkeypatch):
    """The scripted demo drives the REAL pipeline: same outcomes every run, sleeps patched out."""
    import asyncio
    from backend.app.services import demo, events, recovery as rec_mod

    async def no_sleep(_):
        return None

    monkeypatch.setattr(demo.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(rec_mod.time, "sleep", lambda _s: None)

    seen = []
    real_publish = events.hub.publish

    def capture(event_type, payload=None):
        seen.append((event_type, payload or {}))
        return real_publish(event_type, payload)

    monkeypatch.setattr(events.hub, "publish", capture)

    outcomes = []
    for _ in range(2):
        seen.clear()
        demo.reset()
        asyncio.run(demo.run())
        stage_idx = [d["index"] for t, d in seen if t == "demo_stage"]
        assert stage_idx == list(range(7))
        assert any(t == "demo_finished" for t, _ in seen)

        scenarios = [s.scenario for s in db.query(Session_).order_by(Session_.started_at)][-4:]
        assert scenarios == ["normal", "legit_unusual", "judge_flagship", "recovery_failure"]
        flagship, drill = (db.query(Session_).filter(Session_.scenario == k).order_by(Session_.started_at.desc()).first()
                           for k in ("judge_flagship", "recovery_failure"))
        db.expire_all()
        f_inc = db.query(Incident).filter(Incident.session_id == flagship.id).one()
        d_inc = db.query(Incident).filter(Incident.session_id == drill.id).one()
        legit = [a.decision for a in actions(db, db.query(Session_).filter(Session_.scenario == "legit_unusual")
                                              .order_by(Session_.started_at.desc()).first().id)]
        outcomes.append((decisions(db, flagship.id), f_inc.status, d_inc.status, d_inc.recovery_attempts,
                         sorted(set(legit))))
        assert not demo.STATE["running"]
    assert outcomes[0] == outcomes[1], "the demo must be repeatable"
    flag, f_status, d_status, attempts, legit = outcomes[0]
    assert flag[:3] == ["ALLOW"] * 3 and flag[-1] == "TERMINATE"
    assert f_status == "RESOLVED" and d_status == "RESOLVED" and attempts == 2      # partial, then retry
    assert not {"BLOCK", "TERMINATE", "REQUIRE_APPROVAL"} & set(legit)
