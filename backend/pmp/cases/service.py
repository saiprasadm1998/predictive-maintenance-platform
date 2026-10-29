"""Case management (UC-12, UC-13, FR-CAS-01 to -03, UCS §6.9).

A case is created from one or more alerts of one asset and starts Open, with the highest
linked-alert priority and an immutable snapshot of what was known then: per model, the
DI and Health trend of the last 7 days with the DI limits, the sensors at the latest cycle
(contributions, z and data-quality state), the failure-mode match scores and the newest
forecast. It moves through the states of UCS Figure 7: assigning an Open case starts the
investigation, defining an action makes it Action required, completing the last action
puts it under Monitoring; it is closed with an outcome or cancelled with a reason.

Permissions follow ARC §9.2: analysts and model engineers manage and work on cases, a
maintenance engineer only on cases assigned to them. Changes are audited, logged as
activities and announced as `case.changed`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePath
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pmp.alerting import AlertError, AlertView, RuleKind, get_alerts, list_alert_rules
from pmp.cases.domain import (
    MAX_ATTACHMENT_BYTES,
    MAX_TITLE,
    PRIORITIES,
    ActionStatus,
    ActivityType,
    CaseConflictError,
    CaseError,
    CaseStatus,
    Outcome,
    case_number,
    check_closure,
    check_transition,
    clean_text,
    highest_priority,
)
from pmp.cases.models import ActivityRow, AttachmentRow, CaseAlertRow, CaseRow
from pmp.core import (
    Actor,
    Permission,
    Person,
    active_people,
    audit_change,
    authorize,
    notify,
)
from pmp.diagnostics import LibraryError, diagnose, mode_history
from pmp.modelling import ModelError, get_model_by_id, model_asset_code
from pmp.prognostics import latest_for_alerts, list_forecasts
from pmp.registry import AssetView, find_asset, get_asset_by_id, get_tags
from pmp.scoring import cycle_outputs, latest_cycle, score_trend

SNAPSHOT_DAYS = 7
SNAPSHOT_POINTS = 168  # hourly over 7 days
SNAPSHOT_MODES = 5


class _Unset:
    pass


UNSET: Any = _Unset()


@dataclass(frozen=True)
class ActivityView:
    id: int
    ts: datetime
    type: ActivityType
    author_id: int | None
    body: str
    data: dict[str, Any]
    attachment_id: int | None


@dataclass(frozen=True)
class ActionView:
    id: int  # the action's activity
    description: str
    owner_id: int | None
    due: date | None
    status: ActionStatus
    created_at: datetime
    done_at: datetime | None


@dataclass(frozen=True)
class AttachmentView:
    id: int
    filename: str
    content_type: str
    size: int
    sha256: str
    created_at: datetime
    created_by: int | None


@dataclass(frozen=True)
class CaseSummary:
    id: int
    number: str
    title: str
    status: CaseStatus
    priority: str
    asset_id: int
    asset_code: str
    asset_path: str
    assignee_id: int | None
    due: date | None
    outcome: Outcome | None
    review_requested: bool
    alert_ids: tuple[int, ...]
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None

    def overdue(self, today: date) -> bool:
        return self.status.is_open and self.due is not None and self.due < today


@dataclass(frozen=True)
class CaseDetail(CaseSummary):
    priority_set: bool = False
    confirmed_mode_id: int | None = None
    value_estimate: float | None = None
    lessons: str | None = None
    cancel_reason: str | None = None
    created_by: int | None = None
    snapshot: dict[str, Any] = field(default_factory=dict)
    activities: tuple[ActivityView, ...] = ()
    actions: tuple[ActionView, ...] = ()
    attachments: tuple[AttachmentView, ...] = ()


@dataclass(frozen=True)
class CaseQuery:
    statuses: tuple[CaseStatus, ...] = ()
    open_only: bool = False
    priorities: tuple[str, ...] = ()
    assignee_id: int | None = None
    overdue_on: date | None = None  # only cases overdue on this day
    outcome: Outcome | None = None
    asset_ids: tuple[int, ...] | None = None  # None: every asset
    text: str | None = None
    limit: int = 200


# ------------------------------------------------------------------ helpers


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _load(session: Session, case_id: int, actor: Actor, permission: Permission) -> CaseRow:
    """The case, after checking the actor may do `permission` on it (authorised first, so
    a refused user learns nothing: decision 6.7)."""
    row = session.get(CaseRow, case_id, with_for_update=True)
    if row is None:
        authorize(actor, permission, None, what="cases")
        raise CaseError(f"Case {case_id} does not exist")
    authorize(
        actor,
        permission,
        get_asset_by_id(session, row.asset_id).path,
        what=f"case {case_number(row.id)}",
        assigned=actor.user_id is not None and row.assignee_id == actor.user_id,
    )
    return row


def _require_open(row: CaseRow) -> None:
    if not CaseStatus(row.status).is_open:
        raise CaseConflictError(f"Case {case_number(row.id)} is {row.status.lower()}")


def _alert_ids(session: Session, case_ids: Iterable[int]) -> dict[int, tuple[int, ...]]:
    ids = sorted(set(case_ids))
    out: dict[int, list[int]] = {i: [] for i in ids}
    if ids:
        for case_id, alert_id in session.execute(
            select(CaseAlertRow.case_id, CaseAlertRow.alert_id)
            .where(CaseAlertRow.case_id.in_(ids))
            .order_by(CaseAlertRow.alert_id)
        ).all():
            out[case_id].append(alert_id)
    return {k: tuple(v) for k, v in out.items()}


def _activity(
    session: Session,
    row: CaseRow,
    actor: Actor,
    kind: ActivityType,
    now: datetime,
    body: str = "",
    data: dict[str, Any] | None = None,
    attachment_id: int | None = None,
) -> ActivityRow:
    activity = ActivityRow(
        case_id=row.id,
        ts=now,
        type=kind.value,
        author_id=actor.user_id,
        body=body,
        data=data or {},
        attachment_id=attachment_id,
    )
    session.add(activity)
    row.updated_at = now
    return activity


def _notify(session: Session, row: CaseRow) -> None:
    alert_ids = _alert_ids(session, [row.id])[row.id]
    alerts = get_alerts(session, alert_ids[:1]) if alert_ids else []
    notify(
        session,
        {
            "type": "case.changed",
            "case_id": row.id,
            "number": case_number(row.id),
            "status": row.status,
            "priority": row.priority,
            "assignee_id": row.assignee_id,
            "model_id": alerts[0].model_id if alerts else None,  # the stream's scope filter
        },
    )


def _set_status(
    session: Session,
    row: CaseRow,
    actor: Actor,
    target: CaseStatus,
    now: datetime,
    *,
    reason: str | None = None,
    automatic: bool = False,
) -> None:
    previous = row.status
    row.status = target.value
    if not target.is_open:
        row.closed_at = now
        session.execute(
            update(CaseAlertRow).where(CaseAlertRow.case_id == row.id).values(open=False)
        )
    data: dict[str, Any] = {"from": previous, "to": target.value}
    if reason:
        data["reason"] = reason
    if automatic:
        data["automatic"] = True
    _activity(session, row, actor, ActivityType.STATE_CHANGE, now, reason or "", data)
    audit_change(
        session,
        actor,
        entity="case",
        entity_id=row.id,
        action="transition",
        before={"status": previous},
        after={"status": target.value, **({"reason": reason} if reason else {})},
    )


def _actions(activities: Iterable[ActivityRow]) -> list[ActionView]:
    out = []
    for a in activities:
        if a.type != ActivityType.ACTION.value:
            continue
        d = a.data
        out.append(
            ActionView(
                id=a.id,
                description=str(d.get("description", "")),
                owner_id=d.get("owner_id"),
                due=date.fromisoformat(d["due"]) if d.get("due") else None,
                status=ActionStatus(d.get("status", ActionStatus.OPEN.value)),
                created_at=a.ts,
                done_at=datetime.fromisoformat(d["done_at"]) if d.get("done_at") else None,
            )
        )
    return out


def _activity_rows(session: Session, case_id: int) -> list[ActivityRow]:
    return list(
        session.scalars(
            select(ActivityRow).where(ActivityRow.case_id == case_id).order_by(ActivityRow.id)
        ).all()
    )


def _open_actions(session: Session, case_id: int) -> int:
    return sum(
        1 for a in _actions(_activity_rows(session, case_id)) if a.status is ActionStatus.OPEN
    )


def _asset_of_alerts(session: Session, alerts: list[AlertView]) -> AssetView:
    codes = {model_asset_code(session, model_id) for model_id in {a.model_id for a in alerts}}
    if len(codes) != 1:
        raise CaseError(
            "A case covers the alerts of one asset; create one case per asset "
            f"(these are on {', '.join(sorted(codes))})"
        )
    asset = find_asset(session, codes.pop())
    if asset is None:
        raise CaseError("The alerts' asset no longer exists")
    return asset


def _alert_label(alert: AlertView, tags: dict[int, str]) -> str:
    what = "DI" if alert.kind is RuleKind.DI else tags.get(alert.tag_id or 0, "sensor")
    return f"{what} {alert.severity.value.lower()}"


def _check_unlinked(session: Session, alert_ids: Iterable[int], case_id: int | None) -> None:
    rows = session.execute(
        select(CaseAlertRow.alert_id, CaseAlertRow.case_id).where(
            CaseAlertRow.alert_id.in_(list(alert_ids)), CaseAlertRow.open.is_(True)
        )
    ).all()
    taken = [(a, c) for a, c in rows if c != case_id]
    if taken:
        alert_id, other = taken[0]
        raise CaseConflictError(
            f"Alert {alert_id} is already in open case {case_number(other)} "
            "(an alert belongs to one open case)"
        )


def _person(session: Session, user_id: int, asset_path: str, what: str) -> Person:
    people = assignable_people(session, asset_path)
    found = next((p for p in people if p.principal.user_id == user_id), None)
    if found is None:
        raise CaseError(f"User {user_id} cannot be the {what}: they cannot work on this case")
    return found


# ------------------------------------------------------------------ snapshot


def take_snapshot(session: Session, alerts: list[AlertView], now: datetime) -> dict[str, Any]:
    """What was known when the case was created (FR-CAS-01), as plain JSON: it is stored
    once and never changed, so later data cannot alter it."""
    tags = {t.id: t for t in get_tags(session, {a.tag_id for a in alerts if a.tag_id})}
    forecasts = latest_for_alerts(session, [a.id for a in alerts])
    models: list[dict[str, Any]] = []
    for model_id in dict.fromkeys(a.model_id for a in alerts):
        try:
            model = get_model_by_id(session, model_id)
        except ModelError:
            continue
        version_id = max(a.version_id for a in alerts if a.model_id == model_id)
        version = next((v for v in model.versions if v.id == version_id), model.latest)
        cycle = latest_cycle(session, version_id, now)
        entry: dict[str, Any] = {
            "model_id": model.id,
            "model": model.name,
            "asset_code": model.asset_code,
            "version": version.version,
            "at": cycle.isoformat() if cycle else None,
        }
        di_rule = next(
            (r.spec for r in list_alert_rules(session, model_id) if r.spec.kind is RuleKind.DI),
            None,
        )
        entry["limits"] = {"warning": di_rule.warning, "alert": di_rule.alert} if di_rule else None
        if cycle is not None:
            trend = score_trend(
                session,
                model_id,
                cycle - timedelta(days=SNAPSHOT_DAYS),
                cycle + timedelta(seconds=1),
                SNAPSHOT_POINTS,
                version_id=version_id,
            )
            entry["trend"] = {
                "ts": [t.isoformat() for t in trend.ts],
                "di": trend.max.get("di", []),
                "health": trend.min.get("health", []),
            }
            names = {s.tag_id: s.source_name for s in version.sensors}
            outputs = sorted(
                cycle_outputs(session, version_id, cycle),
                key=lambda o: -(o.contribution or 0),
            )
            entry["sensors"] = [
                {
                    "tag_id": o.tag_id,
                    "source_name": names.get(o.tag_id),
                    "actual": o.actual,
                    "predicted": o.predicted,
                    "z": o.z,
                    "contribution": o.contribution,
                    "dq_status": o.dq_status,
                    "dq_rule": o.dq_rule,
                    "used": o.used,
                }
                for o in outputs
            ]
            found = diagnose(session, model_id, cycle)
            entry["diagnosis"] = [
                {
                    "code": d.mode.spec.code,
                    "name": d.mode.spec.name,
                    "version": d.mode.version,
                    "score": None if d.match.score is None else round(d.match.score, 1),
                    "insufficient_evidence": d.match.insufficient,
                }
                for d in found.modes[:SNAPSHOT_MODES]
            ]
        model_alerts = [a.id for a in alerts if a.model_id == model_id]
        forecast = next((forecasts[i] for i in model_alerts if i in forecasts), None)
        if forecast is None:
            newest = list_forecasts(session, model_id=model_id, limit=1)
            forecast = newest[0] if newest else None
        entry["forecast"] = (
            {
                "id": forecast.id,
                "target": forecast.target.value,
                "tag": forecast.source_name,
                "threshold": forecast.threshold,
                "urgency": forecast.urgency,
                "median_h": forecast.median_h,
                "lower_h": forecast.lower_h,
                "upper_h": forecast.upper_h,
                "valid": forecast.valid,
                "at": forecast.at.isoformat(),
            }
            if forecast
            else None
        )
        models.append(entry)
    return {
        "taken_at": now.isoformat(),
        "alerts": [
            {
                "id": a.id,
                "model_id": a.model_id,
                "kind": a.kind.value,
                "tag": tags[a.tag_id].source_name if a.tag_id in tags else None,
                "state": a.state.value,
                "severity": a.severity.value,
                "priority": a.priority,
                "raised_at": a.raised_at.isoformat(),
            }
            for a in alerts
        ],
        "models": models,
    }


# ------------------------------------------------------------------ commands


def create_case(
    session: Session,
    actor: Actor,
    alert_ids: Iterable[int],
    title: str | None = None,
    now: datetime | None = None,
) -> CaseDetail:
    """UC-12 step 1: a case from one or more alerts of one asset, with its snapshot."""
    now = _now(now)
    ids = sorted(set(alert_ids))
    if not ids:
        authorize(actor, Permission.MANAGE_CASES, None, what="cases")
        raise CaseError("Choose at least one alert")
    try:
        alerts = get_alerts(session, ids)
    except AlertError as error:
        authorize(actor, Permission.MANAGE_CASES, None, what="cases")
        raise CaseError(str(error).replace("not found", "does not exist")) from None
    asset = _asset_of_alerts(session, alerts)
    authorize(actor, Permission.MANAGE_CASES, asset.path, what=f"cases on {asset.code}")
    _check_unlinked(session, ids, None)
    tags = {t.id: t.source_name for t in get_tags(session, {a.tag_id for a in alerts if a.tag_id})}
    worst = min(alerts, key=lambda a: (a.priority or "P9", a.raised_at))
    text = clean_text(title, "title", MAX_TITLE, required=False) or (
        f"{asset.code} {_alert_label(worst, tags)}"
    )
    row = CaseRow(
        title=text,
        status=CaseStatus.OPEN.value,
        priority=highest_priority(a.priority for a in alerts),
        priority_set=False,
        asset_id=asset.id,
        snapshot=take_snapshot(session, alerts, now),
        created_by=actor.user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    for alert in alerts:
        session.add(CaseAlertRow(case_id=row.id, alert_id=alert.id, linked_by=actor.user_id))
    try:
        session.flush()
    except IntegrityError:  # another case took one of the alerts meanwhile
        raise CaseConflictError("An alert is already in another open case") from None
    listed = ", ".join(f"alert {a.id} ({a.priority or 'out of service'})" for a in alerts)
    _activity(
        session,
        row,
        actor,
        ActivityType.CREATED,
        now,
        f"Case created from {listed}. Snapshot attached.",
        {"alert_ids": ids},
    )
    audit_change(
        session,
        actor,
        entity="case",
        entity_id=row.id,
        action="create",
        after={"title": text, "priority": row.priority, "alert_ids": ids, "asset": asset.code},
    )
    _notify(session, row)
    return get_case(session, row.id)


def link_alerts(
    session: Session,
    actor: Actor,
    case_id: int,
    alert_ids: Iterable[int],
    now: datetime | None = None,
) -> CaseDetail:
    """UC-12 1a: add alerts to an open case instead of creating a new one."""
    now = _now(now)
    row = _load(session, case_id, actor, Permission.MANAGE_CASES)
    _require_open(row)
    linked = set(_alert_ids(session, [row.id])[row.id])
    ids = sorted(set(alert_ids) - linked)
    if not ids:
        return get_case(session, row.id)
    try:
        alerts = get_alerts(session, ids)
    except AlertError as error:
        raise CaseError(str(error).replace("not found", "does not exist")) from None
    if _asset_of_alerts(session, alerts).id != row.asset_id:
        raise CaseError("A case covers the alerts of one asset")
    _check_unlinked(session, ids, row.id)
    for alert in alerts:
        session.add(CaseAlertRow(case_id=row.id, alert_id=alert.id, linked_by=actor.user_id))
    try:
        session.flush()
    except IntegrityError:
        raise CaseConflictError("An alert is already in another open case") from None
    before = row.priority
    if not row.priority_set:
        everything = get_alerts(session, sorted(linked | set(ids)))
        row.priority = highest_priority(a.priority for a in everything)
    _activity(
        session,
        row,
        actor,
        ActivityType.LINK,
        now,
        "Linked " + ", ".join(f"alert {i}" for i in ids),
        {"alert_ids": ids, "priority": {"from": before, "to": row.priority}},
    )
    audit_change(
        session,
        actor,
        entity="case",
        entity_id=row.id,
        action="link",
        before={"priority": before},
        after={"alert_ids": ids, "priority": row.priority},
    )
    _notify(session, row)
    return get_case(session, row.id)


def update_case(
    session: Session,
    actor: Actor,
    case_id: int,
    *,
    title: str | None = UNSET,
    priority: str | None = UNSET,
    assignee_id: int | None = UNSET,
    due: date | None = UNSET,
    now: datetime | None = None,
) -> CaseDetail:
    """UC-12 step 2: title, priority (editable, UCS §6.9), assignee and due date. Assigning
    an Open case starts its investigation (Figure 7)."""
    now = _now(now)
    row = _load(session, case_id, actor, Permission.MANAGE_CASES)
    _require_open(row)
    path = get_asset_by_id(session, row.asset_id).path
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    if title is not UNSET:
        text = clean_text(title, "title", MAX_TITLE)
        if text != row.title:
            before["title"], after["title"] = row.title, text
            row.title = text
    if priority is not UNSET:
        if priority not in PRIORITIES:
            raise CaseError(f"Priority is one of {', '.join(PRIORITIES)}")
        if priority != row.priority:
            before["priority"], after["priority"] = row.priority, priority
            row.priority = priority
        row.priority_set = True
    if due is not UNSET and due != row.due:
        before["due"] = row.due.isoformat() if row.due else None
        after["due"] = due.isoformat() if due else None
        row.due = due
    if after:
        _activity(
            session,
            row,
            actor,
            ActivityType.UPDATE,
            now,
            "; ".join(f"{k}: {after[k] if after[k] is not None else 'none'}" for k in after),
            {"before": before, "after": after},
        )
    if assignee_id is not UNSET and assignee_id != row.assignee_id:
        if assignee_id is None:
            if row.status != CaseStatus.OPEN.value:
                raise CaseError("A case under investigation keeps an assignee; reassign it")
            name = "nobody"
        else:
            name = _person(session, assignee_id, path, "assignee").display_name
        before["assignee_id"], after["assignee_id"] = row.assignee_id, assignee_id
        _activity(
            session,
            row,
            actor,
            ActivityType.ASSIGNMENT,
            now,
            f"Assigned to {name}",
            {"from": row.assignee_id, "to": assignee_id},
        )
        row.assignee_id = assignee_id
        if assignee_id is not None and row.status == CaseStatus.OPEN.value:
            _set_status(session, row, actor, CaseStatus.INVESTIGATING, now, automatic=True)
    if after:
        audit_change(
            session, actor, entity="case", entity_id=row.id, action="update",
            before=before, after=after,
        )  # fmt: skip
        _notify(session, row)
    return get_case(session, row.id)


def change_status(
    session: Session,
    actor: Actor,
    case_id: int,
    target: CaseStatus,
    reason: str | None = None,
    now: datetime | None = None,
) -> CaseDetail:
    """A state change along Figure 7 (closing has its own command)."""
    now = _now(now)
    row = _load(session, case_id, actor, Permission.MANAGE_CASES)
    reason_text = clean_text(reason, "reason", required=False) or None
    check_transition(
        CaseStatus(row.status),
        target,
        assigned=row.assignee_id is not None,
        open_actions=_open_actions(session, row.id),
        reason=reason_text,
    )
    if target is CaseStatus.CANCELLED:
        row.cancel_reason = reason_text
    _set_status(session, row, actor, target, now, reason=reason_text)
    _notify(session, row)
    return get_case(session, row.id)


def add_comment(
    session: Session, actor: Actor, case_id: int, body: str, now: datetime | None = None
) -> CaseDetail:
    now = _now(now)
    row = _load(session, case_id, actor, Permission.WORK_ON_CASES)
    _require_open(row)
    _activity(session, row, actor, ActivityType.COMMENT, now, clean_text(body, "comment"))
    _notify(session, row)
    return get_case(session, row.id)


def add_action(
    session: Session,
    actor: Actor,
    case_id: int,
    description: str,
    owner_id: int | None = None,
    due: date | None = None,
    now: datetime | None = None,
) -> CaseDetail:
    """UC-12 step 4: an action (description, owner, due date). Defining one under
    investigation or monitoring makes the case Action required."""
    now = _now(now)
    row = _load(session, case_id, actor, Permission.WORK_ON_CASES)
    _require_open(row)
    text = clean_text(description, "action", 2000)
    if owner_id is not None:
        _person(session, owner_id, get_asset_by_id(session, row.asset_id).path, "action owner")
    _activity(
        session,
        row,
        actor,
        ActivityType.ACTION,
        now,
        f"Action: {text}",
        {
            "description": text,
            "owner_id": owner_id,
            "due": due.isoformat() if due else None,
            "status": ActionStatus.OPEN.value,
        },
    )
    if row.status in (CaseStatus.INVESTIGATING.value, CaseStatus.MONITORING.value):
        _set_status(session, row, actor, CaseStatus.ACTION_REQUIRED, now, automatic=True)
    _notify(session, row)
    return get_case(session, row.id)


def complete_action(
    session: Session,
    actor: Actor,
    case_id: int,
    action_id: int,
    now: datetime | None = None,
) -> CaseDetail:
    """Mark an action done; when the last one is done the case goes to Monitoring."""
    now = _now(now)
    row = _load(session, case_id, actor, Permission.WORK_ON_CASES)
    _require_open(row)
    action = session.get(ActivityRow, action_id)
    if action is None or action.case_id != row.id or action.type != ActivityType.ACTION.value:
        raise CaseError(f"Action {action_id} does not exist")
    if action.data.get("status") == ActionStatus.DONE.value:
        raise CaseConflictError("The action is already done")
    action.data = {
        **action.data,
        "status": ActionStatus.DONE.value,
        "done_at": now.isoformat(),
        "done_by": actor.user_id,
    }
    _activity(
        session,
        row,
        actor,
        ActivityType.UPDATE,
        now,
        f"Action done: {action.data.get('description', '')}",
        {"action_id": action.id, "status": ActionStatus.DONE.value},
    )
    session.flush()
    if row.status == CaseStatus.ACTION_REQUIRED.value and not _open_actions(session, row.id):
        _set_status(session, row, actor, CaseStatus.MONITORING, now, automatic=True)
    _notify(session, row)
    return get_case(session, row.id)


def safe_filename(name: str) -> str:
    """The file's own name (no folders), printable, at most 200 characters."""
    base = PurePath(name.replace("\\", "/")).name
    cleaned = "".join(c for c in base if c.isprintable() and c not in '"<>|:*?').strip()
    return ((cleaned.strip(".") and cleaned) or "attachment")[:200]


