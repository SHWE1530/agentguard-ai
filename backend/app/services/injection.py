"""Untrusted-content scanning and session taint.

When the agent ingests content it did not author (a support ticket, a web
page, a tool result), that content may carry instructions aimed at the agent.
This module scans such content for injection INDICATORS (declared in the
policy file) and, above a threshold, marks the session TAINTED.

A tainted session changes downstream decisions: an action that then departs
from the task is blocked (rule R07). Detection of the *behavioural* effect --
intent misalignment, sequence patterns, drift -- does not depend on the scan,
so an injection the regexes miss is still caught by what the agent does next.

This is a defensive heuristic scan over SIMULATED content. It is not a
general prompt-injection classifier and makes no such claim.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Dict, List


@lru_cache(maxsize=8)
def _compiled(key: str, patterns: tuple) -> List[tuple]:
    return [(label, re.compile(rx, re.IGNORECASE), w) for label, rx, w in patterns]


def scan(content: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    inds = cfg.get("indicators", [])
    comp = _compiled("inj", tuple((i["label"], i["regex"], i["weight"]) for i in inds))
    hits = []
    score = 0.0
    for label, rx, w in comp:
        m = rx.search(content or "")
        if m:
            hits.append({"label": label, "match": m.group(0)[:80], "weight": w})
            score += w
    score = min(1.0, score)
    return {"score": round(score, 2), "tainted": score >= cfg.get("threshold", 0.5), "indicators": hits}
