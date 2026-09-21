"""Helpers that turn raw synthetic sessions into analyser inputs."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from backend.app.agent.catalog import get_spec, permission_value
from backend.app.services.analysis import SessionContext, featurize
from backend.app.services.fingerprint import Fingerprint
from backend.app.services.intent import alignment as intent_alignment, resolve_task
from backend.app.services.steps import StepRec


EFFECTIVE_ACTIONS = 800.0     # effective sample size of a bootstrap fingerprint (~115 sessions)


def raw_to_steps(session: Dict[str, Any]) -> List[StepRec]:
    """StepRecs for fingerprint learning (needs no fingerprint itself)."""
    task = resolve_task(session["task"], session["agent"])
    out = []
    for st in session["steps"]:
        spec = get_spec(st["a"])
        al, _ = intent_alignment(task, spec)
        out.append(StepRec(st["a"], st["dt"], permission_value(spec.permission_level),
                           spec.resource_sensitivity, spec.resource, spec.tool_name, al, st["f"]))
    return out


def fit_fingerprint(agent: str, sessions: List[Dict[str, Any]]) -> Fingerprint:
    """Fit on 70% of sessions, calibrate the drift reference on the other 30%, then refit on all."""
    steps = [raw_to_steps(s) for s in sessions if s["agent"] == agent]
    cut = int(len(steps) * 0.7)
    fp = Fingerprint(agent)
    for st in steps[:cut]:
        fp.observe_session(st)
    fp.calibrate_reference(steps[cut:])
    final = Fingerprint(agent)
    for st in steps:
        final.observe_session(st)
    final.ref_drift = fp.ref_drift
    return final.rescaled(EFFECTIVE_ACTIONS)


def new_context(session: Dict[str, Any], fp: Fingerprint, trust: float = 100.0) -> SessionContext:
    return SessionContext(agent=session["agent"], task=resolve_task(session["task"], session["agent"]),
                          fp=fp, trust=trust)


def session_features(session: Dict[str, Any], fp: Fingerprint) -> Tuple[List[List[float]], SessionContext]:
    ctx = new_context(session, fp)
    rows = []
    for st in session["steps"]:
        vec, step = featurize(ctx, st["a"], st["dt"], st["f"])
        ctx.history.append(step)
        rows.append(vec)
    return rows, ctx
