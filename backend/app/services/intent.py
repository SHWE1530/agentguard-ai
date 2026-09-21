"""Intent-behaviour alignment.

The agent is given a free-text task. Two things are computed from it:

1. TASK RESOLUTION  -- a TF-IDF nearest-neighbour match maps the text onto a
   declared task type, which fixes the *expected actions* and the *resource
   scope* for that kind of work.
2. ACTION ALIGNMENT -- every attempted action is scored 0..1 against that
   intent. Expected actions score high; in-scope-but-unplanned actions score
   in the middle; out-of-scope actions score near zero.

    alignment = 0.70 + 0.20*weight + 0.10*semantic     (expected action)
              = 0.30 + 0.25*semantic                    (in scope, not planned)
              = 0.08 * semantic                         (out of scope)

`semantic` is the TF-IDF cosine between the task text and the action's own
description, so wording matters even for actions the task profile did not
anticipate. The result replaces the old hard-coded per-action relevance
constant: the same action (READ_CUSTOMER_RECORD) is aligned for a refund and
misaligned for server maintenance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from backend.app.agent.catalog import ActionSpec, CATALOG
from backend.app.agent.profiles import AGENTS, TASK_TYPES, TaskType, tasks_for_domain


@dataclass
class TaskProfile:
    text: str
    task_type: str
    confidence: float
    expected: Dict[str, float]
    scope_prefixes: List[str]
    description: str = ""

    def in_scope(self, resource: str) -> bool:
        return any(resource.startswith(p) for p in self.scope_prefixes)


class _Model:
    def __init__(self) -> None:
        self.action_names: List[str] = list(CATALOG)
        docs = [CATALOG[a].doc for a in self.action_names] + [t.description for t in TASK_TYPES.values()]
        self.vec = TfidfVectorizer(stop_words="english", sublinear_tf=True, ngram_range=(1, 1))
        self.vec.fit(docs)
        self.action_mat = self.vec.transform([CATALOG[a].doc for a in self.action_names])
        self.action_idx = {a: i for i, a in enumerate(self.action_names)}
        self._cache: Dict[tuple, float] = {}

    def cos_task_types(self, text: str, types: List[TaskType]) -> np.ndarray:
        q = self.vec.transform([text])
        m = self.vec.transform([t.description for t in types])
        return (m @ q.T).toarray().ravel()

    def cos_action(self, text: str, action: str) -> float:
        key = (text, action)
        hit = self._cache.get(key)
        if hit is None:
            q = self.vec.transform([text])
            hit = float((self.action_mat[self.action_idx[action]] @ q.T).toarray()[0, 0])
            self._cache[key] = hit
        return hit


@lru_cache(maxsize=1)
def _model() -> _Model:
    return _Model()


@lru_cache(maxsize=512)
def resolve_task(text: str, agent_name: str) -> TaskProfile:
    profile = AGENTS.get(agent_name)
    domain = profile.domain if profile else "ops"
    types = tasks_for_domain(domain)
    sims = _model().cos_task_types(text, types)
    best = int(np.argmax(sims))
    t = types[best]
    conf = float(sims[best])
    return TaskProfile(text=text, task_type=t.id, confidence=round(conf, 3),
                       expected=dict(t.expected), scope_prefixes=list(t.scope_prefixes),
                       description=t.description)


def alignment(task: TaskProfile, spec: ActionSpec) -> Tuple[float, Dict[str, float]]:
    """Return (score 0..1, components)."""
    sem = _model().cos_action(task.text + " " + task.description, spec.action_type)
    sem_n = min(1.0, sem / 0.35)
    weight = task.expected.get(spec.action_type)
    in_scope = task.in_scope(spec.resource)
    if weight is not None:
        score = 0.70 + 0.20 * weight + 0.10 * sem_n
        kind = "expected_by_task"
    elif in_scope:
        score = 0.30 + 0.25 * sem_n
        kind = "in_scope_unplanned"
    else:
        score = 0.08 * sem_n
        kind = "out_of_scope"
    score = float(max(0.0, min(1.0, score)))
    return score, {"semantic": round(sem_n, 3), "in_scope": float(in_scope),
                   "expected_weight": float(weight or 0.0), "kind": kind}  # type: ignore[dict-item]