def add_attachment(
    session: Session,
    actor: Actor,
    case_id: int,
    filename: str,
    content_type: str,
    content: bytes,
    root: Path,
    comment: str = "",
    now: datetime | None = None,
) -> CaseDetail:
    """An attachment (up to 20 MB, UCS §6.9), kept under the artefact directory."""
    now = _now(now)
    row = _load(session, case_id, actor, Permission.WORK_ON_CASES)
    _require_open(row)
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise CaseError("An attachment may be at most 20 MB")
    if not content:
        raise CaseError("The file is empty")
    name = safe_filename(filename)
    note = clean_text(comment, "comment", required=False)
    attachment = AttachmentRow(
        case_id=row.id,
        filename=name,
        content_type=(content_type or "application/octet-stream")[:200],
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        path="",
        created_by=actor.user_id,
        created_at=now,
    )
    session.add(attachment)
    session.flush()
    relative = f"cases/{row.id}/{attachment.id}"
    attachment.path = relative
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    _activity(
        session,
        row,
        actor,
        ActivityType.ATTACHMENT,
        now,
        note or f"Attached {name}",
        {"filename": name, "size": len(content)},
        attachment.id,
    )
    _notify(session, row)
    return get_case(session, row.id)


def attachment_file(
    session: Session, case_id: int, attachment_id: int, root: Path
) -> tuple[AttachmentView, Path]:
    found = session.get(AttachmentRow, attachment_id)
    if found is None or found.case_id != case_id:
        raise CaseError(f"Attachment {attachment_id} does not exist")
    return _attachment(found), root / found.path


