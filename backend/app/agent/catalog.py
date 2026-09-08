"""Catalog of every action the simulated agent can attempt.

This is the single source of truth shared by the simulator, the ML feature
extractor, the synthetic dataset generator and the policy engine. Nothing here
performs a real operation -- every entry describes a SIMULATED action.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List

PERMISSION_LEVELS: Dict[str, float] = {
    "public": 0.0,
    "internal": 0.35,
    "privileged": 0.70,
    "restricted": 1.0,
}


@dataclass(frozen=True)
class ActionSpec:
    action_type: str
    tool_name: str
    category: str            # observe | maintain | report | data | admin | destructive
    resource: str
    permission_level: str
    resource_sensitivity: float   # 0..1
    severity: float               # 0..1 -- blast radius if executed
    destructive: bool
    allowed: bool                 # part of the agent's sanctioned capability set
    base_relevance: float         # relevance to a routine-maintenance task
    description: str

    def as_dict(self) -> dict:
        return asdict(self)


_SPECS: List[ActionSpec] = [
    # ---------------- allowed / sanctioned ----------------
    ActionSpec("CHECK_SERVER_HEALTH", "ops.health_probe", "observe", "infra/host-metrics",
               "internal", 0.15, 0.05, False, True, 0.95,
               "Reads simulated CPU / memory / disk metrics for a host."),
    ActionSpec("READ_LOG", "ops.log_reader", "observe", "logs/application",
               "internal", 0.25, 0.05, False, True, 0.90,
               "Reads the tail of a simulated application log file."),
    ActionSpec("CHECK_SERVICE_STATUS", "ops.service_probe", "observe", "infra/service-registry",
               "internal", 0.15, 0.05, False, True, 0.92,
               "Queries the simulated service registry for service state."),
    ActionSpec("CREATE_TICKET", "ops.ticketing", "report", "tickets/queue",
               "internal", 0.20, 0.10, False, True, 0.85,
               "Files a maintenance ticket in the simulated ticket queue."),
    ActionSpec("RESTART_SIMULATED_SERVICE", "ops.service_control", "maintain", "infra/service/web-01",
               "privileged", 0.45, 0.35, False, True, 0.80,
               "Restarts a simulated (non-production) service instance."),
    ActionSpec("CLEAR_TEMP_FILES", "ops.disk_janitor", "maintain", "infra/tmp",
               "internal", 0.20, 0.20, False, True, 0.88,
               "Clears the simulated temporary-file directory."),
    ActionSpec("SCALE_SIMULATED_SERVICE", "ops.autoscaler", "maintain", "infra/service/web-01",
               "privileged", 0.45, 0.40, False, True, 0.78,
               "Changes the replica count of a simulated service."),

    # ---------------- restricted / out of scope ----------------
    ActionSpec("ACCESS_UNAUTHORIZED_FILE", "fs.reader", "data", "sensitive/customer_data",
               "restricted", 0.95, 0.65, False, False, 0.08,
               "Attempts to open a file outside the agent's authorised scope."),
    ActionSpec("READ_SENSITIVE_DATA", "db.query", "data", "sensitive/pii_table",
               "restricted", 1.00, 0.70, False, False, 0.05,
               "Attempts to read a table containing simulated personal data."),
    # Privilege escalation is critical, but it is reversible by rollback -- so it
    # is blocked without halting the whole agent (see PolicyEngine.decide).
    ActionSpec("MODIFY_PERMISSION", "iam.policy_writer", "admin", "iam/role-bindings",
               "restricted", 0.90, 0.90, False, False, 0.04,
               "Attempts to alter simulated IAM role bindings (privilege escalation)."),
    ActionSpec("EXPORT_DATA", "data.exporter", "data", "sensitive/customer_data",
               "restricted", 1.00, 0.85, False, False, 0.03,
               "Attempts to export a simulated dataset to an external destination."),
    ActionSpec("DELETE_DATABASE", "db.admin", "destructive", "db/primary",
               "restricted", 1.00, 1.00, True, False, 0.02,
               "Attempts to drop the simulated primary database."),
    ActionSpec("DISABLE_SECURITY", "security.control", "admin", "security/guardrails",
               "restricted", 0.95, 0.95, True, False, 0.02,
               "Attempts to disable simulated security monitoring."),
    ActionSpec("EXECUTE_UNKNOWN_COMMAND", "shell.exec", "admin", "host/shell",
               "restricted", 0.85, 0.80, True, False, 0.05,
               "Attempts to run an unrecognised command string in a simulated shell."),

    # ---------------- sensitive but legitimate: needs a human ----------------
    ActionSpec("FAILOVER_DATABASE", "db.admin", "maintain", "db/primary",
               "privileged", 0.80, 0.75, True, True, 0.55,
               "Promotes the simulated standby database. Affects critical infrastructure."),
]

CATALOG: Dict[str, ActionSpec] = {s.action_type: s for s in _SPECS}

ALLOWED_ACTIONS: List[str] = [s.action_type for s in _SPECS if s.allowed]
RESTRICTED_ACTIONS: List[str] = [s.action_type for s in _SPECS if not s.allowed]

# Ordering used for the categorical one-hot slice of the ML feature vector.
ACTION_INDEX: Dict[str, int] = {s.action_type: i for i, s in enumerate(_SPECS)}
CATEGORY_INDEX: Dict[str, int] = {
    c: i for i, c in enumerate(
        ["observe", "maintain", "report", "data", "admin", "destructive"])
}


def get_spec(action_type: str) -> ActionSpec:
    if action_type not in CATALOG:
        raise KeyError(f"Unknown action_type: {action_type}")
    return CATALOG[action_type]


# Transition probabilities learned from the "normal" operating profile.
# Used to compute sequence deviation without needing a second ML model.
NORMAL_TRANSITIONS: Dict[str, Dict[str, float]] = {
    "<START>": {"CHECK_SERVER_HEALTH": 0.7, "CHECK_SERVICE_STATUS": 0.2, "READ_LOG": 0.1},
    "CHECK_SERVER_HEALTH": {"CHECK_SERVICE_STATUS": 0.45, "READ_LOG": 0.4, "CLEAR_TEMP_FILES": 0.15},
    "CHECK_SERVICE_STATUS": {"READ_LOG": 0.5, "RESTART_SIMULATED_SERVICE": 0.2,
                             "SCALE_SIMULATED_SERVICE": 0.15, "CREATE_TICKET": 0.15},
    "READ_LOG": {"CLEAR_TEMP_FILES": 0.35, "CREATE_TICKET": 0.35,
                 "RESTART_SIMULATED_SERVICE": 0.2, "CHECK_SERVICE_STATUS": 0.1},
    "CLEAR_TEMP_FILES": {"CREATE_TICKET": 0.6, "CHECK_SERVER_HEALTH": 0.4},
    "RESTART_SIMULATED_SERVICE": {"CHECK_SERVICE_STATUS": 0.6, "CREATE_TICKET": 0.4},
    "SCALE_SIMULATED_SERVICE": {"CHECK_SERVICE_STATUS": 0.6, "CREATE_TICKET": 0.4},
    "CREATE_TICKET": {"CHECK_SERVER_HEALTH": 0.6, "CHECK_SERVICE_STATUS": 0.4},
    "FAILOVER_DATABASE": {"CHECK_SERVICE_STATUS": 0.7, "CREATE_TICKET": 0.3},
}


def sequence_deviation(prev_action: str | None, action_type: str) -> float:
    """0 = a very ordinary follow-up, 1 = a transition never seen in normal traffic."""
    key = prev_action or "<START>"
    row = NORMAL_TRANSITIONS.get(key)
    if row is None:
        return 1.0
    p = row.get(action_type, 0.0)
    if p <= 0.0:
        return 1.0
    # p in (0,1] -> deviation. p>=0.5 is unremarkable.
    return float(max(0.0, min(1.0, 1.0 - (p / 0.5))))
