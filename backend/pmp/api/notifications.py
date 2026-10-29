"""Notification subscriptions and the delivery log (plan 8.5, UC-15, UCS §6.10)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from pmp.api.common import not_found
from pmp.api.deps import SignedIn, database_of, settings_of, signed_in
from pmp.api.problems import ProblemError
from pmp.core import Permission, authorize
from pmp.notifications import (
    SUBSCRIBABLE,
    EventKind,
    NotificationError,
    NotificationView,
    SmtpSender,
    Status,
    SubscriptionSpec,
    SubscriptionView,
    delete_subscription,
    list_deliveries,
    list_subscriptions,
    save_subscription,
    send_test,
)

router = APIRouter(prefix="/api/v1", tags=["notifications"])
User = Annotated[SignedIn, Depends(signed_in)]
EventName = Literal[
    "alert_raised",
    "alert_escalated",
    "case_assigned",
    "case_overdue",
    "model_review",
    "source_stale",
]


class EventOut(BaseModel):
    value: str
    label: str


class SubscriptionIn(BaseModel):
    scope_asset_id: int | None = Field(default=None, description="null: everything you may see")
    min_priority: Literal["P1", "P2", "P3", "P4"] = "P2"
    events: list[EventName] = Field(min_length=1)
    enabled: bool = True


class SubscriptionOut(BaseModel):
    id: int
    scope_asset_id: int | None
    scope_code: str | None
    min_priority: str
    events: list[str]
    channel: str = Field(description="email (webhooks arrive in Release 3)")
    enabled: bool
    created_at: datetime
    updated_at: datetime


class NotificationOut(BaseModel):
    id: int
    user_id: int
    event: str
    alert_id: int | None
    case_id: int | None
    recipient: str
    subject: str
    status: str = Field(description="pending, sent, failed, held or summarised")
    attempts: int
    next_attempt_at: datetime | None
    last_error: str | None
    summary_id: int | None
    created_at: datetime
    sent_at: datetime | None


class TestIn(BaseModel):
    to: str = Field(min_length=3, max_length=200, description="an e-mail address")


def _sub_out(v: SubscriptionView) -> SubscriptionOut:
    return SubscriptionOut(
        id=v.id,
        scope_asset_id=v.scope_asset_id,
        scope_code=v.scope_code,
        min_priority=v.min_priority,
        events=[e.value for e in v.events],
        channel=v.channel,
        enabled=v.enabled,
        created_at=v.created_at,
        updated_at=v.updated_at,
    )


def _note_out(v: NotificationView) -> NotificationOut:
    return NotificationOut(
        id=v.id,
        user_id=v.user_id,
        event=v.event.value,
        alert_id=v.alert_id,
        case_id=v.case_id,
        recipient=v.recipient,
        subject=v.subject,
        status=v.status.value,
        attempts=v.attempts,
        next_attempt_at=v.next_attempt_at,
        last_error=v.last_error,
        summary_id=v.summary_id,
        created_at=v.created_at,
        sent_at=v.sent_at,
    )


def _spec(body: SubscriptionIn) -> SubscriptionSpec:
    return SubscriptionSpec(
        body.min_priority,
        tuple(EventKind(e) for e in body.events),
        body.scope_asset_id,
        body.enabled,
    )


def _problem(error: NotificationError) -> ProblemError:
    if "does not exist" in str(error):
        return not_found("Subscription or asset")
    return ProblemError(400, "subscription_refused", str(error))


@router.get(
    "/notifications/events",
    response_model=list[EventOut],
    summary="The events a subscription can choose (UCS §6.10)",
)
def get_events(user: User) -> list[EventOut]:
    return [EventOut(value=e.value, label=e.label) for e in SUBSCRIBABLE]


@router.get(
    "/notifications/subscriptions",
    response_model=list[SubscriptionOut],
    summary="My notification subscriptions",
)
def get_subscriptions(request: Request, user: User) -> list[SubscriptionOut]:
    with database_of(request).session() as session:
        return [_sub_out(v) for v in list_subscriptions(session, user.actor)]


@router.post(
    "/notifications/subscriptions",
    response_model=SubscriptionOut,
    status_code=201,
    summary="Subscribe (scope, minimum priority, events; e-mail)",
)
def post_subscription(request: Request, user: User, body: SubscriptionIn) -> SubscriptionOut:
    try:
        with database_of(request).session() as session:
            return _sub_out(save_subscription(session, user.actor, _spec(body)))
    except NotificationError as error:
        raise _problem(error) from None


@router.put(
    "/notifications/subscriptions/{subscription_id}",
    response_model=SubscriptionOut,
    summary="Change one of my subscriptions",
)
def put_subscription(
    request: Request, user: User, subscription_id: int, body: SubscriptionIn
) -> SubscriptionOut:
    try:
        with database_of(request).session() as session:
            return _sub_out(
                save_subscription(
                    session, user.actor, _spec(body), subscription_id, datetime.now(UTC)
                )
            )
    except NotificationError as error:
        raise _problem(error) from None


@router.delete(
    "/notifications/subscriptions/{subscription_id}",
    status_code=204,
    summary="Remove one of my subscriptions",
)
def remove_subscription(request: Request, user: User, subscription_id: int) -> Response:
    try:
        with database_of(request).session() as session:
            delete_subscription(session, user.actor, subscription_id)
    except NotificationError as error:
        raise _problem(error) from None
    return Response(status_code=204)


@router.get(
    "/notifications/log",
    response_model=list[NotificationOut],
    summary="The delivery log, newest first (administrators)",
)
def get_log(
    request: Request,
    user: User,
    status: Literal["pending", "sent", "failed", "held", "summarised"] | None = None,
    user_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[NotificationOut]:
    with database_of(request).session() as session:
        views = list_deliveries(
            session,
            user.actor,
            status=Status(status) if status else None,
            user_id=user_id,
            limit=limit,
        )
        return [_note_out(v) for v in views]


@router.post(
    "/notifications/test",
    status_code=204,
    summary="Send a test e-mail through the relay (administrators)",
)
def post_test(request: Request, user: User, body: TestIn) -> Response:
    authorize(user.actor, Permission.ADMINISTRATION, None, what="notification settings")
    settings = settings_of(request)
    try:
        send_test(SmtpSender(settings), body.to, settings.public_url)
    except NotificationError as error:
        raise ProblemError(409, "no_relay", str(error)) from None
    except OSError as error:  # SMTP and network failures
        raise ProblemError(502, "relay_failed", f"The relay refused: {error}") from None
    return Response(status_code=204)
