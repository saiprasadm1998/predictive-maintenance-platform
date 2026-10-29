"""Alert services: evaluation each cycle, operator actions, shelving, out of service and the
priority matrix (UC-10, FR-ALM-01, -02, -04, NFR-ACC-01, UCS §6.6).

`evaluate_cycle` runs inside the scoring cycle's transaction, so a score and the alert
changes it causes are stored together or not at all. Every change writes an alert_event
row (the ISA-18.2 log), an audit entry and a NOTIFY; the functions return AlertChanged
events for the caller to publish after commit.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func, literal, select, tuple_
from sqlalchemy.orm import Session

from pmp.alerting.domain import AlertRuleSpec, RuleKind
from pmp.alerting.engine import (
    AlertError,
    AlertState,
    RuleMemory,
    Severity,
    Trigger,
    step,
    transition,
)
from pmp.alerting.models import Alert, AlertEvent, AlertRule, AlertRuleState, PriorityEntry
from pmp.core import Actor, Event, Permission, audit_change, authorize, notify
from pmp.modelling import asset_path, model_asset_code
from pmp.registry import find_asset

MAX_SHELVE = timedelta(days=7)  # UCS §6.6: up to 7 days (configurable maximum)
_OPEN = [s.value for s in AlertState if s is not AlertState.NORMAL]


@dataclass(frozen=True, kw_only=True)
class AlertChanged(Event):
    alert_id: int
    model_id: int
    kind: RuleKind
    tag_id: int | None
    action: str
    previous: AlertState | None
    state: AlertState
    severity: Severity
    priority: str


@dataclass(frozen=True)
class AlertView:
    id: int
    model_id: int
    kind: RuleKind
    tag_id: int | None
    state: AlertState
    severity: Severity
    priority: str | None  # None while out of service (shown as "—", wireframe 02)
    raised_at: datetime
    version_id: int
    condition_active: bool
    ack_at: datetime | None
    shelved_until: datetime | None
    shelve_reason: str | None
    closed_at: datetime | None
    trace: dict[str, Any]


def _view(row: Alert) -> AlertView:
    return AlertView(
        id=row.id,
        model_id=row.model_id,
        kind=RuleKind(row.kind),
        tag_id=row.tag_id,
        state=AlertState(row.state),
        severity=Severity(row.severity),
        priority=None if row.state == AlertState.OUT_OF_SERVICE else row.priority,
        raised_at=row.raised_at,
        version_id=row.version_id,
        condition_active=row.condition_active,
        ack_at=row.ack_at,
        shelved_until=row.shelved_until,
        shelve_reason=row.shelve_reason,
        closed_at=row.closed_at,
        trace=dict(row.trace),
    )


def _rule_spec(row: AlertRule) -> AlertRuleSpec:
    return AlertRuleSpec(
        kind=RuleKind(row.kind),
        warning=row.warning,
        alert=row.alert,
        tag_id=row.tag_id,
        persistence_n=row.persistence_n,
        persistence_m=row.persistence_m,
        on_delay_s=row.on_delay_s,
        deadband=row.deadband,
        clear_cycles=row.clear_cycles,
        enabled=row.enabled,
    )


# ------------------------------------------------------------------ priority (FR-ALM-04)


def get_priority_matrix(session: Session) -> dict[tuple[str, Severity], str]:
    return {
        (r.criticality, Severity(r.severity)): r.priority
        for r in session.scalars(select(PriorityEntry)).all()
    }


def _criticality(session: Session, model_id: int) -> str:
    """The model's asset criticality; an asset without a class counts as C (decision 4.2)."""
    asset = find_asset(session, model_asset_code(session, model_id))
    return asset.criticality.value if asset is not None and asset.criticality else "C"


def _priority(session: Session, model_id: int, severity: Severity) -> str:
    entry = session.get(PriorityEntry, (_criticality(session, model_id), severity.value))
    return entry.priority if entry else "P4"


# ------------------------------------------------------------------ recording changes


