"""Pydantic request models -- all inbound data is validated here."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class StartSimulationRequest(BaseModel):
    scenario: str = Field(..., min_length=1, max_length=40, description="Scenario key from GET /api/scenarios")


class StartAgentRequest(BaseModel):
    scenario: str = Field(default="normal", min_length=1, max_length=40)


class ApprovalDecisionRequest(BaseModel):
    decided_by: str = Field(default="operator", min_length=1, max_length=64)
    note: Optional[str] = Field(default=None, max_length=500)


class EvaluateActionRequest(BaseModel):
    """Manual single-action evaluation for testing.

    Deliberately NO `prev_action` and NO `task_relevance`: the pipeline derives
    history and intent from the database, so a caller cannot lower its own score
    by misreporting context.
    """
    session_id: str = Field(..., min_length=1, max_length=64)
    action_type: str = Field(..., min_length=1, max_length=64)
    dt: float = Field(default=3.0, ge=0.0, le=3600.0, description="simulated seconds since the previous action")
    failed: bool = False
    content: Optional[str] = Field(default=None, max_length=4000, description="untrusted text the agent just read")


class RecoverRequest(BaseModel):
    fault: Optional[str] = Field(default=None, max_length=32,
                                 description="Fault injection: restore_failure | partial | corruption")


class BaselineUpdateRequest(BaseModel):
    session_id: Optional[str] = Field(default=None, max_length=64)


class ErrorResponse(BaseModel):
    error: str
    detail: str


class OpenSessionRequest(BaseModel):
    """Open a monitored session for an EXTERNAL agent (no scenario script)."""
    agent_name: str = Field(..., min_length=1, max_length=64, description="Must exist in policies/agent_policy.json")
    task: str = Field(..., min_length=3, max_length=500, description="Free-text task; resolved to a task type")
