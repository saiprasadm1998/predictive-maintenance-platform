"""Notification rules (UCS §6.10, UC-15). Pure: no database, no SMTP."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

PER_ALERT = timedelta(minutes=30)  # no more than one notification per alert per 30 minutes
PER_HOUR = 20  # at most 20 per user per hour, after which a summary is sent
HISTORY_LAG = timedelta(minutes=10)  # an event older than this is re-scored history
RETRY_FOR = timedelta(hours=1)  # retry with exponential back-off for up to 1 hour
PRIORITIES = ("P1", "P2", "P3", "P4")


class NotificationError(ValueError):
    pass


class EventKind(StrEnum):
    ALERT_RAISED = "alert_raised"
    ALERT_ESCALATED = "alert_escalated"
    CASE_ASSIGNED = "case_assigned"
    CASE_OVERDUE = "case_overdue"
    MODEL_REVIEW = "model_review"  # a case closed as a false alert (UC-13 2a)
    SOURCE_STALE = "source_stale"  # administrators (detected from ingestion health, 8.7)
    SUMMARY = "summary"  # not subscribable: the hourly cap's summary

    @property
    def label(self) -> str:
        return {
            "alert_raised": "Alert raised",
            "alert_escalated": "Alert escalated to Alert",
            "case_assigned": "Case assigned to me",
            "case_overdue": "My case overdue",
            "model_review": "False alert to review (model engineers)",
            "source_stale": "Data source stale (administrators)",
            "summary": "Summary",
        }[self.value]


SUBSCRIBABLE = tuple(e for e in EventKind if e is not EventKind.SUMMARY)


class Status(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"  # gave up after an hour of retries
    HELD = "held"  # over the hourly cap: goes out in the next summary
    SUMMARISED = "summarised"  # went out in a summary


class Decision(StrEnum):
    SEND = "send"
    SKIP = "skip"  # this alert was notified to the user within 30 minutes
    HOLD = "hold"  # the user had 20 this hour


@dataclass(frozen=True)
class SubscriptionSpec:
    min_priority: str
    events: tuple[EventKind, ...]
    scope_asset_id: int | None = None  # None: everything the user may see
    enabled: bool = True

    def check(self) -> None:
        if self.min_priority not in PRIORITIES:
            raise NotificationError(f"Minimum priority is one of {', '.join(PRIORITIES)}")
        if not self.events:
            raise NotificationError("Choose at least one event")
        if EventKind.SUMMARY in self.events:
            raise NotificationError("The summary is not an event to subscribe to")


def priority_reaches(priority: str | None, minimum: str) -> bool:
    """P1 is the highest: P2 reaches a P3 minimum, P4 does not."""
    return priority in PRIORITIES and PRIORITIES.index(priority) <= PRIORITIES.index(minimum)


def in_scope(scope_asset_id: int | None, asset_path: str) -> bool:
    """`asset_path` is the hierarchy path of IDs ("1.5.6"); None covers every asset."""
    return scope_asset_id is None or str(scope_asset_id) in asset_path.split(".")


def matches(
    subscription: SubscriptionSpec,
    event: EventKind,
    priority: str | None,
    asset_path: str | None,
) -> bool:
    if not subscription.enabled or event not in subscription.events:
        return False
    if asset_path is not None and not in_scope(subscription.scope_asset_id, asset_path):
        return False
    if priority is None:  # events without a priority (a stale source)
        return True
    return priority_reaches(priority, subscription.min_priority)


def decide(
    now: datetime,
    last_for_alert: datetime | None,
    recent_count: int,
) -> Decision:
    """UCS §6.10 throttling for one user: `last_for_alert` is when this alert was last
    notified to them, `recent_count` how many they were sent (or will be) this hour."""
    if last_for_alert is not None and now - last_for_alert < PER_ALERT:
        return Decision.SKIP
    if recent_count >= PER_HOUR:
        return Decision.HOLD
    return Decision.SEND


def is_history(event_time: datetime, now: datetime) -> bool:
    """Re-scored or replayed history is not notified (UCS §6.10 suppression)."""
    return now - event_time > HISTORY_LAG


def next_attempt(created_at: datetime, attempts: int, now: datetime) -> datetime | None:
    """Exponential back-off (1, 2, 4 … minutes) for up to an hour; None: give up."""
    retry_at = now + timedelta(minutes=2 ** max(attempts - 1, 0))
    return retry_at if retry_at - created_at <= RETRY_FOR else None


def summary_text(subjects: Sequence[str], link: str) -> tuple[str, str]:
    count = len(subjects)
    subject = f"[PMP] {count} more notification{'s' if count != 1 else ''} this hour"
    lines = [
        f"You reached the limit of {PER_HOUR} notifications an hour. These followed:",
        "",
        *(f"- {s.removeprefix('[PMP] ')}" for s in subjects),
        "",
        f"Open PMP: {link}",
    ]
    return subject, "\n".join(lines)


def contributors_text(contributors: Iterable[tuple[str, float | None]]) -> str:
    parts = [
        f"{name} {round(share)} %" if share is not None else name for name, share in contributors
    ]
    return ", ".join(parts) if parts else "—"