def _record(
    session: Session,
    row: Alert,
    action: str,
    previous: AlertState | None,
    ts: datetime,
    actor: Actor,
    comment: str | None = None,
) -> AlertChanged:
    session.flush()
    session.add(
        AlertEvent(
            alert_id=row.id,
            ts=ts,
            action=action,
            from_state=previous.value if previous else None,
            to_state=row.state,
            severity=row.severity,
            priority=row.priority,
            user_id=actor.user_id,
            comment=comment,
        )
    )
    audit_change(
        session,
        actor,
        entity="alert",
        entity_id=row.id,
        action=action,
        before={"state": previous.value} if previous else None,
        after={"state": row.state, "severity": row.severity, "priority": row.priority},
    )
    notify(
        session,
        {
            "type": "alert.changed",
            "alert_id": row.id,
            "model_id": row.model_id,
            "state": row.state,
            "severity": row.severity,
            "priority": row.priority,
        },
    )
    return AlertChanged(
        alert_id=row.id,
        model_id=row.model_id,
        kind=RuleKind(row.kind),
        tag_id=row.tag_id,
        action=action,
        previous=previous,
        state=AlertState(row.state),
        severity=Severity(row.severity),
        priority=row.priority,
    )


def _apply(
    session: Session,
    row: Alert,
    trigger: Trigger,
    ts: datetime,
    actor: Actor,
    comment: str | None = None,
) -> AlertChanged:
    previous = AlertState(row.state)
    row.state = transition(previous, trigger).value
    if row.state == AlertState.NORMAL.value:
        row.closed_at = ts
    return _record(session, row, trigger.value, previous, ts, actor, comment)


# ------------------------------------------------------------------ evaluation per cycle


def evaluate_cycle(
    session: Session,
    *,
    model_id: int,
    version_id: int,
    ts: datetime,
    di: float,
    z: Mapping[int, float],
    trace: Mapping[str, Any],
) -> list[AlertChanged]:
    """Evaluate the model's enabled rules for one scored cycle (status Running).

    `z` holds the standardised residual of each usable sensor (tag ID); sensor rules on
    sensors not in `z` (excluded) are not evaluated this cycle (UCS §6.6). `trace` is
    stored with any alert raised: model version, cycle, inputs, contributions and
    data-quality states (NFR-ACC-01).
    """
    system = Actor.system()
    rules = session.scalars(
        select(AlertRule).where(AlertRule.model_id == model_id, AlertRule.enabled.is_(True))
    ).all()
    if not rules:
        return []
    rule_ids = [r.id for r in rules]
    memories = {
        m.rule_id: m
        for m in session.scalars(
            select(AlertRuleState).where(AlertRuleState.rule_id.in_(rule_ids))
        ).all()
    }
    open_alerts = {
        a.rule_id: a
        for a in session.scalars(
            select(Alert).where(Alert.rule_id.in_(rule_ids), Alert.state.in_(_OPEN))
        ).all()
    }
    changes: list[AlertChanged] = []
    for rule in rules:
        spec = _rule_spec(rule)
        if spec.kind is RuleKind.DI:
            value: float | None = di
        else:
            sensor = z.get(rule.tag_id) if rule.tag_id is not None else None
            value = abs(sensor) if sensor is not None else None
        alert = open_alerts.get(rule.id)
        stored = memories.get(rule.id)
        if value is None or (alert is not None and alert.state == AlertState.OUT_OF_SERVICE):
            continue
        if stored is not None and stored.out_of_service:
            continue  # the model's return to service is handled by sync_out_of_service
        memory = (
            RuleMemory(tuple(stored.levels), stored.clear_count, stored.condition_since)
            if stored
            else RuleMemory()
        )
        active = Severity(alert.severity) if alert is not None and alert.condition_active else None
        result = step(spec, memory, value, ts, active)
        _save_memory(session, rule.id, stored, result.memory, ts)

        if result.raise_to is not None:
            changes += _raise(session, rule, alert, result.raise_to, value, ts, version_id, trace)
        elif result.cleared and alert is not None:
            alert.condition_active = False
            if alert.state in (AlertState.ACTIVE_UNACK, AlertState.ACTIVE_ACK):
                changes.append(_apply(session, alert, Trigger.CLEAR, ts, system))
    return changes