def close_case(
    session: Session,
    actor: Actor,
    case_id: int,
    outcome: Outcome | None,
    confirmed_mode_id: int | None = None,
    value_estimate: float | None = None,
    lessons: str | None = None,
    now: datetime | None = None,
) -> CaseDetail:
    """UC-13: close with an outcome (and the confirmed mode of a true finding); the
    alerts are free for new cases. A false alert asks the model engineer to review the
    limits or retrain (2a; the notification arrives with plan 8.5)."""
    now = _now(now)
    row = _load(session, case_id, actor, Permission.WORK_ON_CASES)
    check_closure(CaseStatus(row.status), outcome, confirmed_mode_id)
    if outcome is None:  # check_closure refused it; this narrows the type
        raise CaseError("Record the outcome to close the case")
    if confirmed_mode_id is not None:
        try:
            mode_history(session, confirmed_mode_id)
        except LibraryError:
            raise CaseError(f"Failure mode {confirmed_mode_id} does not exist") from None
    if value_estimate is not None and value_estimate < 0:
        raise CaseError("The value estimate cannot be negative")
    row.outcome = outcome.value
    row.confirmed_mode_id = confirmed_mode_id
    row.value_estimate = value_estimate
    row.lessons = clean_text(lessons, "lessons learned", required=False) or None
    row.review_requested = outcome is Outcome.FALSE_ALERT
    body = f"Closed: {outcome.label}"
    if row.review_requested:
        body += ". Model engineer asked to review the alert limits or retrain the model."
    _activity(
        session,
        row,
        actor,
        ActivityType.CLOSURE,
        now,
        body,
        {
            "outcome": outcome.value,
            "confirmed_mode_id": confirmed_mode_id,
            "value_estimate": value_estimate,
            "lessons": row.lessons,
        },
    )
    _set_status(session, row, actor, CaseStatus.CLOSED, now)
    audit_change(
        session,
        actor,
        entity="case",
        entity_id=row.id,
        action="close",
        after={
            "outcome": outcome.value,
            "confirmed_mode_id": confirmed_mode_id,
            "value_estimate": value_estimate,
            "review_requested": row.review_requested,
        },
    )
    _notify(session, row)
    return get_case(session, row.id)


