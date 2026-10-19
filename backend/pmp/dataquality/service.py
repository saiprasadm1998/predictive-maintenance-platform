"""Data-quality services: rule sets, sensor evaluation, statuses and preview (UC-04).

Rule overrides are kept per scope and versioned: a save adds a new version and writes an
audit entry; nothing is overwritten. The effective parameters for a tag are the UCS
§6.1 defaults, then the global overrides, then the overrides for the tag's asset-type
role, then the tag's own overrides (implementation plan, decision for 2.1).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import numpy as np
import numpy.typing as npt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pmp.core import Actor, EventBus, audit_change
from pmp.dataquality.domain import (
    PREVIEW_WARN_SHARE,
    RULE_ORDER,
    DataQualityError,
    Effect,
    Ne107,
    Rule,
    RuleParams,
    Samples,
    SensorConfig,
    SensorState,
    SensorStatusChanged,
    evaluate_rules,
    evaluate_sensor,
    parse_overrides,
    resolve_params,
    state_for,
    to_ns,
)
from pmp.dataquality.models import DqRule, SensorExclusion, SensorStatus
from pmp.ingestion import read_last_samples, read_samples
from pmp.registry import RegistryError, TagView, get_asset_type, get_tags, list_tags

_NS = 1_000_000_000


# ------------------------------------------------------------------ scopes and rule sets


class ScopeKind(StrEnum):
    GLOBAL = "global"
    ROLE = "role"
    TAG = "tag"


@dataclass(frozen=True)
class RuleScope:
    """Where a set of overrides applies: everywhere, one asset-type role, or one tag."""

    kind: ScopeKind
    key: str = ""

    @classmethod
    def everywhere(cls) -> RuleScope:
        return cls(ScopeKind.GLOBAL)

    @classmethod
    def role(cls, asset_type: str, role: str) -> RuleScope:
        return cls(ScopeKind.ROLE, f"{asset_type}/{role}")

    @classmethod
    def tag(cls, tag_id: int) -> RuleScope:
        return cls(ScopeKind.TAG, str(tag_id))

    def covers(self, tag: TagView) -> bool:
        if self.kind is ScopeKind.GLOBAL:
            return True
        if self.kind is ScopeKind.ROLE:
            return _role_key(tag) == self.key
        return str(tag.id) == self.key

    def __str__(self) -> str:
        return self.kind.value if self.kind is ScopeKind.GLOBAL else f"{self.kind} {self.key}"


@dataclass(frozen=True)
class RuleSetView:
    scope: RuleScope
    version: int  # 0: nothing saved yet
    overrides: dict[str, Any]
    comment: str = ""
    created_at: datetime | None = None


def _role_key(tag: TagView) -> str | None:
    if tag.asset_type_code and tag.role_code:
        return f"{tag.asset_type_code}/{tag.role_code}"
    return None


def _check_scope(session: Session, scope: RuleScope) -> None:
    if scope.kind is ScopeKind.GLOBAL:
        if scope.key:
            raise DataQualityError("The global scope has no key")
    elif scope.kind is ScopeKind.ROLE:
        asset_type, _, role = scope.key.partition("/")
        try:
            type_view = get_asset_type(session, asset_type)
        except RegistryError:
            raise DataQualityError(f"Asset type {asset_type!r} does not exist") from None
        if role not in {r.code for r in type_view.roles}:
            raise DataQualityError(f"Asset type {asset_type!r} has no role {role!r}")
    elif not scope.key.isdigit() or not get_tags(session, [int(scope.key)]):
        raise DataQualityError(f"Tag {scope.key!r} does not exist")


def _current_rows(session: Session) -> dict[tuple[str, str], DqRule]:
    """The latest version for every scope, in one query."""
    latest = (
        select(DqRule.scope, DqRule.scope_key, func.max(DqRule.version).label("version"))
        .group_by(DqRule.scope, DqRule.scope_key)
        .subquery()
    )
    rows = session.scalars(
        select(DqRule).join(
            latest,
            (DqRule.scope == latest.c.scope)
            & (DqRule.scope_key == latest.c.scope_key)
            & (DqRule.version == latest.c.version),
        )
    ).all()
    return {(r.scope, r.scope_key): r for r in rows}


def _view(scope: RuleScope, row: DqRule | None) -> RuleSetView:
    if row is None:
        return RuleSetView(scope, 0, {})
    return RuleSetView(scope, row.version, dict(row.params), row.comment, row.created_at)


def get_rule_set(session: Session, scope: RuleScope) -> RuleSetView:
    """The current overrides for a scope (empty if nothing was saved)."""
    row = session.scalars(
        select(DqRule)
        .where(DqRule.scope == scope.kind.value, DqRule.scope_key == scope.key)
        .order_by(DqRule.version.desc())
        .limit(1)
    ).one_or_none()
    return _view(scope, row)


def list_rule_versions(session: Session, scope: RuleScope) -> list[RuleSetView]:
    """Every saved version for a scope, newest first."""
    rows = session.scalars(
        select(DqRule)
        .where(DqRule.scope == scope.kind.value, DqRule.scope_key == scope.key)
        .order_by(DqRule.version.desc())
    ).all()
    return [_view(scope, r) for r in rows]


def save_rule_set(
    session: Session,
    actor: Actor,
    scope: RuleScope,
    overrides: Mapping[str, Any],
    comment: str = "",
) -> RuleSetView:
    """Replace a scope's overrides with a new version. Rules apply from the next cycle.

    Saving the same overrides again creates no new version. An empty mapping removes all
    overrides for the scope (it inherits again), as a new version.
    """
    _check_scope(session, scope)
    parsed = parse_overrides(overrides)
    current = get_rule_set(session, scope)
    if current.version and current.overrides == parsed:
        return current
    row = DqRule(
        scope=scope.kind.value,
        scope_key=scope.key,
        version=current.version + 1,
        params=parsed,
        comment=comment,
        created_by=actor.user_id,
    )
    session.add(row)
    session.flush()
    audit_change(
        session,
        actor,
        entity="dq_rule",
        entity_id=f"{scope.kind.value}:{scope.key}",
        action="save",
        before=(
            {"version": current.version, "params": current.overrides} if current.version else None
        ),
        after={"version": row.version, "params": parsed, "comment": comment},
    )
    return _view(scope, row)


def _params_for(tag: TagView, rows: Mapping[tuple[str, str], Any]) -> RuleParams:
    def overrides(kind: ScopeKind, key: str | None) -> Mapping[str, Any]:
        if key is None:
            return {}
        row = rows.get((kind.value, key))
        if row is None:
            return {}
        return row if isinstance(row, Mapping) else row.params

    return resolve_params(
        overrides(ScopeKind.GLOBAL, ""),
        overrides(ScopeKind.ROLE, _role_key(tag)),
        overrides(ScopeKind.TAG, str(tag.id)),
    )


def effective_params(session: Session, tag_id: int) -> RuleParams:
    """The parameters the rules use for one tag right now."""
    tags = get_tags(session, [tag_id])
    if not tags:
        raise DataQualityError(f"Tag {tag_id} does not exist")
    return _params_for(tags[0], _current_rows(session))


# ------------------------------------------------------------------ evaluation


@dataclass(frozen=True)
class Reference:
    """Training statistics for one sensor, supplied by scoring once a model is deployed."""

    range: float  # P99 - P1 of cleansed training data
    std: float | None = None


def _config(tag: TagView, reference: Reference | None) -> SensorConfig:
    return SensorConfig(
        range_lo=tag.range_lo,
        range_hi=tag.range_hi,
        interval_s=tag.interval_s,
        reference_range=reference.range if reference else None,
        training_std=reference.std if reference else None,
    )


def _exclusions(
    session: Session, tag_ids: Iterable[int], start: datetime, end: datetime
) -> dict[int, list[tuple[datetime, datetime]]]:
    """Manual exclusion periods overlapping [start, end] per tag (UC-14)."""
    ids = list(tag_ids)
    periods: dict[int, list[tuple[datetime, datetime]]] = {}
    if not ids:
        return periods
    rows = session.scalars(
        select(SensorExclusion).where(
            SensorExclusion.tag_id.in_(ids),
            SensorExclusion.starts_at <= end,
            SensorExclusion.expires_at > start,
        )
    ).all()
    for row in rows:
        stop = min(row.expires_at, row.cleared_at) if row.cleared_at else row.expires_at
        if stop > row.starts_at:
            periods.setdefault(row.tag_id, []).append((row.starts_at, stop))
    return periods


def _excluded_mask(
    cycle_ns: npt.NDArray[np.int64], periods: Iterable[tuple[datetime, datetime]]
) -> npt.NDArray[np.bool_]:
    mask = np.zeros(len(cycle_ns), dtype=bool)
    for begin, stop in periods:
        b, s = to_ns([begin, stop])
        mask |= (cycle_ns >= b) & (cycle_ns < s)
    return mask


def _tags(session: Session, tag_ids: Iterable[int] | None) -> list[TagView]:
    return list_tags(session) if tag_ids is None else get_tags(session, tag_ids)


def evaluate_sensors(
    session: Session,
    at: datetime,
    tag_ids: Iterable[int] | None = None,
    *,
    references: Mapping[int, Reference] | None = None,
    bus: EventBus | None = None,
) -> dict[int, SensorState]:
    """Evaluate the rules for each tag at cycle time `at` and store the statuses.

    `SensorStatusChanged` is published for every tag whose status or rule changed. The
    scoring cycle (4.1) calls this with the deployed models' training statistics.
    """
    tags = _tags(session, tag_ids)
    rows = _current_rows(session)
    excl = _exclusions(session, (t.id for t in tags), at, at)
    refs = references or {}
    states: dict[int, SensorState] = {}
    events: list[SensorStatusChanged] = []
    for tag in tags:
        params = _params_for(tag, rows)
        samples = Samples.from_rows(read_last_samples(session, tag.id, at, params.flatline_window))
        excluded = bool(_excluded_mask(to_ns(at), excl.get(tag.id, [])).any())
        state = evaluate_sensor(samples, _config(tag, refs.get(tag.id)), params, at, excluded)
        states[tag.id] = state

        stored = session.get(SensorStatus, tag.id)
        if stored is None:
            session.add(
                SensorStatus(
                    tag_id=tag.id,
                    status=state.status.value,
                    rule=state.rule.value,
                    effect=state.effect.value,
                    since=at,
                    evaluated_at=at,
                )
            )
            events.append(
                SensorStatusChanged(
                    tag_id=tag.id, previous=None, status=state.status, rule=state.rule
                )
            )
            continue
        if (stored.status, stored.rule) != (state.status.value, state.rule.value):
            events.append(
                SensorStatusChanged(
                    tag_id=tag.id,
                    previous=Ne107(stored.status),
                    status=state.status,
                    rule=state.rule,
                )
            )
            stored.status, stored.rule, stored.since = state.status.value, state.rule.value, at
        stored.effect = state.effect.value
        stored.evaluated_at = at
    session.flush()
    if bus is not None:
        for event in events:
            bus.publish(event)
    return states


@dataclass(frozen=True)
class SensorStatusView:
    tag_id: int
    source: str
    source_name: str
    asset_code: str
    status: Ne107
    rule: Rule
    effect: Effect
    since: datetime
    evaluated_at: datetime


def get_sensor_statuses(
    session: Session, tag_ids: Iterable[int] | None = None
) -> list[SensorStatusView]:
    """Stored statuses: every sensor shows one category and the rule that set it."""
    tags = {t.id: t for t in _tags(session, tag_ids)}
    rows = session.scalars(select(SensorStatus).where(SensorStatus.tag_id.in_(list(tags)))).all()
    views = [
        SensorStatusView(
            tag_id=r.tag_id,
            source=tags[r.tag_id].source,
            source_name=tags[r.tag_id].source_name,
            asset_code=tags[r.tag_id].asset_code,
            status=Ne107(r.status),
            rule=Rule(r.rule),
            effect=Effect(r.effect),
            since=r.since,
            evaluated_at=r.evaluated_at,
        )
        for r in rows
    ]
    return sorted(views, key=lambda v: (v.asset_code, v.source_name))


# ------------------------------------------------------------------ preview


@dataclass(frozen=True)
class TagPreview:
    tag_id: int
    source_name: str
    asset_code: str
    cycles: int
    by_rule: dict[Rule, int]
    excluded: int  # cycles in which the sensor would not be used for scoring

    @property
    def excluded_share(self) -> float:
        return self.excluded / self.cycles if self.cycles else 0.0


@dataclass(frozen=True)
class PreviewReport:
    scope: RuleScope
    start: datetime
    end: datetime
    tags: list[TagPreview]

    @property
    def cycles(self) -> int:
        return sum(t.cycles for t in self.tags)

    @property
    def excluded_share(self) -> float:
        cycles = self.cycles
        return sum(t.excluded for t in self.tags) / cycles if cycles else 0.0

    @property
    def over_limit(self) -> list[TagPreview]:
        """Tags where more than 20 % of cycles would be excluded (UC-04 3a)."""
        return [t for t in self.tags if t.excluded_share > PREVIEW_WARN_SHARE]

    @property
    def warning(self) -> bool:
        return bool(self.over_limit)

    def summary(self) -> str:
        lines = [
            f"Preview for {self.scope}: {len(self.tags)} tags, "
            f"{self.start:%Y-%m-%d %H:%M} to {self.end:%Y-%m-%d %H:%M} UTC",
            f"{'tag':<28} {'asset':<10} {'excluded':>9}  rules that fired",
        ]
        for t in self.tags:
            fired = ", ".join(
                f"{rule.value} {n / t.cycles:.1%}"
                for rule, n in t.by_rule.items()
                if rule is not Rule.NONE and n and t.cycles
            )
            lines.append(
                f"{t.source_name:<28} {t.asset_code:<10} {t.excluded_share:>8.1%}  {fired or '-'}"
            )
        lines.append(f"Overall excluded: {self.excluded_share:.1%} of {self.cycles} sensor-cycles")
        if self.warning:
            names = ", ".join(t.source_name for t in self.over_limit)
            lines.append(
                f"WARNING: more than {PREVIEW_WARN_SHARE:.0%} of cycles excluded for: {names}"
            )
        return "\n".join(lines)


def cycle_grid(start: datetime, end: datetime, cycle_s: int) -> npt.NDArray[np.int64]:
    """Cycle times in [start, end) as epoch nanoseconds, on whole multiples of cycle_s."""
    step = cycle_s * _NS
    start_ns, end_ns = (int(x) for x in to_ns([start, end]))
    first = -(-start_ns // step) * step  # first cycle time on or after start
    return np.arange(first, end_ns, step, dtype=np.int64)


def _samples_for(
    session: Session, tag_id: int, start: datetime, end: datetime, params: RuleParams
) -> Samples:
    """Samples in [start, end) plus enough before start for the stale, spike and flatline
    rules at the first cycle."""
    before = read_last_samples(
        session, tag_id, start - timedelta(microseconds=1), params.flatline_window
    )
    return Samples.from_rows(before + read_samples(session, tag_id, start, end))


def preview_rules(
    session: Session,
    scope: RuleScope,
    overrides: Mapping[str, Any] | None = None,
    *,
    days: int = 30,
    end: datetime | None = None,
    cycle_s: int = 60,
    references: Mapping[int, Reference] | None = None,
) -> PreviewReport:
    """The effect of the rules on the last `days` of data, one cycle per `cycle_s` (UC-04).

    With `overrides`, the scope's overrides are replaced by them for the preview only,
    so the effect of a change can be seen before it is saved.
    """
    _check_scope(session, scope)
    end = end or datetime.now(UTC)
    start = end - timedelta(days=days)
    rows: dict[tuple[str, str], Any] = {k: v.params for k, v in _current_rows(session).items()}
    if overrides is not None:
        rows[(scope.kind.value, scope.key)] = parse_overrides(overrides)
    tags = [t for t in list_tags(session) if scope.covers(t)]

    cycle_ns = cycle_grid(start, end, cycle_s)
    excl = _exclusions(session, (t.id for t in tags), start, end)
    refs = references or {}

    previews = []
    for tag in tags:
        params = _params_for(tag, rows)
        samples = _samples_for(session, tag.id, start, end, params)
        codes = evaluate_rules(
            samples,
            _config(tag, refs.get(tag.id)),
            params,
            cycle_ns,
            _excluded_mask(cycle_ns, excl.get(tag.id, [])),
        )
        counts = np.bincount(codes, minlength=len(RULE_ORDER))
        by_rule = {rule: int(counts[i]) for i, rule in enumerate(RULE_ORDER)}
        previews.append(
            TagPreview(
                tag_id=tag.id,
                source_name=tag.source_name,
                asset_code=tag.asset_code,
                cycles=len(cycle_ns),
                by_rule=by_rule,
                excluded=sum(n for r, n in by_rule.items() if not state_for(r, params).usable),
            )
        )
    return PreviewReport(scope, start, end, previews)


# ------------------------------------------------------------------ series for training


@dataclass(frozen=True)
class SeriesAssessment:
    """One tag on a cycle grid: the value scoring would use and whether it is usable."""

    tag_id: int
    values: npt.NDArray[np.float64]  # latest sample at or before each cycle; NaN if none
    usable: npt.NDArray[np.bool_]  # the rules' effect is "used" or "used, flagged"
    rules: npt.NDArray[np.int8]  # index into the rule order, for reports


def assess_series(
    session: Session,
    tag_ids: Iterable[int],
    cycle_ns: npt.NDArray[np.int64],
    *,
    references: Mapping[int, Reference] | None = None,
) -> dict[int, SeriesAssessment]:
    """Each tag's held values and usability at every cycle time, exactly as scoring sees
    them (sample-and-hold, the rules, manual exclusions). Used to assemble training and
    validation data (UCS §6.4: samples failing the rules, other than Uncertain, are
    removed)."""
    if len(cycle_ns) == 0:
        return {}
    start = datetime.fromtimestamp(int(cycle_ns[0]) / 1e9, tz=UTC)
    end = datetime.fromtimestamp(int(cycle_ns[-1]) / 1e9, tz=UTC) + timedelta(microseconds=1)
    tags = _tags(session, tag_ids)
    rows = _current_rows(session)
    excl = _exclusions(session, (t.id for t in tags), start, end)
    refs = references or {}
    result = {}
    for tag in tags:
        params = _params_for(tag, rows)
        samples = _samples_for(session, tag.id, start, end, params)
        codes = evaluate_rules(
            samples,
            _config(tag, refs.get(tag.id)),
            params,
            cycle_ns,
            _excluded_mask(cycle_ns, excl.get(tag.id, [])),
        )
        idx = np.searchsorted(samples.ts, cycle_ns, side="right") - 1
        values = np.where(idx >= 0, samples.value[np.maximum(idx, 0)], np.nan)
        if len(samples.value) == 0:
            values = np.full(len(cycle_ns), np.nan)
        usable_by_rule = np.array([state_for(r, params).usable for r in RULE_ORDER])
        result[tag.id] = SeriesAssessment(tag.id, values, usable_by_rule[codes], codes)
    return result