def _save_memory(
    session: Session,
    rule_id: int,
    stored: AlertRuleState | None,
    memory: RuleMemory,
    ts: datetime,
) -> None:
    if stored is None:
        session.add(
            AlertRuleState(
                rule_id=rule_id,
                levels=list(memory.levels),
                clear_count=memory.clear_count,
                condition_since=memory.condition_since,
                last_cycle=ts,
            )
        )
        return
    stored.levels = list(memory.levels)
    stored.clear_count = memory.clear_count
    stored.condition_since = memory.condition_since
    stored.last_cycle = ts


def _raise(
    session: Session,
    rule: AlertRule,
    alert: Alert | None,
    severity: Severity,
    value: float,
    ts: datetime,
    version_id: int,
    trace: Mapping[str, Any],
) -> list[AlertChanged]:
    system = Actor.system()
    priority = _priority(session, rule.model_id, severity)
    full_trace = {
        **dict(trace),
        "rule": {
            "id": rule.id,
            "kind": rule.kind,
            "tag_id": rule.tag_id,
            "warning": rule.warning,
            "alert": rule.alert,
        },
        "value": value,
        "version_id": version_id,
        "cycle": ts.isoformat(),
    }
    if alert is None:
        row = Alert(
            rule_id=rule.id,
            model_id=rule.model_id,
            kind=rule.kind,
            tag_id=rule.tag_id,
            state=AlertState.ACTIVE_UNACK.value,
            severity=severity.value,
            priority=priority,
            condition_active=True,
            raised_at=ts,
            version_id=version_id,
            trace=full_trace,
        )
        session.add(row)
        return [_record(session, row, Trigger.RAISE.value, AlertState.NORMAL, ts, system)]
    if not alert.condition_active:  # RTN-unacknowledged comes back, or a shelved one
        alert.condition_active = True
        alert.severity, alert.priority = severity.value, priority
        alert.trace = full_trace
        if alert.state == AlertState.RTN_UNACK:
            return [_apply(session, alert, Trigger.RAISE, ts, system)]
        return []
    alert.severity, alert.priority = severity.value, priority  # escalation to Alert
    if alert.state == AlertState.ACTIVE_ACK:  # the new severity is acknowledged afresh
        alert.ack_by = alert.ack_at = None
    return [_apply(session, alert, Trigger.ESCALATE, ts, system)]


# ------------------------------------------------------------------ operator actions (UC-10)


def _load(session: Session, alert_ids: Iterable[int]) -> list[Alert]:
    ids = sorted(set(alert_ids))
    rows = session.scalars(select(Alert).where(Alert.id.in_(ids)).order_by(Alert.id)).all()
    missing = sorted(set(ids) - {r.id for r in rows})
    if missing:
        raise AlertError(f"No alert with ID {', '.join(map(str, missing))}")
    return list(rows)


def _authorize_rows(session: Session, actor: Actor, rows: Sequence[Alert]) -> None:
    """Acknowledge and shelve need the right on every alert's asset (ARC §9.2), checked
    before any change: bulk actions are all or nothing."""
    for model_id in sorted({r.model_id for r in rows}):
        code = model_asset_code(session, model_id)
        authorize(actor, Permission.ALERT_ACTIONS, asset_path(session, code), what=code)


def _check_all(rows: Sequence[Alert], trigger: Trigger) -> None:
    """Bulk actions are all or nothing: refuse if any alert cannot take the action."""
    problems = []
    for row in rows:
        try:
            transition(AlertState(row.state), trigger)
        except AlertError as error:
            problems.append(f"alert {row.id}: {error}")
    if problems:
        raise AlertError("; ".join(problems))


def acknowledge(
    session: Session,
    actor: Actor,
    alert_ids: Iterable[int],
    now: datetime,
    comment: str | None = None,
) -> list[AlertChanged]:
    rows = _load(session, alert_ids)
    _authorize_rows(session, actor, rows)
    _check_all(rows, Trigger.ACK)
    changes = []
    for row in rows:
        row.ack_by, row.ack_at = actor.user_id, now
        changes.append(_apply(session, row, Trigger.ACK, now, actor, comment))
    return changes


