"""Lightweight per-step record shared by the pure analysis modules."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StepRec:
    action: str
    dt: float                 # seconds since the previous action in the session
    permission: float         # 0..1 ordinal privilege of the action
    sensitivity: float        # 0..1 resource sensitivity
    resource: str
    tool: str
    alignment: float          # 0..1 intent alignment with the session task
    failed: bool = False
    blocked: bool = False     # the safety layer denied this attempt

    @property
    def prefix(self) -> str:
        return self.resource.split("/")[0] + "/"
