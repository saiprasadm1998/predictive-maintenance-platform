"""notifications.

Subscriptions, throttling, e-mail and webhook delivery, and digests.

Public interface of the module (ARC-001 §4.1). Other modules may import only
what this file exports, never the module's internal files.
"""

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
    is_history,
    matches,
    next_attempt,
    priority_reaches,
)
from pmp.notifications.runner import Notifier, PassResult
from pmp.notifications.service import (
    NotificationView,
    Recipient,
    Sender,
    SmtpSender,
    SubscriptionView,
    collect_alerts,
    collect_cases,
    collect_overdue,
    delete_subscription,
    deliver,
    list_deliveries,
    list_subscriptions,
    recipients,
    save_subscription,
    send_test,
    summarise,
)

__all__ = [
    "HISTORY_LAG",
    "PER_ALERT",
    "PER_HOUR",
    "SUBSCRIBABLE",
    "Decision",
    "EventKind",
    "NotificationError",
    "NotificationView",
    "Notifier",
    "PassResult",
    "Recipient",
    "Sender",
    "SmtpSender",
    "Status",
    "SubscriptionSpec",
    "SubscriptionView",
    "collect_alerts",
    "collect_cases",
    "collect_overdue",
    "decide",
    "delete_subscription",
    "deliver",
    "is_history",
    "list_deliveries",
    "list_subscriptions",
    "matches",
    "next_attempt",
    "priority_reaches",
    "recipients",
    "save_subscription",
    "send_test",
    "summarise",
]