def shelve(
    session: Session,
    actor: Actor,
    alert_ids: Iterable[int],
    now: datetime,
    *,
    reason: str,
    duration: timedelta,
    max_duration: timedelta = MAX_SHELVE,
) -> list[AlertChanged]:
    """Shelve with a reason, for a limited time (never indefinitely, UC-10)."""
    if not reason.strip():
        raise AlertError("Shelving needs a reason")
    if not timedelta(0) < duration <= max_duration:
        raise AlertError(f"Shelving lasts more than 0 and at most {max_duration}")
    rows = _load(session, alert_ids)
    _authorize_rows(session, actor, rows)
    _check_all(rows, Trigger.SHELVE)
    changes = []
    for row in rows:
        row.shelved_until, row.shelve_reason = now + duration, reason.strip()
        changes.append(_apply(session, row, Trigger.SHELVE, now, actor, reason.strip()))
    return changes


def _end_shelf(session: Session, row: Alert, now: datetime, actor: Actor, why: str) -> AlertChanged:
    trigger = Trigger.EXPIRE_ACTIVE if row.condition_active else Trigger.EXPIRE_NORMAL
    row.shelved_until = row.shelve_reason = None
    if trigger is Trigger.EXPIRE_ACTIVE:
        row.ack_by = row.ack_at = None  # back to Active-Unacknowledged
    return _apply(session, row, trigger, now, actor, why)


def unshelve(
    session: Session, actor: Actor, alert_ids: Iterable[int], now: datetime
) -> list[AlertChanged]:
    """End shelving early: re-evaluated as at expiry (implementation plan, conflict 4.2)."""
    rows = _load(session, alert_ids)
    _authorize_rows(session, actor, rows)
    not_shelved = [r.id for r in rows if r.state != AlertState.SHELVED]
    if not_shelved:
        raise AlertError(f"Not shelved: alert {', '.join(map(str, not_shelved))}")
    return [_end_shelf(session, r, now, actor, "unshelved") for r in rows]


def expire_shelves(session: Session, now: datetime) -> list[AlertChanged]:
    rows = session.scalars(
        select(Alert).where(Alert.state == AlertState.SHELVED, Alert.shelved_until <= now)
    ).all()
    return [_end_shelf(session, r, now, Actor.system(), "shelving expired") for r in rows]


def sync_out_of_service(
    session: Session, in_service: Iterable[int], now: datetime
) -> list[AlertChanged]:
    """Out of service follows the model (UC-10: set by model state, not by users; UCS
    Figure 6: any state, Normal included, moves to Out of service when the model is
    paused or retired). Rules are taken out of service with their alerts, and their
    persistence memory is cleared, so when the model is deployed again every rule starts
    counting afresh and its alerts return to Normal.

    Only rules that have run at least once are affected: a draft model's rules never
    were in service.
    """
    deployed = set(in_service)
    system = Actor.system()
    changes = []
    for row in session.scalars(select(Alert).where(Alert.state.in_(_OPEN))).all():
        if row.state == AlertState.OUT_OF_SERVICE:
            if row.model_id in deployed:
                row.condition_active = False
                changes.append(_apply(session, row, Trigger.RETURN_TO_SERVICE, now, system))
        elif row.model_id not in deployed:
            row.condition_active = False
            row.shelved_until = row.shelve_reason = None
            changes.append(_apply(session, row, Trigger.OUT_OF_SERVICE, now, system))

    memories = session.execute(
        select(AlertRuleState, AlertRule.model_id).join(
            AlertRule, AlertRule.id == AlertRuleState.rule_id
        )
    ).all()
    for memory, model_id in memories:
        out = model_id not in deployed
        if out != memory.out_of_service:
            memory.out_of_service = out
            memory.levels, memory.clear_count, memory.condition_since = [], 0, None
    return changes


def close_rule_alerts(
    session: Session, rule_ids: Iterable[int], actor: Actor, now: datetime, why: str
) -> list[AlertChanged]:
    """Close the open alerts of rules that are being removed or switched off: they could
    never clear otherwise, and a sensor alert would hold the band (plan 6.7). The rules'
    persistence memory is cleared, so a rule switched on again counts afresh."""
    ids = list(rule_ids)
    if not ids:
        return []
    rows = session.scalars(
        select(Alert).where(Alert.rule_id.in_(ids), Alert.state.in_(_OPEN))
    ).all()
    changes = []
    for row in rows:
        row.condition_active = False
        row.shelved_until = row.shelve_reason = None
        changes.append(_apply(session, row, Trigger.RULE_REMOVED, now, actor, why))
    for memory in session.scalars(
        select(AlertRuleState).where(AlertRuleState.rule_id.in_(ids))
    ).all():
        memory.levels, memory.clear_count, memory.condition_since = [], 0, None
    return changes


