"""Subscriptions, matching, throttling and delivery (UC-15, FR-NOT-01, UCS §6.10).

The notifier follows two logs with cursors: the alert event log (raise, escalate) and the
case activity log (assignment, closure as a false alert), and checks overdue cases once a
day. Each event is matched to the subscriptions of the users who may see its asset; the
throttling rules then decide, per user, to send it, skip it (the alert was notified within
30 minutes) or hold it for an hourly summary (20 an hour). Shelved alerts, alerts of
models out of service and re-scored history are not notified. Each notification is a row
of the delivery log, sent by the worker with retries for up to an hour.
"""

from __future__ import annotations

import logging
import smtplib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pmp.alerting import (
    AlertState,
    AlertView,
    alert_events_since,
    get_alerts,
    last_alert_event_id,
)
from pmp.cases import (
    ActivityType,
    CaseError,
    case_events_since,
    get_case,
    last_case_event_id,
    overdue_cases,
)
from pmp.core import (
    Actor,
    Permission,
    Person,
    Settings,
    active_people,
    audit_change,
    authorize,
)
from pmp.modelling import ModelError, get_model_by_id, model_asset_code
from pmp.notifications.domain import (
    PER_HOUR,
    Decision,
    EventKind,
    NotificationError,
    Status,
    SubscriptionSpec,
    contributors_text,
    decide,
    is_history,
    matches,
    next_attempt,
    summary_text,
)
from pmp.notifications.models import CursorRow, NotificationRow, SubscriptionRow
from pmp.registry import AssetView, RegistryError, find_asset, get_asset_by_id
from pmp.scoring import cycle_outputs, get_runtime_statuses

logger = logging.getLogger(__name__)
ALERT_ACTIONS = {"raise": EventKind.ALERT_RAISED, "escalate": EventKind.ALERT_ESCALATED}
SILENT_STATES = {AlertState.SHELVED, AlertState.OUT_OF_SERVICE}
BATCH = 100


# ------------------------------------------------------------------ subscriptions


@dataclass(frozen=True)
class SubscriptionView:
    id: int
    user_id: int
    scope_asset_id: int | None
    scope_code: str | None
    min_priority: str
    events: tuple[EventKind, ...]
    channel: str
    enabled: bool
    created_at: datetime
    updated_at: datetime

    @property
    def spec(self) -> SubscriptionSpec:
        return SubscriptionSpec(self.min_priority, self.events, self.scope_asset_id, self.enabled)


def _sub_view(session: Session, row: SubscriptionRow) -> SubscriptionView:
    scope = get_asset_by_id(session, row.scope_asset_id).code if row.scope_asset_id else None
    return SubscriptionView(
        row.id,
        row.user_id,
        row.scope_asset_id,
        scope,
        row.min_priority,
        tuple(EventKind(e) for e in row.events if e in EventKind._value2member_map_),
        row.channel,
        row.enabled,
        row.created_at,
        row.updated_at,
    )


def _own(actor: Actor) -> int:
    authorize(actor, Permission.OWN_SUBSCRIPTIONS, None, what="notification subscriptions")
    if actor.user_id is None:
        raise NotificationError("Subscriptions belong to a user")
    return actor.user_id


def list_subscriptions(session: Session, actor: Actor) -> list[SubscriptionView]:
    user_id = _own(actor)
    rows = session.scalars(
        select(SubscriptionRow)
        .where(SubscriptionRow.user_id == user_id)
        .order_by(SubscriptionRow.id)
    ).all()
    return [_sub_view(session, r) for r in rows]


