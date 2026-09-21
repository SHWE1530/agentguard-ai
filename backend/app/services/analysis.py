"""The pure analysis engine (no database, no I/O).

    analyze(ctx, action)  ->  Analysis

runs the full detection stack for one attempted action:

  intent alignment -> sequence analysis -> ML anomaly -> drift -> policy
  invariants -> counterfactual simulation -> multi-layer risk -> rule
  decision -> explanation / zero-trust / allow-rationale

It is used unchanged by the live pipeline (pipeline.py) and by the offline
evaluator (ml/evaluate.py), so what is measured is what runs.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.app.agent.catalog import ActionSpec, get_spec, permission_value
from backend.app.services import envsim, explanation, injection
from backend.app.services.fingerprint import Fingerprint
from backend.app.services.intent import TaskProfile, alignment as intent_alignment
from backend.app.services.ml_detector import detector
from backend.app.services.policy_engine import PolicyResult, policy_engine
from backend.app.services.risk_engine import RiskAssessmentResult, assess
from backend.app.services.sequence import SequenceFindings, analyze_sequence
from backend.app.services.steps import StepRec
from backend.ml.features import as_named, build_feature_vector


@dataclass
class SessionContext:
    agent: str
    task: TaskProfile
    fp: Fingerprint
    history: List[StepRec] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=envsim.fresh_state)
    trust: float = 100.0
    tainted: bool = False
    taint_evidence: Optional[Dict[str, Any]] = None
    blocked_in_session: int = 0

    def commit(self, a: "Analysis", executed: bool) -> None:
        """Record the attempt (blocked attempts still count as attempts)."""
        step = a.step
        step.blocked = a.decision in ("BLOCK", "TERMINATE")
        self.history.append(step)
        if step.blocked:
            self.blocked_in_session += 1
        if a.injection and a.injection["tainted"]:
            self.tainted = True
            self.taint_evidence = a.injection
        if executed:
            self.env, _ = envsim.apply(self.env, a.spec.action_type)


@dataclass
class Analysis:
    agent: str
    spec: ActionSpec
    task_type: str
    step: StepRec
    history: List[StepRec]
    alignment: float
    alignment_detail: Dict[str, Any]
    in_scope: bool
    anomaly: float
    ml: Dict[str, Any]
    features: Dict[str, float]
    seq: SequenceFindings
    drift: Dict[str, float]
    drift_alert: bool
    drift_threshold: float
    policy: PolicyResult
    counterfactual: Dict[str, Any]
    risk: RiskAssessmentResult
    decision: str
    matched_rules: List[Dict[str, str]]
    trust: float
    tainted: bool
    injection: Optional[Dict[str, Any]]
    fp_version: int
    latency_ms: Dict[str, float]
    explanation: str = ""
    allow_rationale: Optional[Dict[str, Any]] = None
    zero_trust: List[Dict[str, Any]] = field(default_factory=list)
    alternative: Optional[Dict[str, str]] = None

    def payload(self) -> Dict[str, Any]:
        """JSON-serialisable analysis stored with the action and sent to the UI."""
        return {
            "factors": self.risk.factors,
            "weighted_contributions": self.risk.contributions,
            "floors": self.risk.floors,
            "intent": {"task_type": self.task_type, "alignment": round(self.alignment, 3),
                       **{k: v for k, v in self.alignment_detail.items()}},
            "sequence": self.seq.as_dict(),
            "drift": {k: round(v, 3) for k, v in self.drift.items()},
            "drift_alert": self.drift_alert,
            "drift_threshold": round(self.drift_threshold, 3),
            "policy_violations": self.policy.violations,
            "policy_details": self.policy.details,
            "matched_rules": self.matched_rules,
            "counterfactual": self.counterfactual,
            "zero_trust": self.zero_trust,
            "allow_rationale": self.allow_rationale,
            "alternative": self.alternative,
            "trust": round(self.trust, 1),
            "tainted": self.tainted,
            "injection": self.injection,
            "fingerprint_version": self.fp_version,
            "ml_source": self.ml["source"],
            "ml_raw_score": self.ml["raw_score"],
            "features": {k: round(float(v), 4) for k, v in self.features.items()},
            "latency_ms": {k: round(v, 3) for k, v in self.latency_ms.items()},
        }


def _next_actions() -> Dict[str, List[str]]:
    return {p["id"]: p.get("next_actions", []) for p in policy_engine.policy.get("sequence_patterns", [])}


def analyze(ctx: SessionContext, action_type: str, dt: float = 3.0, failed: bool = False,
            content: Optional[str] = None, anomaly_override: Optional[float] = None) -> Analysis:
    cfg = policy_engine.policy
    t0 = time.perf_counter()
    lat: Dict[str, float] = {}

    spec = get_spec(action_type)
    align, align_detail = intent_alignment(ctx.task, spec)
    step = StepRec(action=action_type, dt=dt, permission=permission_value(spec.permission_level),
                   sensitivity=spec.resource_sensitivity, resource=spec.resource, tool=spec.tool_name,
                   alignment=align, failed=failed)
    hist = ctx.history + [step]
    prev = ctx.history[-1].action if ctx.history else None
    prev2 = ctx.history[-2].action if len(ctx.history) > 1 else None
    lat["intent"] = (time.perf_counter() - t0) * 1000

    # ---- untrusted content / taint
    inj = injection.scan(content, cfg["injection"]) if content else None
    tainted = ctx.tainted or bool(inj and inj["tainted"])

    # ---- sequence
    t1 = time.perf_counter()
    seq = analyze_sequence(cfg, ctx.fp, hist, prev, prev2)
    lat["sequence"] = (time.perf_counter() - t1) * 1000

    # ---- ML
    t2 = time.perf_counter()
    vec = build_feature_vector(spec, hist, ctx.fp)
    if anomaly_override is None:
        ml = detector.score_vector(vec)
    else:
        ml = {"anomaly_score": float(anomaly_override), "raw_score": None, "source": "precomputed_batch"}
    anomaly = ml["anomaly_score"]
    lat["ml"] = (time.perf_counter() - t2) * 1000

    # ---- drift
    win = hist[-8:]
    drift = ctx.fp.drift(win)
    thr = ctx.fp.drift_threshold
    drift_alert = (not drift["insufficient"]) and len(win) >= 5 and drift["score"] >= thr
    ref = ctx.fp.ref_drift.get("mean", 0.2)
    drift_excess = max(0.0, (drift["score"] - ref) / max(1e-6, 1.0 - ref)) if not drift["insufficient"] else 0.0

    # ---- policy invariants
    t3 = time.perf_counter()
    seq_dict = seq.as_dict()
    pol = policy_engine.evaluate(ctx.agent, ctx.task, spec, align, tainted, seq_dict)
    lat["policy"] = (time.perf_counter() - t3) * 1000

    # ---- counterfactual
    t4 = time.perf_counter()
    cf = envsim.counterfactual(ctx.env, action_type, align, seq.patterns, _next_actions())
    lat["counterfactual"] = (time.perf_counter() - t4) * 1000

    # ---- risk
    t5 = time.perf_counter()
    risk = assess(spec, anomaly, align, seq, pol, ctx.trust, drift_excess, tainted,
                  cf["allow"]["impact_score"])
    lat["risk"] = (time.perf_counter() - t5) * 1000

    # ---- decision by rules
    facts = {
        "agent": ctx.agent, "task_type": ctx.task.task_type, "tool": spec.tool_name, "action": action_type,
        "resource": spec.resource, "permission": spec.permission_level,
        "severity": spec.severity, "sensitivity": spec.resource_sensitivity,
        "destructive": spec.destructive, "allowed": pol.allowed, "always_block": pol.always_block,
        "needs_approval": pol.needs_approval, "risk": risk.risk_score, "risk_level": risk.risk_level,
        "trust": ctx.trust, "drift": drift["score"], "drift_alert": drift_alert,
        "alignment": align, "anomaly": anomaly, "pattern_terminate": bool(seq.pattern_terminate),
        "privilege_escalation": bool(seq.escalation.get("detected")), "tainted": tainted,
        "loop_kind": seq.loop.get("kind"), "consecutive_failures": seq.loop.get("consecutive_failures", 0),
        "observe_streak": seq.loop.get("observe_streak", 0),
        "blocked_in_session": ctx.blocked_in_session,
    }
    decision, matched = policy_engine.decide(facts)

    a = Analysis(
        agent=ctx.agent, spec=spec, task_type=ctx.task.task_type, step=step, history=hist,
        alignment=align, alignment_detail=align_detail, in_scope=ctx.task.in_scope(spec.resource),
        anomaly=anomaly, ml=ml, features=as_named(vec), seq=seq, drift=drift, drift_alert=drift_alert,
        drift_threshold=thr, policy=pol, counterfactual=cf, risk=risk, decision=decision,
        matched_rules=matched, trust=ctx.trust, tainted=tainted, injection=inj,
        fp_version=ctx.fp.version, latency_ms=lat,
    )
    a.explanation = explanation.explain_action(a)
    a.allow_rationale = explanation.allow_rationale(a)
    a.zero_trust = explanation.zero_trust(a)
    a.alternative = policy_engine.alternative(action_type) if decision in ("BLOCK", "TERMINATE", "REQUIRE_APPROVAL") else None
    lat["total"] = (time.perf_counter() - t0) * 1000
    return a


def featurize(ctx: SessionContext, action_type: str, dt: float = 3.0, failed: bool = False):
    """Cheap path used for training and batch evaluation: features only, no decision.

    Returns (feature_vector, step). The caller appends `step` to ctx.history.
    """
    spec = get_spec(action_type)
    align, _ = intent_alignment(ctx.task, spec)
    step = StepRec(action=action_type, dt=dt, permission=permission_value(spec.permission_level),
                   sensitivity=spec.resource_sensitivity, resource=spec.resource, tool=spec.tool_name,
                   alignment=align, failed=failed)
    return build_feature_vector(spec, ctx.history + [step], ctx.fp), step