def rule_states(session: Session, model_id: int) -> dict[int, AlertState]:
    """Each of a model's rules in Figure 6 terms: its open alert's state, Out of service
    while the model is not in service, otherwise Normal."""
    rules = session.scalars(select(AlertRule.id).where(AlertRule.model_id == model_id)).all()
    states = dict.fromkeys(rules, AlertState.NORMAL)
    for memory in session.scalars(
        select(AlertRuleState).where(AlertRuleState.rule_id.in_(rules))
    ).all():
        if memory.out_of_service:
            states[memory.rule_id] = AlertState.OUT_OF_SERVICE
    for alert in session.scalars(
        select(Alert).where(Alert.rule_id.in_(rules), Alert.state.in_(_OPEN))
    ).all():
        if alert.rule_id is not None:
            states[alert.rule_id] = AlertState(alert.state)
    return states


def set_priority(
    session: Session,
    actor: Actor,
    criticality: str,
    severity: Severity,
    priority: str,
    now: datetime,
) -> list[AlertChanged]:
    """Change one matrix cell (FR-ALM-04): audited, and open alerts it covers are
    re-prioritised."""
    authorize(actor, Permission.MODELS, what="the priority matrix")  # decision 5.1
    if criticality not in ("A", "B", "C") or priority not in ("P1", "P2", "P3", "P4"):
        raise AlertError("Criticality is A, B or C and priority P1 to P4")
    entry = session.get(PriorityEntry, (criticality, severity.value))
    before = entry.priority if entry else None
    if entry is None:
        session.add(
            PriorityEntry(criticality=criticality, severity=severity.value, priority=priority)
        )
    else:
        entry.priority = priority
    audit_change(
        session,
        actor,
        entity="priority_matrix",
        entity_id=f"{criticality}:{severity.value}",
        action="update",
        before={"priority": before},
        after={"priority": priority},
    )
    changes = []
    for row in session.scalars(
        select(Alert).where(Alert.state.in_(_OPEN), Alert.severity == severity.value)
    ).all():
        if _criticality(session, row.model_id) == criticality and row.priority != priority:
            row.priority = priority
            changes.append(_record(session, row, "reprioritise", AlertState(row.state), now, actor))
    return changes


# ------------------------------------------------------------------ queries


@dataclass(frozen=True)
class AlertQuery:
    """Filters for the alert list (FR-ALM-03, ARC §7.3). Empty tuples mean "any"."""

    open_only: bool = True
    model_ids: tuple[int, ...] | None = None  # None: all models (scope already applied)
    states: tuple[AlertState, ...] = ()
    priorities: tuple[str, ...] = ()
    severities: tuple[Severity, ...] = ()
    kind: RuleKind | None = None
    raised_after: datetime | None = None  # age filters (FR-ALM-03)
    raised_before: datetime | None = None
    sort: str = "default"


_UNACK = (AlertState.ACTIVE_UNACK.value, AlertState.RTN_UNACK.value)
SORTS = ("default", "newest", "oldest", "priority", "severity")


def _sort_columns(sort: str = "default") -> tuple[tuple[Any, str], ...]:
    """The list order as (expression, kind) pairs, all ascending so keyset paging is one
    row comparison. PDS §4.2 default: unacknowledged first, then priority, then age, out
    of service last; the others let the user sort by age, priority or severity."""
    out_of_service = case((Alert.state == AlertState.OUT_OF_SERVICE.value, 1), else_=0)
    acknowledged = case((Alert.state.in_(_UNACK), 0), else_=1)
    severity = case((Alert.severity == Severity.ALERT.value, 0), else_=1)
    epoch = func.extract("epoch", Alert.raised_at)
    by = {
        "default": (
            (out_of_service, "int"),
            (acknowledged, "int"),
            (Alert.priority, "str"),
            (epoch, "float"),
        ),
        "newest": ((-epoch, "float"),),
        "oldest": ((epoch, "float"),),
        "priority": ((Alert.priority, "str"), (epoch, "float")),
        "severity": ((severity, "int"), (Alert.priority, "str"), (epoch, "float")),
    }[sort]
    last = (-Alert.id, "int") if sort == "newest" else (Alert.id, "int")
    return (*by, last)


