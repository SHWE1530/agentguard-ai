"""Pydantic request/response models -- all inbound data is validated here."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class StartSimulationRequest(BaseModel):
    scenario: str = Field(..., min_length=1, max_length=32,
                          description="Scenario key: normal | abnormal | critical | approval")


class StartAgentRequest(BaseModel):
    scenario: str = Field(default="normal", min_length=1, max_length=32)


class ApprovalDecisionRequest(BaseModel):
    decided_by: str = Field(default="operator", min_length=1, max_length=64)
    note: Optional[str] = Field(default=None, max_length=500)


class EvaluateActionRequest(BaseModel):
    """Manual single-action evaluation, used by tests and the API explorer."""
    session_id: str = Field(..., min_length=1)
    action_type: str = Field(..., min_length=1, max_length=64)
    prev_action: Optional[str] = Field(default=None, max_length=64)
    task_relevance: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class ErrorResponse(BaseModel):
    error: str
    detail: str
