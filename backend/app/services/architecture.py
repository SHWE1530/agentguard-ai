"""Architecture description with LIVE statistics for each stage.

Every stage names the module that implements it and reports numbers read from
the running system (counts and measured latency), so the page is evidence of
what runs rather than a diagram of intentions. `implemented=False` entries are
explicitly future work.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.app.database.models import (
    Action, AgentBaseline, Approval, AuditEvent, Incident, RecoveryEvent, RiskAssessment,
)
from backend.app.services.ml_detector import detector
from backend.app.services.policy_engine import policy_engine


def describe(db: Session) -> Dict[str, Any]:
    actions = db.query(Action).all()
    n = len(actions)
    lat: Dict[str, List[float]] = {}
    rules: Counter = Counter()
    patterns: Counter = Counter()
    for a in actions[-400:]:
        try:
            rf = json.loads(a.risk_factors_json)
        except Exception:
            continue
        for k, v in rf.get("latency_ms", {}).items():
            lat.setdefault(k, []).append(v)
        for r in rf.get("matched_rules", [])[:1]:
            rules[r["id"]] += 1
        for p in rf.get("sequence", {}).get("patterns", []):
            patterns[p["id"]] += 1

    def ms(k: str) -> str:
        v = lat.get(k)
        return f"{sum(v) / len(v):.2f} ms" if v else "n/a"

    decisions = Counter(a.decision for a in actions)
    attempts = db.query(Incident).with_entities(Incident.recovery_attempts).all()
    outcomes = Counter(i.status for i in db.query(Incident).all())
    pol = policy_engine.policy

    stages: List[Dict[str, Any]] = [
        {"id": "agent", "name": "Agent", "module": "backend/app/services/simulator.py",
         "does": "Proposes actions toward a task. Has no authority to execute them.",
         "inputs": "Task text, scenario plan", "outputs": "Attempted action + simulated interval",
         "stat": f"{db.query(Action).count()} actions attempted", "implemented": True,
         "note": "Scripted scenarios, not a live LLM. Injection compliance is simulated."},
        {"id": "monitor", "name": "Activity monitor", "module": "backend/app/services/pipeline.py",
         "does": "Rebuilds the session context from the database for every action: history, fingerprint, trust, environment. Callers cannot supply their own context.",
         "inputs": "Attempted action", "outputs": "SessionContext",
         "stat": f"context built in {ms('context')}", "implemented": True},
        {"id": "intelligence", "name": "Behavioural intelligence", "module": "services/fingerprint.py, intent.py, sequence.py",
         "does": "Per-agent fingerprint (bigram/trigram, tools, resources, timing), drift, intent-alignment (TF-IDF), kill-chain + privilege-escalation + loop detection.",
         "inputs": "Action + session history", "outputs": "Alignment, sequence findings, drift",
         "stat": f"intent {ms('intent')} | sequence {ms('sequence')} | {db.query(AgentBaseline).count()} fingerprint version(s)",
         "implemented": True},
        {"id": "ml", "name": "ML detector", "module": "services/ml_detector.py + ml/train_model.py",
         "does": "Isolation Forest over 24 behavioural features, trained on normal sessions only; calibrated 0-1 anomaly score.",
         "inputs": "Feature vector", "outputs": "Anomaly score",
         "stat": f"inference {ms('ml')}" + ("" if detector.ready else " (MODEL NOT LOADED - heuristic fallback)"),
         "implemented": True},
        {"id": "risk", "name": "Risk engine", "module": "services/risk_engine.py",
         "does": "Fuses 8 signals into a 0-100 score with a per-factor breakdown, violation penalties and floors. Includes a counterfactual simulation of what the action would do if allowed.",
         "inputs": "Anomaly, alignment, sequence, drift, trust, counterfactual", "outputs": "Risk score + factors",
         "stat": f"risk {ms('risk')} | counterfactual {ms('counterfactual')}", "implemented": True},
        {"id": "policy", "name": "Policy engine", "module": "services/policy_engine.py + policies/agent_policy.json",
         "does": f"{len(pol['rules'])} configurable rules over identity, task, tool, resource, permission, severity, risk, trust and sequence. Most severe effect wins: ALLOW < MONITOR < REQUIRE_APPROVAL < BLOCK < TERMINATE.",
         "inputs": "Facts about the action", "outputs": "Decision + matched rule ids",
         "stat": f"policy {ms('policy')} | top rules: " + (", ".join(f"{k} x{v}" for k, v in rules.most_common(3)) or "none yet"),
         "implemented": True},
        {"id": "intervention", "name": "Intervention", "module": "services/pipeline.py + approvals.py",
         "does": "Enforces the decision before execution. Approvals carry evidence, modelled impact and a safer alternative; operators can request more evidence.",
         "inputs": "Decision", "outputs": "Allowed / blocked / held / agent halted",
         "stat": ", ".join(f"{k} {decisions.get(k, 0)}" for k in ("ALLOW", "MONITOR", "REQUIRE_APPROVAL", "BLOCK", "TERMINATE")),
         "implemented": True},
        {"id": "recovery", "name": "Recovery + verification", "module": "services/recovery.py + sandbox.py",
         "does": "Pause, revert permissions, restore resources, then independently verify state AND integrity checksum. Supports partial/failed outcomes and retry.",
         "inputs": "Incident", "outputs": "SUCCESS / PARTIAL / FAILED",
         "stat": f"{db.query(RecoveryEvent).count()} recovery steps recorded | " + ", ".join(f"{k} {v}" for k, v in outcomes.items() if k.startswith("RECOV") or k == "RESOLVED"),
         "implemented": True},
        {"id": "audit", "name": "Audit", "module": "services/audit.py",
         "does": "Append-only trail of every safety-relevant event, broadcast live over WebSocket.",
         "inputs": "All stages", "outputs": "Evidence trail",
         "stat": f"{db.query(AuditEvent).count()} events, {db.query(RiskAssessment).count()} risk assessments",
         "implemented": True},
    ]
    future = [
        {"name": "LLM reasoning-trace analysis", "why": "Inspect why the agent chose an action, not only what."},
        {"name": "Learned sequence model (HMM / transformer)", "why": "Sequence detection is currently engineered features + declared patterns."},
        {"name": "Real infrastructure adapters", "why": "Everything acts on a simulated sandbox."},
        {"name": "Multi-agent correlation", "why": "Agents are monitored independently."},
        {"name": "Authentication and tenancy", "why": "Only an optional shared API key guards write endpoints."},
    ]
    return {"stages": stages, "future_work": future,
            "decision_latency_ms": {k: round(sum(v) / len(v), 2) for k, v in lat.items()},
            "n_actions_measured": min(n, 400),
            "zero_trust": {
                "principle": "Never trust an agent simply because it is an approved agent.",
                "per_action_questions": ["Who is acting?", "What is it trying to do?", "Which resource?",
                                         "Why is it required?", "What is the risk?", "What if it fails or is allowed?"],
                "claim": "A design principle applied per action. This project does not claim conformance to any formal zero-trust standard."}}