_CAST: dict[str, Any] = {"int": int, "str": str, "float": float}


def search_alerts(
    session: Session,
    query: AlertQuery = AlertQuery(),  # noqa: B008  (frozen)
    *,
    after: Sequence[Any] | None = None,
    limit: int = 100,
) -> tuple[list[AlertView], list[Any] | None]:
    """One page of alerts in list order, and the sort key to continue after (keyset
    paging, done in the database: FR-ALM-03 asks for 1,000 alerts filtered in under 1 s)."""
    if query.sort not in SORTS:
        raise AlertError(f"Sort by one of {', '.join(SORTS)}")
    columns = _sort_columns(query.sort)
    exprs = [e for e, _ in columns]
    stmt = select(Alert, *(e.label(f"sort_{i}") for i, e in enumerate(exprs)))
    if query.open_only:
        stmt = stmt.where(Alert.state.in_(_OPEN))
    if query.model_ids is not None:
        stmt = stmt.where(Alert.model_id.in_(query.model_ids))
    if query.states:
        stmt = stmt.where(Alert.state.in_([s.value for s in query.states]))
    if query.priorities:
        stmt = stmt.where(Alert.priority.in_(query.priorities))
    if query.severities:
        stmt = stmt.where(Alert.severity.in_([s.value for s in query.severities]))
    if query.kind is not None:
        stmt = stmt.where(Alert.kind == query.kind.value)
    if query.raised_after is not None:
        stmt = stmt.where(Alert.raised_at >= query.raised_after)
    if query.raised_before is not None:
        stmt = stmt.where(Alert.raised_at < query.raised_before)
    if after is not None:
        if len(after) != len(columns):
            raise AlertError("The cursor belongs to another sort order")
        values = [literal(_CAST[kind](v)) for (_, kind), v in zip(columns, after, strict=True)]
        stmt = stmt.where(tuple_(*exprs) > tuple_(*values))
    rows = session.execute(stmt.order_by(*exprs).limit(limit + 1)).all()
    more = len(rows) > limit
    rows = rows[:limit]
    views = [_view(row[0]) for row in rows]
    if not more or not rows:
        return views, None
    return views, [
        _CAST[kind](value) for (_, kind), value in zip(columns, rows[-1][1:], strict=True)
    ]


def list_alerts(
    session: Session, *, open_only: bool = True, model_id: int | None = None
) -> list[AlertView]:
    """Every alert in list order (for the command line)."""
    query = AlertQuery(open_only=open_only, model_ids=(model_id,) if model_id else None)
    views, _ = search_alerts(session, query, limit=1_000_000)
    return views


def alert_counts(
    session: Session, model_ids: Sequence[int] | None = None
) -> dict[str, dict[str, int]]:
    """Open alerts by priority, split into unacknowledged and all (fleet KPIs, SCR-01).
    Out-of-service alerts are not counted: they have no priority."""
    stmt = select(Alert.priority, func.count(), func.count().filter(Alert.state.in_(_UNACK))).where(
        Alert.state.in_(_OPEN), Alert.state != AlertState.OUT_OF_SERVICE.value
    )
    if model_ids is not None:
        stmt = stmt.where(Alert.model_id.in_(model_ids))
    rows = session.execute(stmt.group_by(Alert.priority)).all()
    return {
        "open": {p: int(n) for p, n, _ in rows},
        "unacknowledged": {p: int(u) for p, _, u in rows if u},
    }


