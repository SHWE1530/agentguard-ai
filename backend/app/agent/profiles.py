"""Agent identities and task types.

An agent profile carries a *bootstrap prior* over how that agent normally
sequences its actions. It is used ONCE, to generate the synthetic training
corpus from which each agent's behavioural fingerprint is learned. At runtime
the fingerprint (not this prior) is what detection uses.

A task type declares intent: which actions serve it and which resources it may
touch. Free-text tasks are mapped onto a task type by the intent module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class AgentProfile:
    name: str
    purpose: str
    domain: str                                   # ops | support
    prior: Dict[str, Dict[str, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskType:
    id: str
    domain: str
    description: str                              # TF-IDF corpus for task resolution
    expected: Dict[str, float]                    # action -> weight (how central to the task)
    scope_prefixes: List[str]                     # resources this task may touch
    session_len: Tuple[int, int] = (4, 9)


OPS_PRIOR: Dict[str, Dict[str, float]] = {
    "<START>": {"CHECK_SERVER_HEALTH": 0.65, "CHECK_SERVICE_STATUS": 0.2, "READ_LOG": 0.1,
                "QUERY_METRICS_API": 0.05},
    "CHECK_SERVER_HEALTH": {"CHECK_SERVICE_STATUS": 0.42, "READ_LOG": 0.38, "CLEAR_TEMP_FILES": 0.12,
                            "QUERY_METRICS_API": 0.08},
    "CHECK_SERVICE_STATUS": {"READ_LOG": 0.42, "RESTART_SIMULATED_SERVICE": 0.18,
                             "SCALE_SIMULATED_SERVICE": 0.14, "CREATE_TICKET": 0.14,
                             "QUERY_METRICS_API": 0.12},
    "READ_LOG": {"CLEAR_TEMP_FILES": 0.32, "CREATE_TICKET": 0.32, "RESTART_SIMULATED_SERVICE": 0.18,
                 "CHECK_SERVICE_STATUS": 0.1, "QUERY_METRICS_API": 0.08},
    "QUERY_METRICS_API": {"SCALE_SIMULATED_SERVICE": 0.35, "CHECK_SERVICE_STATUS": 0.35,
                          "CREATE_TICKET": 0.3},
    "CLEAR_TEMP_FILES": {"CREATE_TICKET": 0.58, "CHECK_SERVER_HEALTH": 0.42},
    "RESTART_SIMULATED_SERVICE": {"CHECK_SERVICE_STATUS": 0.58, "CREATE_TICKET": 0.42},
    "SCALE_SIMULATED_SERVICE": {"CHECK_SERVICE_STATUS": 0.58, "CREATE_TICKET": 0.42},
    "CREATE_TICKET": {"CHECK_SERVER_HEALTH": 0.6, "CHECK_SERVICE_STATUS": 0.4},
    "FAILOVER_DATABASE": {"CHECK_SERVICE_STATUS": 0.7, "CREATE_TICKET": 0.3},
}

SUPPORT_PRIOR: Dict[str, Dict[str, float]] = {
    "<START>": {"LOOKUP_ORDER": 0.75, "READ_SUPPORT_TICKET": 0.25},
    "READ_SUPPORT_TICKET": {"LOOKUP_ORDER": 0.7, "VERIFY_PAYMENT": 0.3},
    "LOOKUP_ORDER": {"VERIFY_PAYMENT": 0.5, "READ_CUSTOMER_RECORD": 0.3, "READ_SUPPORT_TICKET": 0.2},
    "READ_CUSTOMER_RECORD": {"VERIFY_PAYMENT": 0.55, "PROCESS_REFUND": 0.45},
    "VERIFY_PAYMENT": {"PROCESS_REFUND": 0.72, "READ_CUSTOMER_RECORD": 0.28},
    "PROCESS_REFUND": {"SEND_CONFIRMATION_EMAIL": 0.85, "CREATE_TICKET": 0.15},
    "SEND_CONFIRMATION_EMAIL": {"CREATE_TICKET": 0.5, "LOOKUP_ORDER": 0.5},
    "CREATE_TICKET": {"LOOKUP_ORDER": 1.0},
}

AGENTS: Dict[str, AgentProfile] = {
    "OpsAssist-Agent": AgentProfile(
        "OpsAssist-Agent", "Perform safe IT maintenance tasks.", "ops", OPS_PRIOR),
    "SupportAssist-Agent": AgentProfile(
        "SupportAssist-Agent", "Process customer refunds and support requests.", "support",
        SUPPORT_PRIOR),
}

_OPS_SCOPE = ["infra/", "logs/", "tickets/"]

TASK_TYPES: Dict[str, TaskType] = {
    "routine_maintenance": TaskType(
        "routine_maintenance", "ops",
        "check server health perform routine maintenance logs service status temporary files ticket",
        {"CHECK_SERVER_HEALTH": 1.0, "CHECK_SERVICE_STATUS": 1.0, "READ_LOG": 0.9,
         "CLEAR_TEMP_FILES": 0.9, "CREATE_TICKET": 0.85, "QUERY_METRICS_API": 0.6,
         "RESTART_SIMULATED_SERVICE": 0.55, "SCALE_SIMULATED_SERVICE": 0.5},
        _OPS_SCOPE),
    "temp_cleanup": TaskType(
        "temp_cleanup", "ops",
        "clean temporary server files free disk space clear temp directory",
        {"CLEAR_TEMP_FILES": 1.0, "CHECK_SERVER_HEALTH": 0.9, "CREATE_TICKET": 0.7, "READ_LOG": 0.6},
        _OPS_SCOPE, (3, 6)),
    "incident_response": TaskType(
        "incident_response", "ops",
        "respond to service latency incident restart scale service recover outage degraded web",
        {"CHECK_SERVICE_STATUS": 1.0, "RESTART_SIMULATED_SERVICE": 1.0, "SCALE_SIMULATED_SERVICE": 1.0,
         "READ_LOG": 0.9, "CHECK_SERVER_HEALTH": 0.8, "CREATE_TICKET": 0.8, "CLEAR_TEMP_FILES": 0.6,
         "QUERY_METRICS_API": 0.7},
        _OPS_SCOPE, (5, 10)),
    "capacity_planning": TaskType(
        "capacity_planning", "ops",
        "capacity planning review metrics scale service replicas load forecast",
        {"QUERY_METRICS_API": 1.0, "SCALE_SIMULATED_SERVICE": 0.9, "CHECK_SERVICE_STATUS": 0.8,
         "CHECK_SERVER_HEALTH": 0.7, "CREATE_TICKET": 0.7},
        _OPS_SCOPE, (4, 8)),
    "database_recovery": TaskType(
        "database_recovery", "ops",
        "restore database availability degraded primary database failover recovery",
        {"FAILOVER_DATABASE": 1.0, "CHECK_SERVICE_STATUS": 0.9, "CHECK_SERVER_HEALTH": 0.8,
         "READ_LOG": 0.7, "CREATE_TICKET": 0.7},
        _OPS_SCOPE + ["db/"], (3, 5)),
    "refund_processing": TaskType(
        "refund_processing", "support",
        "process refund for order customer payment verify confirmation email support ticket",
        {"LOOKUP_ORDER": 1.0, "VERIFY_PAYMENT": 1.0, "PROCESS_REFUND": 1.0, "READ_SUPPORT_TICKET": 0.8,
         "READ_CUSTOMER_RECORD": 0.7, "SEND_CONFIRMATION_EMAIL": 0.85, "CREATE_TICKET": 0.5},
        ["orders/", "payments/", "customers/4471", "tickets/", "comms/"], (4, 8)),
}


def tasks_for_domain(domain: str) -> List[TaskType]:
    return [t for t in TASK_TYPES.values() if t.domain == domain]