def save_subscription(
    session: Session,
    actor: Actor,
    spec: SubscriptionSpec,
    subscription_id: int | None = None,
    now: datetime | None = None,
) -> SubscriptionView:
    """Create, or change, one of the actor's own subscriptions (ARC §9.2: every role)."""
    user_id = _own(actor)
    spec.check()
    if spec.scope_asset_id is not None:
        try:
            get_asset_by_id(session, spec.scope_asset_id)
        except RegistryError:
            raise NotificationError(f"Asset {spec.scope_asset_id} does not exist") from None
    content = {
        "scope_asset_id": spec.scope_asset_id,
        "min_priority": spec.min_priority,
        "events": [e.value for e in spec.events],
        "enabled": spec.enabled,
    }
    if subscription_id is None:
        row = SubscriptionRow(user_id=user_id, channel="email", **content)
        session.add(row)
        before = None
    else:
        found = session.get(SubscriptionRow, subscription_id)
        if found is None or found.user_id != user_id:
            raise NotificationError(f"Subscription {subscription_id} does not exist")
        row = found
        before = {
            "scope_asset_id": row.scope_asset_id,
            "min_priority": row.min_priority,
            "events": list(row.events),
            "enabled": row.enabled,
        }
        for key, value in content.items():
            setattr(row, key, value)
        if now is not None:
            row.updated_at = now
    session.flush()
    session.refresh(row)
    audit_change(
        session,
        actor,
        entity="subscription",
        entity_id=row.id,
        action="create" if before is None else "update",
        before=before,
        after=content,
    )
    return _sub_view(session, row)


def delete_subscription(session: Session, actor: Actor, subscription_id: int) -> None:
    user_id = _own(actor)
    row = session.get(SubscriptionRow, subscription_id)
    if row is None or row.user_id != user_id:
        raise NotificationError(f"Subscription {subscription_id} does not exist")
    session.delete(row)
    audit_change(session, actor, entity="subscription", entity_id=subscription_id, action="delete")


# ------------------------------------------------------------------ delivery log


@dataclass(frozen=True)
class NotificationView:
    id: int
    user_id: int
    event: EventKind
    alert_id: int | None
    case_id: int | None
    recipient: str
    subject: str
    body: str
    status: Status
    attempts: int
    next_attempt_at: datetime | None
    last_error: str | None
    summary_id: int | None
    created_at: datetime
    sent_at: datetime | None


def _note_view(r: NotificationRow) -> NotificationView:
    return NotificationView(
        r.id, r.user_id, EventKind(r.event), r.alert_id, r.case_id, r.recipient, r.subject,
        r.body, Status(r.status), r.attempts, r.next_attempt_at, r.last_error, r.summary_id,
        r.created_at, r.sent_at,
    )  # fmt: skip


def list_deliveries(
    session: Session,
    actor: Actor,
    *,
    status: Status | None = None,
    user_id: int | None = None,
    limit: int = 200,
) -> list[NotificationView]:
    """The delivery log, newest first (administrators, plan 8.5)."""
    authorize(actor, Permission.ADMINISTRATION, None, what="the notification log")
    query = select(NotificationRow).order_by(NotificationRow.id.desc()).limit(limit)
    if status is not None:
        query = query.where(NotificationRow.status == status.value)
    if user_id is not None:
        query = query.where(NotificationRow.user_id == user_id)
    return [_note_view(r) for r in session.scalars(query).all()]


# ------------------------------------------------------------------ matching


@dataclass(frozen=True)
class Recipient:
    person: Person
    email: str


def _subscriptions(session: Session, user_ids: Iterable[int]) -> dict[int, list[SubscriptionSpec]]:
    out: dict[int, list[SubscriptionSpec]] = {}
    ids = sorted(set(user_ids))
    if not ids:
        return out
    for row in session.scalars(
        select(SubscriptionRow).where(
            SubscriptionRow.user_id.in_(ids), SubscriptionRow.enabled.is_(True)
        )
    ).all():
        events = tuple(EventKind(e) for e in row.events if e in EventKind._value2member_map_)
        out.setdefault(row.user_id, []).append(
            SubscriptionSpec(row.min_priority, events, row.scope_asset_id, row.enabled)
        )
    return out


NEEDS = {
    EventKind.MODEL_REVIEW: Permission.MODELS,
    EventKind.SOURCE_STALE: Permission.ADMINISTRATION,
}


