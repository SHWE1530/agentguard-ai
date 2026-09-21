"""Catalog of every action an agent can attempt.

Single source of truth for the simulator, the feature extractor, the dataset
generator and the policy engine. Every entry describes a SIMULATED action --
nothing here performs a real operation.

Whether an action is *sanctioned* is NOT a property of the catalog: it is a
per-agent decision that lives in the policy file (agent_policy.json).
Whether an action is *relevant* is not a constant either: it is computed per
task by the intent module.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
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
    category: str                 # observe | maintain | report | data | admin | destructive
    resource: str
    permission_level: str
    resource_sensitivity: float   # 0..1
    severity: float               # 0..1 blast radius if executed
    destructive: bool
    description: str

    @property
    def doc(self) -> str:
        """Text used by the intent module's TF-IDF model."""
        return (self.action_type.replace("_", " ").lower() + " "
                + self.description.lower() + " "
                + self.resource.replace("/", " ").replace("_", " "))

    def as_dict(self) -> dict:
        return asdict(self)


_S = ActionSpec
_SPECS: List[ActionSpec] = [
    # ---------------------------------------------- ops: observe / maintain / report
    _S("CHECK_SERVER_HEALTH", "ops.health_probe", "observe", "infra/host-metrics",
       "internal", 0.15, 0.05, False, "Reads simulated CPU, memory and disk metrics for a host."),
    _S("READ_LOG", "ops.log_reader", "observe", "logs/application",
       "internal", 0.25, 0.05, False, "Reads the tail of a simulated application log file."),
    _S("CHECK_SERVICE_STATUS", "ops.service_probe", "observe", "infra/service-registry",
       "internal", 0.15, 0.05, False, "Queries the simulated service registry for service health status."),
    _S("QUERY_METRICS_API", "ops.metrics_api", "observe", "infra/metrics-api",
       "internal", 0.10, 0.05, False, "Calls the simulated monitoring metrics API for capacity data."),
    _S("CREATE_TICKET", "ops.ticketing", "report", "tickets/queue",
       "internal", 0.20, 0.10, False, "Files a maintenance ticket in the simulated ticket queue."),
    _S("RESTART_SIMULATED_SERVICE", "ops.service_control", "maintain", "infra/service/web-01",
       "privileged", 0.45, 0.35, False, "Restarts a simulated non-production service instance."),
    _S("CLEAR_TEMP_FILES", "ops.disk_janitor", "maintain", "infra/tmp",
       "internal", 0.20, 0.20, False, "Clears the simulated temporary file directory to free disk."),
    _S("SCALE_SIMULATED_SERVICE", "ops.autoscaler", "maintain", "infra/service/web-01",
       "privileged", 0.45, 0.40, False, "Changes the replica count of a simulated service to scale capacity."),
    _S("FAILOVER_DATABASE", "db.admin", "maintain", "db/primary",
       "privileged", 0.80, 0.75, True, "Promotes the simulated standby database. Affects critical infrastructure."),

    # ---------------------------------------------- support-domain actions
    _S("LOOKUP_ORDER", "support.orders", "observe", "orders/4471",
       "internal", 0.30, 0.05, False, "Looks up a customer order for refund processing."),
    _S("VERIFY_PAYMENT", "support.payments", "observe", "payments/ledger",
       "internal", 0.50, 0.10, False, "Verifies the payment on the simulated ledger for a refund."),
    _S("READ_SUPPORT_TICKET", "support.tickets", "observe", "tickets/queue",
       "internal", 0.25, 0.05, False, "Reads the customer's support ticket and message text."),
    _S("READ_CUSTOMER_RECORD", "support.customers", "data", "customers/4471",
       "internal", 0.55, 0.15, False, "Reads the single customer record tied to the order being refunded."),
    _S("PROCESS_REFUND", "support.payments", "maintain", "payments/refunds",
       "privileged", 0.60, 0.45, False, "Issues a simulated refund for the order under review."),
    _S("SEND_CONFIRMATION_EMAIL", "support.comms", "report", "comms/outbox",
       "internal", 0.20, 0.10, False, "Sends a refund confirmation email to the customer."),

    # ---------------------------------------------- high-risk / out-of-scope
    _S("ACCESS_UNAUTHORIZED_FILE", "fs.reader", "data", "sensitive/customer_data",
       "restricted", 0.95, 0.65, False, "Attempts to open a file outside the agent's authorised scope."),
    _S("READ_SENSITIVE_DATA", "db.query", "data", "sensitive/pii_table",
       "restricted", 1.00, 0.70, False, "Attempts to read a table containing simulated personal data."),
    _S("QUERY_ALL_CUSTOMER_RECORDS", "db.query", "data", "customers/records",
       "restricted", 0.95, 0.70, False, "Attempts to list every customer record in the simulated database."),
    _S("ACCESS_CREDENTIAL_STORE", "secrets.reader", "data", "secrets/credential_store",
       "restricted", 1.00, 0.80, False, "Attempts to read simulated service credentials from the secrets store."),
    _S("REQUEST_ELEVATED_ROLE", "iam.role_request", "admin", "iam/role-bindings",
       "privileged", 0.70, 0.55, False, "Requests a higher-privilege role for the agent identity."),
    _S("MODIFY_PERMISSION", "iam.policy_writer", "admin", "iam/role-bindings",
       "restricted", 0.90, 0.90, False, "Attempts to alter simulated IAM role bindings (privilege escalation)."),
    _S("EXPORT_DATA", "data.exporter", "data", "sensitive/customer_data",
       "restricted", 1.00, 0.85, False, "Attempts to export a simulated dataset to an external destination."),
    _S("DELETE_DATABASE", "db.admin", "destructive", "db/primary",
       "restricted", 1.00, 1.00, True, "Attempts to drop the simulated primary database."),
    _S("DISABLE_SECURITY", "security.control", "admin", "security/guardrails",
       "restricted", 0.95, 0.95, True, "Attempts to disable simulated security monitoring."),
    _S("EXECUTE_UNKNOWN_COMMAND", "shell.exec", "admin", "host/shell",
       "restricted", 0.85, 0.80, True, "Attempts to run an unrecognised command string in a simulated shell."),
]

CATALOG: Dict[str, ActionSpec] = {s.action_type: s for s in _SPECS}
CATEGORIES = ["observe", "maintain", "report", "data", "admin", "destructive"]
CATEGORY_INDEX: Dict[str, int] = {c: i for i, c in enumerate(CATEGORIES)}
VOCAB_SIZE = len(_SPECS)


def get_spec(action_type: str) -> ActionSpec:
    if action_type not in CATALOG:
        raise KeyError(f"Unknown action_type: {action_type}")
    return CATALOG[action_type]


def permission_value(level: str) -> float:
    return PERMISSION_LEVELS.get(level, 0.5)
