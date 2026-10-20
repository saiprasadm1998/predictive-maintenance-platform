"""alerting.

Alert rules, persistence, ISA-18.2 lifecycle, shelving, priority and KPIs.

Public interface of the module (ARC-001 §4.1). Other modules may import only
what this file exports, never the module's internal files.
"""

from pmp.alerting.alerts import (
    MAX_SHELVE,
    AlertChanged,
    AlertView,
    acknowledge,
    active_sensor_alerts,
    alert_history,
    evaluate_cycle,
    expire_shelves,
    get_alert,
    get_priority_matrix,
    list_alerts,
    rule_states,
    set_priority,
    shelve,
    sync_out_of_service,
    unshelve,
)
from pmp.alerting.domain import (
    DEFAULT_SENSOR_ALERT,
    DEFAULT_SENSOR_WARNING,
    AlertRuleError,
    AlertRuleSpec,
    RuleKind,
)
from pmp.alerting.engine import AlertError, AlertState, Severity, replay
from pmp.alerting.service import (
    AlertRuleView,
    list_alert_rules,
    require_di_rule,
    set_alert_rules,
)

__all__ = [
    "DEFAULT_SENSOR_ALERT",
    "DEFAULT_SENSOR_WARNING",
    "MAX_SHELVE",
    "AlertChanged",
    "AlertError",
    "AlertRuleError",
    "AlertRuleSpec",
    "AlertRuleView",
    "AlertState",
    "AlertView",
    "RuleKind",
    "Severity",
    "acknowledge",
    "active_sensor_alerts",
    "alert_history",
    "evaluate_cycle",
    "expire_shelves",
    "get_alert",
    "get_priority_matrix",
    "list_alert_rules",
    "list_alerts",
    "replay",
    "require_di_rule",
    "rule_states",
    "set_alert_rules",
    "set_priority",
    "shelve",
    "sync_out_of_service",
    "unshelve",
]