def recipients(
    session: Session,
    event: EventKind,
    priority: str | None,
    asset_path: str | None,
    only: Iterable[int] | None = None,
) -> list[Recipient]:
    """Active users with an e-mail address whose subscription matches the event and who
    may see the asset (and, for some events, act on it)."""
    people = [p for p in active_people(session, only) if p.email]
    subs = _subscriptions(session, [p.principal.user_id for p in people])
    found = []
    for person in people:
        if not person.principal.grant(Permission.VIEW, asset_path):
            continue
        needed = NEEDS.get(event)
        if needed is not None and not person.principal.grant(needed, asset_path):
            continue
        if any(
            matches(s, event, priority, asset_path) for s in subs.get(person.principal.user_id, [])
        ):
            found.append(Recipient(person, person.email or ""))
    return found


def _last_for_alert(session: Session, user_id: int, alert_id: int) -> datetime | None:
    found: datetime | None = session.scalar(
        select(func.max(NotificationRow.created_at)).where(
            NotificationRow.user_id == user_id, NotificationRow.alert_id == alert_id
        )
    )
    return found


def _recent_count(session: Session, user_id: int, now: datetime) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(NotificationRow)
            .where(
                NotificationRow.user_id == user_id,
                NotificationRow.created_at > now - timedelta(hours=1),
                NotificationRow.status.in_(
                    [Status.PENDING.value, Status.SENT.value, Status.FAILED.value]
                ),
            )
        )
        or 0
    )


def _queue(
    session: Session,
    people: Sequence[Recipient],
    event: EventKind,
    subject: str,
    body: str,
    now: datetime,
    *,
    alert_id: int | None = None,
    case_id: int | None = None,
) -> int:
    queued = 0
    for r in people:
        user_id = r.person.principal.user_id
        last = _last_for_alert(session, user_id, alert_id) if alert_id is not None else None
        decision = decide(now, last, _recent_count(session, user_id, now))
        if decision is Decision.SKIP:
            continue
        session.add(
            NotificationRow(
                user_id=user_id,
                event=event.value,
                alert_id=alert_id,
                case_id=case_id,
                recipient=r.email,
                subject=subject,
                body=body,
                status=(Status.HELD if decision is Decision.HOLD else Status.PENDING).value,
                attempts=0,
                next_attempt_at=now,
                created_at=now,
            )
        )
        session.flush()
        queued += 1
    return queued


# ------------------------------------------------------------------ content


def _path_label(session: Session, asset: AssetView) -> str:
    names = []
    for part in asset.path.split("."):
        if part.isdigit():
            node = get_asset_by_id(session, int(part))
            names.append(node.code if node.id == asset.id else node.name)
    return " / ".join(names) or asset.code


def _alert_content(
    session: Session,
    alert: AlertView,
    event: EventKind,
    event_time: datetime,
    priority: str,
    severity: str,
    asset: AssetView,
    public_url: str,
) -> tuple[str, str]:
    try:
        model = get_model_by_id(session, alert.model_id)
        version = next((v for v in model.versions if v.id == alert.version_id), model.latest)
        model_text = f"{model.asset_code} / {model.name} v{version.version}"
        names = {s.tag_id: s.source_name for s in version.sensors}
    except ModelError:
        model_text, names = f"model {alert.model_id}", {}
    runtime = next((r for r in get_runtime_statuses(session) if r.model_id == alert.model_id), None)
    outputs = sorted(
        cycle_outputs(session, alert.version_id, event_time),
        key=lambda o: -(o.contribution or 0),
    )[:3]
    what = "DI" if alert.kind.value == "di" else names.get(alert.tag_id or 0, "sensor")
    verb = "escalated to Alert" if event is EventKind.ALERT_ESCALATED else "raised"
    subject = f"[PMP] {priority} {severity} {verb} · {asset.code} · {what}"
    di = "—" if runtime is None or runtime.di is None else f"{runtime.di:.1f} %"
    health = "—" if runtime is None or runtime.health is None else f"{runtime.health:.0f}"
    lines = [
        f"{severity} {verb} on {asset.code} ({what}).",
        "",
        f"Asset:     {_path_label(session, asset)}",
        f"Model:     {model_text}",
        f"Severity:  {severity}",
        f"Priority:  {priority}",
        f"DI:        {di}",
        f"Health:    {health}",
        "Top contributors: "
        + contributors_text((names.get(o.tag_id, str(o.tag_id)), o.contribution) for o in outputs),
        f"Time:      {event_time.isoformat()}",
        "",
        f"Open the alert: {public_url.rstrip('/')}/assets/{asset.id}?alert={alert.id}",
    ]
    return subject, "\n".join(lines)