# ------------------------------------------------------------------ queries


def _attachment(row: AttachmentRow) -> AttachmentView:
    return AttachmentView(
        row.id, row.filename, row.content_type, row.size, row.sha256, row.created_at,
        row.created_by,
    )  # fmt: skip


def _summaries(session: Session, rows: list[CaseRow]) -> list[CaseSummary]:
    alerts = _alert_ids(session, [r.id for r in rows])
    assets = {a: get_asset_by_id(session, a) for a in {r.asset_id for r in rows}}
    return [
        CaseSummary(
            id=r.id,
            number=case_number(r.id),
            title=r.title,
            status=CaseStatus(r.status),
            priority=r.priority,
            asset_id=r.asset_id,
            asset_code=assets[r.asset_id].code,
            asset_path=assets[r.asset_id].path,
            assignee_id=r.assignee_id,
            due=r.due,
            outcome=Outcome(r.outcome) if r.outcome else None,
            review_requested=r.review_requested,
            alert_ids=alerts[r.id],
            created_at=r.created_at,
            updated_at=r.updated_at,
            closed_at=r.closed_at,
        )
        for r in rows
    ]


def get_case(session: Session, case_id: int) -> CaseDetail:
    row = session.get(CaseRow, case_id)
    if row is None:
        raise CaseError(f"Case {case_id} does not exist")
    summary = _summaries(session, [row])[0]
    activities = _activity_rows(session, case_id)
    attachments = session.scalars(
        select(AttachmentRow).where(AttachmentRow.case_id == case_id).order_by(AttachmentRow.id)
    ).all()
    return CaseDetail(
        **{f: getattr(summary, f) for f in CaseSummary.__dataclass_fields__},
        priority_set=row.priority_set,
        confirmed_mode_id=row.confirmed_mode_id,
        value_estimate=row.value_estimate,
        lessons=row.lessons,
        cancel_reason=row.cancel_reason,
        created_by=row.created_by,
        snapshot=row.snapshot,
        activities=tuple(
            ActivityView(
                a.id, a.ts, ActivityType(a.type), a.author_id, a.body, a.data, a.attachment_id
            )
            for a in activities
        ),
        actions=tuple(_actions(activities)),
        attachments=tuple(_attachment(a) for a in attachments),
    )


