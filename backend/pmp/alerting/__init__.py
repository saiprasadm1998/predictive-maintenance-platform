"""alerting.

Alert rules, persistence, ISA-18.2 lifecycle, shelving, priority and KPIs.

Public interface of the module (ARC-001 §4.1). Other modules may import only
what this file exports, never the module's internal files.
"""

from pmp.alerting.domain import (
    DEFAULT_SENSOR_ALERT,
    DEFAULT_SENSOR_WARNING,
    AlertRuleError,
    AlertRuleSpec,
    RuleKind,
)
from pmp.alerting.service import AlertRuleView, list_alert_rules, set_alert_rules

__all__ = [
    "DEFAULT_SENSOR_ALERT",
    "DEFAULT_SENSOR_WARNING",
    "AlertRuleError",
    "AlertRuleSpec",
    "AlertRuleView",
    "RuleKind",
    "list_alert_rules",
    "set_alert_rules",
]