# ------------------------------------------------------------------ collection


def _cursor(session: Session, name: str, initial: int) -> CursorRow:
    row = session.get(CursorRow, name, with_for_update=True)
    if row is None:  # first run: start at the end, so history is never notified
        row = CursorRow(name=name, position=initial)
        session.add(row)
        session.flush()
    return row


def collect_alerts(session: Session, now: datetime, public_url: str) -> int:
    cursor = _cursor(session, "alert_event", last_alert_event_id(session))
    events = alert_events_since(session, cursor.position, ALERT_ACTIONS, BATCH)
    if not events:
        return 0
    alerts = {a.id: a for a in get_alerts(session, sorted({e.alert_id for e in events}))}
    queued = 0
    for ev in events:
        cursor.position = ev.id
        alert = alerts.get(ev.alert_id)
        if alert is None or alert.state in SILENT_STATES or not ev.priority:
            continue  # shelved or out of service (UCS §6.10 suppression)
        if is_history(ev.ts, now):
            continue  # re-scored or replayed history
        asset = find_asset(session, model_asset_code(session, alert.model_id))
        if asset is None:
            continue
        kind = ALERT_ACTIONS[ev.action]
        people = recipients(session, kind, ev.priority, asset.path)
        if not people:
            continue
        subject, body = _alert_content(
            session, alert, kind, ev.ts, ev.priority, ev.severity, asset, public_url
        )
        queued += _queue(session, people, kind, subject, body, now, alert_id=alert.id)
    return queued


def collect_cases(session: Session, now: datetime, public_url: str) -> int:
    cursor = _cursor(session, "case_activity", last_case_event_id(session))
    events = case_events_since(
        session, cursor.position, [ActivityType.ASSIGNMENT, ActivityType.CLOSURE], BATCH
    )
    queued = 0
    for ev in events:
        cursor.position = ev.id
        try:
            c = get_case(session, ev.case_id)
        except CaseError:
            continue
        link = f"{public_url.rstrip('/')}/cases/{c.id}"
        if ev.type is ActivityType.ASSIGNMENT:
            to = ev.data.get("to")
            if not isinstance(to, int) or to == ev.author_id:
                continue  # unassigned, or assigned to themselves
            kind = EventKind.CASE_ASSIGNED
            people = recipients(session, kind, c.priority, c.asset_path, only=[to])
            subject = f"[PMP] {c.number} assigned to you · {c.priority} · {c.asset_code}"
            body = "\n".join(
                [
                    f"{c.number} · {c.title}",
                    "",
                    f"Asset:     {c.asset_code}",
                    f"Priority:  {c.priority}",
                    f"Status:    {c.status.value}",
                    f"Due:       {c.due.isoformat() if c.due else '—'}",
                    "",
                    f"Open the case: {link}",
                ]
            )
        elif ev.data.get("outcome") == "false_alert":
            kind = EventKind.MODEL_REVIEW
            people = recipients(session, kind, c.priority, c.asset_path)
            models = sorted({a["model_id"] for a in c.snapshot.get("alerts", [])})
            subject = f"[PMP] Review {c.asset_code}: {c.number} closed as a false alert"
            body = "\n".join(
                [
                    f"{c.number} · {c.title} was closed as a false alert.",
                    "Please review the model's alert limits or retrain it (UC-13).",
                    "",
                    f"Asset:     {c.asset_code}",
                    "Models:    " + ", ".join(str(m) for m in models),
                    f"Lessons:   {c.lessons or '—'}",
                    "",
                    f"Open the case: {link}",
                ]
            )
        else:
            continue
        queued += _queue(session, people, kind, subject, body, now, case_id=c.id)
    return queued