_ORDER = {s.value: i for i, s in enumerate(CaseStatus)}


def list_cases(session: Session, query: CaseQuery) -> list[CaseSummary]:
    """Open cases first, then priority, due date and newest (SCR-09)."""
    q = select(CaseRow)
    if query.statuses:
        q = q.where(CaseRow.status.in_([s.value for s in query.statuses]))
    if query.open_only:
        closed = [CaseStatus.CLOSED.value, CaseStatus.CANCELLED.value]
        q = q.where(CaseRow.status.not_in(closed))
    if query.priorities:
        q = q.where(CaseRow.priority.in_(query.priorities))
    if query.assignee_id is not None:
        q = q.where(CaseRow.assignee_id == query.assignee_id)
    if query.overdue_on is not None:
        closed = [CaseStatus.CLOSED.value, CaseStatus.CANCELLED.value]
        q = q.where(CaseRow.due < query.overdue_on, CaseRow.status.not_in(closed))
    if query.outcome is not None:
        q = q.where(CaseRow.outcome == query.outcome.value)
    if query.asset_ids is not None:
        q = q.where(CaseRow.asset_id.in_(query.asset_ids))
    if query.text:
        q = q.where(CaseRow.title.ilike(f"%{query.text.strip()}%"))
    rows = list(session.scalars(q.order_by(CaseRow.id.desc()).limit(query.limit)).all())
    rows.sort(
        key=lambda r: (
            not CaseStatus(r.status).is_open,
            r.priority,
            r.due or date.max,
            -r.id,
        )
    )
    return _summaries(session, rows)


