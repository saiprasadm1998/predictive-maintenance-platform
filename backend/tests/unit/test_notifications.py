"""Notification rules (plan 8.5, UCS §6.10): throttling, suppression, matching, retries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pmp.notifications import (
    Decision,
    EventKind,
    NotificationError,
    SubscriptionSpec,
    decide,
    is_history,
    matches,
    next_attempt,
    priority_reaches,
)

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def test_one_notification_per_alert_per_30_minutes() -> None:
    assert decide(NOW, None, 0) is Decision.SEND
    assert decide(NOW, NOW - timedelta(minutes=29), 0) is Decision.SKIP
    assert decide(NOW, NOW - timedelta(minutes=30), 0) is Decision.SEND


def test_at_most_20_an_hour_then_held_for_the_summary() -> None:
    assert decide(NOW, None, 19) is Decision.SEND
    assert decide(NOW, None, 20) is Decision.HOLD
    assert decide(NOW, NOW - timedelta(minutes=5), 25) is Decision.SKIP  # the alert rule first


def test_history_is_not_notified() -> None:
    assert not is_history(NOW - timedelta(minutes=2), NOW)
    assert is_history(NOW - timedelta(minutes=11), NOW)


def test_retries_back_off_for_an_hour() -> None:
    created = NOW
    delays = []
    at = created
    for attempt in range(1, 10):
        retry = next_attempt(created, attempt, at)
        if retry is None:
            break
        delays.append(round((retry - at).total_seconds() / 60))
        at = retry
    assert delays == [1, 2, 4, 8, 16]  # 31 minutes; the next (32) would pass the hour
    assert next_attempt(created, 6, created + timedelta(minutes=31)) is None


def test_matching_by_event_priority_and_scope() -> None:
    spec = SubscriptionSpec("P2", (EventKind.ALERT_RAISED,), scope_asset_id=5)
    assert matches(spec, EventKind.ALERT_RAISED, "P1", "1.5.6")
    assert matches(spec, EventKind.ALERT_RAISED, "P2", "1.5")
    assert not matches(spec, EventKind.ALERT_RAISED, "P3", "1.5.6")  # below the minimum
    assert not matches(spec, EventKind.ALERT_RAISED, "P1", "1.4.7")  # outside the scope
    assert not matches(spec, EventKind.ALERT_ESCALATED, "P1", "1.5.6")  # not chosen
    off = SubscriptionSpec("P4", (EventKind.ALERT_RAISED,), enabled=False)
    assert not matches(off, EventKind.ALERT_RAISED, "P1", "1")
    assert matches(
        SubscriptionSpec("P4", (EventKind.SOURCE_STALE,)), EventKind.SOURCE_STALE, None, None
    )
    assert priority_reaches("P1", "P4")
    assert not priority_reaches(None, "P4")


def test_a_subscription_needs_events_and_a_priority() -> None:
    with pytest.raises(NotificationError, match="at least one event"):
        SubscriptionSpec("P1", ()).check()
    with pytest.raises(NotificationError, match="Minimum priority"):
        SubscriptionSpec("P9", (EventKind.ALERT_RAISED,)).check()
    with pytest.raises(NotificationError, match="summary"):
        SubscriptionSpec("P1", (EventKind.SUMMARY,)).check()


def test_the_smtp_sender_uses_starttls_and_the_relay_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from email.message import EmailMessage

    from pmp.core import Settings
    from pmp.notifications import SmtpSender

    calls: list[object] = []

    class FakeSmtp:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            calls.append(("connect", host, port))

        def __enter__(self) -> FakeSmtp:
            return self

        def __exit__(self, *exc: object) -> None:
            calls.append("quit")

        def starttls(self) -> None:
            calls.append("starttls")

        def login(self, user: str, password: str) -> None:
            calls.append(("login", user, password))

        def send_message(self, message: EmailMessage) -> None:
            calls.append((message["From"], message["To"], message["Subject"]))

    monkeypatch.setattr("pmp.notifications.service.smtplib.SMTP", FakeSmtp)
    settings = Settings(
        database_url="postgresql+psycopg://x@localhost/x",
        secret_key="k",
        smtp_host="relay.plant.test",
        smtp_user="pmp",
        smtp_password="s3cret",
        smtp_from="pmp@plant.test",
        _env_file=None,
    )
    SmtpSender(settings).send("ana@plant.test", "[PMP] Test", "body")
    assert calls == [
        ("connect", "relay.plant.test", 587),
        "starttls",
        ("login", "pmp", "s3cret"),
        ("pmp@plant.test", "ana@plant.test", "[PMP] Test"),
        "quit",
    ]
    with pytest.raises(NotificationError, match="No SMTP host"):
        SmtpSender(Settings(database_url="x", secret_key="k", _env_file=None))
