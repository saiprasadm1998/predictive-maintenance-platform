"""Notifications against PostgreSQL (plan 8.5, UC-15, FR-NOT-01, UCS §6.10).

"Done when": a P1 alert e-mails a subscriber within 2 minutes, once. The alert is the
alert-engine tests' DI rule on EQ-1 / main (criticality A), set so its first cycle raises
an Alert (P1); the notifier runs on the cycle's clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from pmp.alerting import AlertRuleSpec, RuleKind, shelve
from pmp.cases import Outcome, add_action, close_case, complete_action, create_case, update_case
from pmp.core import Actor, Database, Principal, Role, RoleAssignment, create_user
from pmp.notifications import (
    EventKind,
    NotificationError,
    Notifier,
    Status,
    SubscriptionSpec,
    list_deliveries,
    list_subscriptions,
    save_subscription,
)
from tests.integration.test_alerts import _rules, _run, _scheduler
from tests.integration.test_scoring_cycle import (  # noqa: F401  (deployed is a fixture)
    ACTOR,
    LIVE,
    deployed,
)

pytestmark = pytest.mark.integration
CYCLE = LIVE + timedelta(minutes=1)  # the first cycle the scheduler scores


class Mailbox:
    def __init__(self, failures: int = 0) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.failures = failures

    def send(self, to: str, subject: str, body: str) -> None:
        if self.failures:
            self.failures -= 1
            raise ConnectionRefusedError("relay down")
        self.sent.append((to, subject, body))


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def db(deployed: Database) -> Database:  # noqa: F811
    with deployed.session() as s:
        s.execute(text("TRUNCATE app_user RESTART IDENTITY CASCADE"))
        s.execute(text("TRUNCATE notifier_cursor, notification_log"))
        for name, role in (
            ("ana", Role.ANALYST),
            ("max", Role.MAINTENANCE),
            ("moe", Role.MODEL_ENGINEER),
            ("vic", Role.VIEWER),
        ):
            create_user(
                s,
                ACTOR,
                username=name,
                display_name=name.capitalize(),
                password="correct horse battery",
                assignments=[RoleAssignment(role)],
                email=f"{name}@plant.test",
            )
    return deployed


def actor(db: Database, username: str) -> Actor:
    with db.session() as s:
        user_id, role = s.execute(
            text(
                "SELECT u.id, r.role FROM app_user u JOIN user_role r ON r.user_id = u.id "
                "WHERE u.username = :u"
            ),
            {"u": username},
        ).one()
    return Actor.user(Principal(user_id, username, (RoleAssignment(Role(role)),)))


def subscribe(db: Database, username: str, *events: EventKind, minimum: str = "P2") -> None:
    with db.session() as s:
        save_subscription(s, actor(db, username), SubscriptionSpec(minimum, events))


def notifier(db: Database, mailbox: Mailbox, now: datetime) -> tuple[Notifier, Clock]:
    clock = Clock(now)
    return Notifier(db, mailbox, "https://pmp.test", clock=clock), clock


def raise_p1(db: Database) -> None:
    """DI near 30 % against an alert limit of 20, raised on the first cycle: Alert, P1."""
    _rules(db, AlertRuleSpec(RuleKind.DI, 10, 20, persistence_n=1, persistence_m=1))
    _run(_scheduler(db), 1)


def test_a_p1_alert_emails_a_subscriber_within_2_minutes_once(db: Database) -> None:
    subscribe(db, "ana", EventKind.ALERT_RAISED, EventKind.ALERT_ESCALATED, minimum="P1")
    subscribe(db, "vic", EventKind.CASE_ASSIGNED)  # another event: no alert e-mail
    mailbox = Mailbox()
    worker, clock = notifier(db, mailbox, CYCLE - timedelta(minutes=5))
    worker.run_once()  # the first pass starts the cursors at the end: no history
    raise_p1(db)
    clock.now = CYCLE + timedelta(seconds=30)
    result = worker.run_once()
    assert (result.queued, result.sent) == (1, 1)
    ((to, subject, body),) = mailbox.sent
    assert to == "ana@plant.test"
    assert subject == "[PMP] P1 Alert raised · EQ-1 · DI"
    assert "Asset:     Site A / EQ-1" in body
    assert "Priority:  P1" in body
    assert "Top contributors: EQ1." in body
    assert "https://pmp.test/assets/" in body
    assert "?alert=" in body
    clock.now += timedelta(minutes=1)
    assert worker.run_once().sent == 0  # once
    with db.session() as s:
        (logged,) = list_deliveries(s, ACTOR)
    assert logged.status is Status.SENT
    assert logged.sent_at is not None
    assert logged.sent_at - CYCLE < timedelta(minutes=2)


def test_shelved_alerts_and_history_are_not_notified(db: Database) -> None:
    subscribe(db, "ana", EventKind.ALERT_RAISED, minimum="P4")
    mailbox = Mailbox()
    worker, clock = notifier(db, mailbox, CYCLE - timedelta(minutes=5))
    worker.run_once()
    raise_p1(db)
    with db.session() as s:
        alert_id = s.execute(text("SELECT max(id) FROM alert")).scalar_one()
        shelve(
            s,
            ACTOR,
            [alert_id],
            CYCLE,
            reason="maintenance",
            duration=timedelta(hours=1),
        )
    clock.now = CYCLE + timedelta(seconds=30)
    assert worker.run_once().queued == 0  # shelved
    late, late_clock = notifier(db, mailbox, CYCLE - timedelta(minutes=5))
    with db.session() as s:
        s.execute(text("TRUNCATE notifier_cursor"))
        s.execute(text("TRUNCATE alert RESTART IDENTITY CASCADE"))
    late.run_once()
    raise_p1(db)
    late_clock.now = CYCLE + timedelta(hours=2)  # re-scored history, seen hours later
    assert late.run_once().queued == 0
    assert mailbox.sent == []


def test_the_hourly_cap_holds_then_summarises(db: Database) -> None:
    subscribe(db, "ana", EventKind.ALERT_RAISED, minimum="P4")
    ana = actor(db, "ana")
    now = CYCLE + timedelta(seconds=30)
    with db.session() as s:  # 20 already this hour
        for i in range(20):
            s.execute(
                text(
                    "INSERT INTO notification_log (user_id, event, recipient, subject, body, "
                    "status, attempts, created_at, sent_at) VALUES (:u, 'alert_raised', "
                    "'ana@plant.test', :s, '', 'sent', 1, :t, :t)"
                ),
                {"u": ana.user_id, "s": f"[PMP] earlier {i}", "t": now - timedelta(minutes=50)},
            )
    mailbox = Mailbox()
    worker, clock = notifier(db, mailbox, CYCLE - timedelta(minutes=5))
    worker.run_once()
    raise_p1(db)
    clock.now = now
    result = worker.run_once()
    assert (result.queued, result.sent, result.summaries) == (1, 0, 0)  # held
    clock.now = now + timedelta(minutes=11)  # the earlier 20 are now over an hour old
    result = worker.run_once()
    assert (result.summaries, result.sent) == (1, 1)
    ((_, subject, body),) = mailbox.sent
    assert subject == "[PMP] 1 more notification this hour"
    assert "P1 Alert raised · EQ-1 · DI" in body
    with db.session() as s:
        held = list_deliveries(s, ACTOR, status=Status.SUMMARISED)
    assert len(held) == 1
    assert held[0].summary_id is not None


def test_a_failed_relay_is_retried_with_back_off(db: Database) -> None:
    subscribe(db, "ana", EventKind.ALERT_RAISED, minimum="P1")
    mailbox = Mailbox(failures=2)
    worker, clock = notifier(db, mailbox, CYCLE - timedelta(minutes=5))
    worker.run_once()
    raise_p1(db)
    start = CYCLE + timedelta(seconds=30)
    clock.now = start
    assert worker.run_once().sent == 0  # attempt 1 fails: retry in 1 minute
    clock.now = start + timedelta(seconds=30)
    assert worker.run_once().sent == 0  # not yet due
    clock.now = start + timedelta(minutes=1)
    assert worker.run_once().sent == 0  # attempt 2 fails: retry in 2 minutes
    clock.now = start + timedelta(minutes=3)
    assert worker.run_once().sent == 1
    with db.session() as s:
        (logged,) = list_deliveries(s, ACTOR)
    assert (logged.status, logged.attempts, logged.last_error) == (Status.SENT, 3, None)

    always = Mailbox(failures=100)
    give_up, give_up_clock = notifier(db, always, start)
    with db.session() as s:
        s.execute(text("UPDATE notification_log SET status = 'pending', attempts = 0, "
                       "next_attempt_at = created_at"))  # fmt: skip
    for minutes in (0, 1, 3, 7, 15, 31):
        give_up_clock.now = start + timedelta(minutes=minutes)
        give_up.run_once()
    with db.session() as s:
        (logged,) = list_deliveries(s, ACTOR)
    assert logged.status is Status.FAILED
    assert logged.last_error == "ConnectionRefusedError: relay down"


def test_case_assignment_and_a_false_alert_review(db: Database) -> None:
    subscribe(db, "max", EventKind.CASE_ASSIGNED, minimum="P4")
    subscribe(db, "moe", EventKind.MODEL_REVIEW, minimum="P4")
    subscribe(db, "ana", EventKind.MODEL_REVIEW, minimum="P4")  # not a model engineer
    raise_p1(db)
    mailbox = Mailbox()
    worker, clock = notifier(db, mailbox, CYCLE)
    worker.run_once()
    ana, max_ = actor(db, "ana"), actor(db, "max")
    with db.session() as s:
        alert_id = s.execute(text("SELECT max(id) FROM alert")).scalar_one()
        case = create_case(s, ana, [alert_id], "Pump bearing", CYCLE)
        update_case(s, ana, case.id, assignee_id=max_.user_id, now=CYCLE)
        acting = add_action(s, max_, case.id, "Inspect", now=CYCLE)
        complete_action(s, max_, case.id, acting.actions[0].id, now=CYCLE)
        close_case(s, max_, case.id, Outcome.FALSE_ALERT, now=CYCLE)
    clock.now = CYCLE + timedelta(seconds=30)
    worker.run_once()
    sent = {(to, subject) for to, subject, _ in mailbox.sent}
    assert sent == {
        ("max@plant.test", "[PMP] C-0001 assigned to you · P1 · EQ-1"),
        ("moe@plant.test", "[PMP] Review EQ-1: C-0001 closed as a false alert"),
    }


def test_subscriptions_are_ones_own(db: Database) -> None:
    ana, vic = actor(db, "ana"), actor(db, "vic")
    with db.session() as s:
        mine = save_subscription(s, ana, SubscriptionSpec("P2", (EventKind.ALERT_RAISED,)))
        with pytest.raises(NotificationError, match="does not exist"):
            save_subscription(s, vic, SubscriptionSpec("P1", (EventKind.ALERT_RAISED,)), mine.id)
        assert list_subscriptions(s, vic) == []
        assert [x.id for x in list_subscriptions(s, ana)] == [mine.id]