def collect_overdue(session: Session, now: datetime, public_url: str, today: date) -> int:
    """Once a day: each open case past its due date reminds its assignee."""
    cursor = _cursor(session, "overdue", 0)
    if cursor.checked_at is not None and cursor.checked_at.date() >= today:
        return 0
    cursor.checked_at = now
    queued = 0
    for c in overdue_cases(session, today):
        if c.assignee_id is None:
            continue
        kind = EventKind.CASE_OVERDUE
        people = recipients(session, kind, c.priority, c.asset_path, only=[c.assignee_id])
        due = c.due.isoformat() if c.due else "—"
        subject = f"[PMP] {c.number} is overdue · {c.priority} · {c.asset_code}"
        body = "\n".join(
            [
                f"{c.number} · {c.title} was due on {due} and is {c.status.value.lower()}.",
                "",
                f"Open the case: {public_url.rstrip('/')}/cases/{c.id}",
            ]
        )
        queued += _queue(session, people, kind, subject, body, now, case_id=c.id)
    return queued


# ------------------------------------------------------------------ sending


class Sender(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpSender:
    """The SMTP relay (ARC §9.1 conduit C3: port 587 with STARTTLS)."""

    def __init__(self, settings: Settings, timeout_s: float = 20.0) -> None:
        if not settings.smtp_host:
            raise NotificationError("No SMTP host is configured (PMP_SMTP_HOST)")
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.user = settings.smtp_user
        self.password = (
            settings.smtp_password.get_secret_value() if settings.smtp_password else None
        )
        self.sender = settings.smtp_from
        self.starttls = settings.smtp_starttls
        self.timeout_s = timeout_s

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_s) as smtp:
            if self.starttls:
                smtp.starttls()
            if self.user and self.password:
                smtp.login(self.user, self.password)
            smtp.send_message(message)


def summarise(session: Session, now: datetime, public_url: str) -> int:
    """Users over the hourly cap get one summary of what was held, once below it again."""
    users = session.scalars(
        select(NotificationRow.user_id)
        .where(NotificationRow.status == Status.HELD.value)
        .distinct()
    ).all()
    made = 0
    for user_id in users:
        if _recent_count(session, user_id, now) >= PER_HOUR:
            continue
        held = session.scalars(
            select(NotificationRow)
            .where(NotificationRow.user_id == user_id, NotificationRow.status == Status.HELD.value)
            .order_by(NotificationRow.id)
            .with_for_update()
        ).all()
        subject, body = summary_text([h.subject for h in held], public_url.rstrip("/") + "/alerts")
        summary = NotificationRow(
            user_id=user_id,
            event=EventKind.SUMMARY.value,
            recipient=held[0].recipient,
            subject=subject,
            body=body,
            status=Status.PENDING.value,
            attempts=0,
            next_attempt_at=now,
            created_at=now,
        )
        session.add(summary)
        session.flush()
        for h in held:
            h.status = Status.SUMMARISED.value
            h.summary_id = summary.id
        made += 1
    return made


def deliver(session: Session, sender: Sender, now: datetime) -> tuple[int, int]:
    """Send what is due; a failure is retried with back-off for up to an hour."""
    due = session.scalars(
        select(NotificationRow)
        .where(
            NotificationRow.status == Status.PENDING.value,
            NotificationRow.next_attempt_at <= now,
        )
        .order_by(NotificationRow.id)
        .limit(BATCH)
        .with_for_update(skip_locked=True)
    ).all()
    sent = failed = 0
    for row in due:
        row.attempts += 1
        try:
            sender.send(row.recipient, row.subject, row.body)
        except Exception as error:
            row.last_error = f"{type(error).__name__}: {error}"[:500]
            retry = next_attempt(row.created_at, row.attempts, now)
            if retry is None:
                row.status = Status.FAILED.value
                row.next_attempt_at = None
                failed += 1
                logger.warning("Notification %s to %s failed for good", row.id, row.recipient)
            else:
                row.next_attempt_at = retry
            continue
        row.status = Status.SENT.value
        row.sent_at = now
        row.next_attempt_at = None
        row.last_error = None
        sent += 1
    return sent, failed


def send_test(sender: Sender, to: str, public_url: str) -> None:
    sender.send(
        to,
        "[PMP] Test notification",
        f"This is a test from the Predictive Maintenance Platform.\n\nOpen PMP: {public_url}",
    )