def open_cases_for_alerts(session: Session, alert_ids: Iterable[int]) -> dict[int, int]:
    """The open case each alert is in (the alert list's Case column)."""
    ids = sorted(set(alert_ids))
    if not ids:
        return {}
    rows = session.execute(
        select(CaseAlertRow.alert_id, CaseAlertRow.case_id).where(
            CaseAlertRow.alert_id.in_(ids), CaseAlertRow.open.is_(True)
        )
    ).all()
    return {int(a): int(c) for a, c in rows}


def count_open_cases(session: Session, asset_ids: Iterable[int]) -> int:
    """Open cases on these assets (the fleet KPI strip, FR-VIS-01)."""
    ids = sorted(set(asset_ids))
    if not ids:
        return 0
    closed = [CaseStatus.CLOSED.value, CaseStatus.CANCELLED.value]
    return int(
        session.scalar(
            select(func.count())
            .select_from(CaseRow)
            .where(CaseRow.asset_id.in_(ids), CaseRow.status.not_in(closed))
        )
        or 0
    )


def assignable_people(session: Session, asset_path: str) -> list[Person]:
    """Who can work on a case on this asset when it is assigned to them (ARC §9.2)."""
    return [
        p
        for p in active_people(session)
        if p.principal.grant(Permission.WORK_ON_CASES, asset_path, assigned=True)
    ]


@dataclass(frozen=True)
class CaseEvent:
    """An activity of any case, for readers that follow the log (the notifier, 8.5)."""

    id: int
    case_id: int
    ts: datetime
    type: ActivityType
    author_id: int | None
    data: dict[str, Any]


def case_events_since(
    session: Session, after_id: int, types: Iterable[ActivityType], limit: int = 1000
) -> list[CaseEvent]:
    rows = session.scalars(
        select(ActivityRow)
        .where(ActivityRow.id > after_id, ActivityRow.type.in_([t.value for t in types]))
        .order_by(ActivityRow.id)
        .limit(limit)
    ).all()
    return [
        CaseEvent(r.id, r.case_id, r.ts, ActivityType(r.type), r.author_id, dict(r.data))
        for r in rows
    ]


def last_case_event_id(session: Session) -> int:
    return int(session.scalar(select(func.max(ActivityRow.id))) or 0)


def overdue_cases(session: Session, today: date) -> list[CaseSummary]:
    """Open cases whose due date has passed (the overdue notification, UCS §6.10)."""
    return list_cases(session, CaseQuery(overdue_on=today, limit=10_000))