def persistence(session: Session, alert_ids: Iterable[int]) -> dict[int, tuple[int, int]]:
    """For each alert, how many of its rule's last m cycles met its severity, and m
    ("5 of 5", SCR-02). Alerts whose rule is gone or has no memory yet are left out."""
    ids = sorted(set(alert_ids))
    if not ids:
        return {}
    rows = session.execute(
        select(Alert.id, Alert.severity, AlertRule.persistence_m, AlertRuleState.levels)
        .join(AlertRule, AlertRule.id == Alert.rule_id)
        .join(AlertRuleState, AlertRuleState.rule_id == Alert.rule_id)
        .where(Alert.id.in_(ids))
    ).all()
    out = {}
    for alert_id, severity, m, levels in rows:
        at_least = 2 if severity == Severity.ALERT.value else 1
        recent = list(levels or [])[-m:]
        out[int(alert_id)] = (sum(1 for x in recent if x >= at_least), int(m))
    return out


def cleared_times(session: Session, alert_ids: Iterable[int]) -> dict[int, datetime]:
    """When each alert's condition last returned to normal (the end of its bar on a trend,
    SCR-03). Only meaningful while the condition is inactive."""
    ids = sorted(set(alert_ids))
    if not ids:
        return {}
    rows = session.execute(
        select(AlertEvent.alert_id, func.max(AlertEvent.ts))
        .where(AlertEvent.alert_id.in_(ids), AlertEvent.action == Trigger.CLEAR.value)
        .group_by(AlertEvent.alert_id)
    ).all()
    return {int(a): t for a, t in rows}


def alerts_raised_since(session: Session, since: datetime) -> dict[int, int]:
    """Alerts raised per model since a time (the alert rate on the model list, SCR-10)."""
    rows = session.execute(
        select(Alert.model_id, func.count())
        .where(Alert.raised_at >= since)
        .group_by(Alert.model_id)
    ).all()
    return {int(m): int(n) for m, n in rows}


def open_alerts_by_model(session: Session) -> dict[int, int]:
    """Open alerts per model, out of service left out (active-alert counts, SCR-01)."""
    rows = session.execute(
        select(Alert.model_id, func.count())
        .where(Alert.state.in_(_OPEN), Alert.state != AlertState.OUT_OF_SERVICE.value)
        .group_by(Alert.model_id)
    ).all()
    return {int(m): int(n) for m, n in rows}


def get_alerts(session: Session, alert_ids: Iterable[int]) -> list[AlertView]:
    """Alerts by ID, in ID order; AlertError names any that do not exist."""
    return [_view(r) for r in _load(session, alert_ids)]


def get_alert(session: Session, alert_id: int) -> AlertView:
    return _view(_load(session, [alert_id])[0])


def alert_history(session: Session, alert_id: int) -> list[AlertEvent]:
    return list(
        session.scalars(
            select(AlertEvent).where(AlertEvent.alert_id == alert_id).order_by(AlertEvent.id)
        ).all()
    )


@dataclass(frozen=True)
class AlertEventView:
    """One entry of the alert event log (ISA-18.2), for readers that follow it."""

    id: int
    alert_id: int
    ts: datetime  # the cycle (raise, escalate) or the moment of the action
    action: str
    to_state: str
    severity: str
    priority: str


def alert_events_since(
    session: Session, after_id: int, actions: Iterable[str], limit: int = 1000
) -> list[AlertEventView]:
    """Events after `after_id`, oldest first (the notifier's cursor, plan 8.5)."""
    rows = session.scalars(
        select(AlertEvent)
        .where(AlertEvent.id > after_id, AlertEvent.action.in_(list(actions)))
        .order_by(AlertEvent.id)
        .limit(limit)
    ).all()
    return [
        AlertEventView(r.id, r.alert_id, r.ts, r.action, r.to_state, r.severity, r.priority)
        for r in rows
    ]


def last_alert_event_id(session: Session) -> int:
    return int(session.scalar(select(func.max(AlertEvent.id))) or 0)


def active_sensor_alerts(session: Session, model_id: int) -> dict[int, Severity]:
    """Sensor alerts whose condition is active, by tag: they set the band (UCS §6.5,
    decision for 2.3)."""
    rows = session.scalars(
        select(Alert).where(
            Alert.model_id == model_id,
            Alert.kind == RuleKind.SENSOR.value,
            Alert.state.in_(_OPEN),
            Alert.condition_active.is_(True),
        )
    ).all()
    return {r.tag_id: Severity(r.severity) for r in rows if r.tag_id is not None}
