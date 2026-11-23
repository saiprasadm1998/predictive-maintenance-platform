"""notifications.

Subscriptions, throttling, e-mail and webhook delivery, and digests.

Public interface of the module (ARC-001 §4.1). Other modules may import only
what this file exports, never the module's internal files.
"""

from pmp.core import RetainedRecords
from pmp.notifications.domain import (
    HISTORY_LAG,
    PER_ALERT,
    PER_HOUR,
    SUBSCRIBABLE,
    Decision,
    EventKind,
    NotificationError,
    Status,
    SubscriptionSpec,
    decide,
    in_quiet_hours,
    is_history,
    matches,
    next_attempt,
    priority_reaches,
)
from pmp.notifications.runner import Notifier, PassResult
from pmp.notifications.service import (
    NotificationView,
    Preferences,
    Recipient,
    Sender,
    SmtpSender,
    SubscriptionView,
    collect_alerts,
    collect_cases,
    collect_overdue,
    configure_tuning,
    delete_subscription,
    deliver,
    get_preferences,
    list_deliveries,
    list_subscriptions,
    recipients,
    save_subscription,
    send_digests,
    send_test,
    set_quiet_hours,
    summarise,
)

# The delivery log past its period.
NOTIFICATION_RECORDS = RetainedRecords("notifications", "notification_log", "created_at")

__all__ = [
    "HISTORY_LAG",
    "NOTIFICATION_RECORDS",
    "PER_ALERT",
    "PER_HOUR",
    "SUBSCRIBABLE",
    "Decision",
    "EventKind",
    "NotificationError",
    "NotificationView",
    "Notifier",
    "PassResult",
    "Preferences",
    "Recipient",
    "Sender",
    "SmtpSender",
    "Status",
    "SubscriptionSpec",
    "SubscriptionView",
    "collect_alerts",
    "collect_cases",
    "collect_overdue",
    "configure_tuning",
    "decide",
    "delete_subscription",
    "deliver",
    "get_preferences",
    "in_quiet_hours",
    "is_history",
    "list_deliveries",
    "list_subscriptions",
    "matches",
    "next_attempt",
    "priority_reaches",
    "recipients",
    "save_subscription",
    "send_digests",
    "send_test",
    "set_quiet_hours",
    "summarise",
]
