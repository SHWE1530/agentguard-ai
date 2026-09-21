from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex[:12]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, unique=True)
    purpose: Mapped[str] = mapped_column(String)
    # IDLE | RUNNING | SUSPICIOUS | PAUSED | STOPPED
    status: Mapped[str] = mapped_column(String, default="IDLE")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Session_(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    scenario: Mapped[str] = mapped_column(String)
    # RUNNING | COMPLETED | PAUSED | STOPPED | AWAITING_APPROVAL
    status: Mapped[str] = mapped_column(String, default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tainted: Mapped[bool] = mapped_column(Boolean, default=False)
    taint_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_json: Mapped[str] = mapped_column(Text, default="[]")     # remaining scenario steps
    cursor: Mapped[int] = mapped_column(Integer, default=0)         # next step to execute
    fault: Mapped[str | None] = mapped_column(String, nullable=True)  # recovery fault injection
    task: Mapped["Task"] = relationship(back_populates="session", uselist=False)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    description: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    session: Mapped[Session_] = relationship(back_populates="task")


class Action(Base):
    __tablename__ = "actions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    task_id: Mapped[str] = mapped_column(String)
    step_index: Mapped[int] = mapped_column(Integer, default=0)
    action_type: Mapped[str] = mapped_column(String, index=True)
    tool_name: Mapped[str] = mapped_column(String)
    resource: Mapped[str] = mapped_column(String)
    permission_level: Mapped[str] = mapped_column(String)
    task_relevance: Mapped[float] = mapped_column(Float)
    # ALLOWED | MONITORED | BLOCKED | PENDING_APPROVAL | APPROVED | REJECTED
    action_status: Mapped[str] = mapped_column(String)
    decision: Mapped[str] = mapped_column(String, default="ALLOW")
    interval_s: Mapped[float] = mapped_column(Float, default=3.0)
    execution_result: Mapped[str] = mapped_column(String, default="NOT_EXECUTED")  # SUCCESS|FAILED|NOT_EXECUTED
    anomaly_score: Mapped[float] = mapped_column(Float)
    risk_score: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String, index=True)
    policy_violation: Mapped[str | None] = mapped_column(String, nullable=True)
    explanation: Mapped[str] = mapped_column(Text)
    risk_factors_json: Mapped[str] = mapped_column(Text, default="{}")
    incident_id: Mapped[str | None] = mapped_column(String, nullable=True)


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    reference: Mapped[str] = mapped_column(String, unique=True)  # INC-0042
    session_id: Mapped[str] = mapped_column(String, index=True)
    agent_id: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)  # MEDIUM | HIGH | CRITICAL
    title: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)
    risk_score: Mapped[float] = mapped_column(Float)
    # OPEN | RECOVERING | RESOLVED | RECOVERY_PARTIAL | RECOVERY_FAILED
    status: Mapped[str] = mapped_column(String, default="OPEN")
    trigger_action_id: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="MISBEHAVIOR")  # MISBEHAVIOR | DRIFT
    recovery_attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    action_id: Mapped[str] = mapped_column(String, index=True)
    anomaly_score: Mapped[float] = mapped_column(Float)
    risk_score: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String)
    factors_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Intervention(Base):
    __tablename__ = "interventions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    action_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str] = mapped_column(String)
    # ALLOW | MONITOR | BLOCK | REQUIRE_APPROVAL | BLOCK_AND_STOP
    decision: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)
    agent_state_after: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    action_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str] = mapped_column(String)
    agent_id: Mapped[str] = mapped_column(String)
    action_type: Mapped[str] = mapped_column(String)
    risk_score: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="PENDING")  # PENDING | APPROVED | REJECTED
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    impact_json: Mapped[str] = mapped_column(Text, default="{}")
    alternative_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_rounds: Mapped[int] = mapped_column(Integer, default=0)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RecoveryEvent(Base):
    __tablename__ = "recovery_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    incident_id: Mapped[str] = mapped_column(String, index=True)
    recovery_action: Mapped[str] = mapped_column(String)
    previous_state: Mapped[str] = mapped_column(Text)
    restored_state: Mapped[str] = mapped_column(Text)
    # STARTED | COMPLETED | FAILED | VERIFIED | VERIFICATION_FAILED
    recovery_status: Mapped[str] = mapped_column(String)
    detail: Mapped[str] = mapped_column(Text, default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    incident_id: Mapped[str | None] = mapped_column(String, nullable=True)
    action_type: Mapped[str | None] = mapped_column(String, nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    decision: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")


class SimulatedResource(Base):
    """The sandboxed world the agent acts on. Nothing here touches the real host."""

    __tablename__ = "simulated_resources"
    name: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)  # database | service | permissions | data | security
    # HEALTHY | DEGRADED | DELETED | ESCALATED | EXFILTRATED | DISABLED
    state: Mapped[str] = mapped_column(String)
    healthy_state: Mapped[str] = mapped_column(String)  # known-good baseline
    checksum: Mapped[str] = mapped_column(String, default="")
    healthy_checksum: Mapped[str] = mapped_column(String, default="")
    content_version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    compromised: Mapped[bool] = mapped_column(Boolean, default=False)


class AgentBaseline(Base):
    """Versioned behavioural fingerprint. Only one version per agent is active."""

    __tablename__ = "agent_baselines"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String)         # bootstrap | adaptive
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    data_json: Mapped[str] = mapped_column(Text)
    anchor_divergence: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TrustSnapshot(Base):
    __tablename__ = "trust_snapshots"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    score: Mapped[float] = mapped_column(Float)
    event: Mapped[str] = mapped_column(String)
    components_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DriftSnapshot(Base):
    """Per-session behavioural drift versus the agent's fingerprint."""

    __tablename__ = "drift_snapshots"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    peak: Mapped[float] = mapped_column(Float)
    final: Mapped[float] = mapped_column(Float)
    threshold: Mapped[float] = mapped_column(Float)
    reference_mean: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
