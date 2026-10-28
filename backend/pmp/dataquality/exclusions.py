"""Manual sensor exclusions and overrides (UC-14, FR-DQ-04, -05, plan 8.1).

- Exclude: the sensor's status is Function check and it is left out of every model, from
  the next cycle until the expiry (or until ended).
- Override: an automatic status (out of range, flatline, spike, uncertain quality) is
  forced to Good, for example a flatline on a sensor that is genuinely constant. Bad
  source quality and a sensor without data cannot be overridden (FR-ING-05).

Both need a reason and an expiry, end on their own at the expiry, and are audited. A tag
has at most one active entry: a new one ends the previous.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from pmp.core import Actor, Permission, audit_change, authorize
from pmp.dataquality.domain import DataQualityError
from pmp.dataquality.models import SensorExclusion
from pmp.registry import get_asset_by_id, get_tags

MAX_DURATION = timedelta(days=90)  # decision 8.1: an expiry is required, and bounded
MAX_REASON = 500


class ExclusionKind(StrEnum):
    EXCLUDE = "exclude"
    OVERRIDE = "override"


@dataclass(frozen=True)
class ExclusionView:
    id: int
    tag_id: int
    source_name: str
    asset_code: str
    kind: ExclusionKind
    reason: str
    starts_at: datetime
    expires_at: datetime
    ended_at: datetime | None  # ended by hand before its expiry
    created_by: int | None

    def active_at(self, at: datetime) -> bool:
        stop = min(self.expires_at, self.ended_at) if self.ended_at else self.expires_at
        return self.starts_at <= at < stop


def _view(row: SensorExclusion, names: dict[int, tuple[str, str]]) -> ExclusionView:
    source_name, asset_code = names.get(row.tag_id, ("?", "?"))
    return ExclusionView(
        id=row.id,
        tag_id=row.tag_id,
        source_name=source_name,
        asset_code=asset_code,
        kind=ExclusionKind(row.kind),
        reason=row.reason,
        starts_at=row.starts_at,
        expires_at=row.expires_at,
        ended_at=row.cleared_at,
        created_by=row.created_by,
    )


def _names(session: Session, tag_ids: Iterable[int]) -> dict[int, tuple[str, str]]:
    return {t.id: (t.source_name, t.asset_code) for t in get_tags(session, list(set(tag_ids)))}


def _active_rows(session: Session, tag_ids: list[int], at: datetime) -> list[SensorExclusion]:
    return list(
        session.scalars(
            select(SensorExclusion).where(
                SensorExclusion.tag_id.in_(tag_ids),
                SensorExclusion.starts_at <= at,
                SensorExclusion.expires_at > at,
                or_(SensorExclusion.cleared_at.is_(None), SensorExclusion.cleared_at > at),
            )
        ).all()
    )


def _snapshot(row: SensorExclusion) -> dict[str, object]:
    return {
        "tag_id": row.tag_id,
        "kind": row.kind,
        "reason": row.reason,
        "starts_at": row.starts_at.isoformat(),
        "expires_at": row.expires_at.isoformat(),
        "ended_at": row.cleared_at.isoformat() if row.cleared_at else None,
    }


def add_exclusion(
    session: Session,
    actor: Actor,
    tag_id: int,
    kind: ExclusionKind,
    reason: str,
    until: datetime,
    now: datetime,
) -> ExclusionView:
    """Exclude a sensor or override its status from now until `until`."""
    tags = get_tags(session, [tag_id])
    if not tags:  # authorised first, so a refused user learns nothing (decision 6.7)
        authorize(actor, Permission.SENSOR_EXCLUSION, None, what="sensor exclusions")
        raise DataQualityError(f"Tag {tag_id} does not exist")
    tag = tags[0]
    authorize(
        actor,
        Permission.SENSOR_EXCLUSION,
        get_asset_by_id(session, tag.asset_id).path,
        what=f"sensor exclusions on {tag.asset_code}",
    )
    text = reason.strip()
    if not text:
        raise DataQualityError("Give a reason")
    if len(text) > MAX_REASON:
        raise DataQualityError(f"The reason may have at most {MAX_REASON} characters")
    if until.tzinfo is None:
        raise DataQualityError("The expiry needs a time zone")
    if not until > now:
        raise DataQualityError("The expiry must be in the future")
    if until - now > MAX_DURATION:
        raise DataQualityError(
            f"An exclusion or override lasts at most {MAX_DURATION.days} days; set it again "
            "when it ends if it is still needed"
        )
    for previous in _active_rows(session, [tag_id], now):
        before = _snapshot(previous)
        previous.cleared_at = now
        audit_change(
            session,
            actor,
            entity="sensor_exclusion",
            entity_id=previous.id,
            action="end",
            before=before,
            after=_snapshot(previous),
        )
    row = SensorExclusion(
        tag_id=tag_id,
        kind=kind.value,
        reason=text,
        starts_at=now,
        expires_at=until,
        created_by=actor.user_id,
    )
    session.add(row)
    session.flush()
    audit_change(
        session,
        actor,
        entity="sensor_exclusion",
        entity_id=row.id,
        action=kind.value,
        after=_snapshot(row),
    )
    return _view(row, {tag.id: (tag.source_name, tag.asset_code)})


def end_exclusion(
    session: Session, actor: Actor, exclusion_id: int, now: datetime
) -> ExclusionView:
    """End an exclusion or override now; the normal rules apply from the next cycle."""
    row = session.get(SensorExclusion, exclusion_id)
    if row is None:  # authorised first, so a refused user learns nothing (decision 6.7)
        authorize(actor, Permission.SENSOR_EXCLUSION, None, what="sensor exclusions")
        raise DataQualityError(f"Exclusion {exclusion_id} does not exist")
    tag = get_tags(session, [row.tag_id])[0]
    authorize(
        actor,
        Permission.SENSOR_EXCLUSION,
        get_asset_by_id(session, tag.asset_id).path,
        what=f"sensor exclusions on {tag.asset_code}",
    )
    view = _view(row, {tag.id: (tag.source_name, tag.asset_code)})
    if not view.active_at(now):
        raise DataQualityError("The exclusion has already ended")
    before = _snapshot(row)
    row.cleared_at = now
    session.flush()
    audit_change(
        session,
        actor,
        entity="sensor_exclusion",
        entity_id=row.id,
        action="end",
        before=before,
        after=_snapshot(row),
    )
    return _view(row, {tag.id: (tag.source_name, tag.asset_code)})


def list_exclusions(
    session: Session,
    tag_ids: Iterable[int] | None = None,
    *,
    active_at: datetime | None = None,
) -> list[ExclusionView]:
    """Exclusions and overrides, newest first; with `active_at`, only those active then."""
    query = select(SensorExclusion).order_by(SensorExclusion.starts_at.desc())
    if tag_ids is not None:
        query = query.where(SensorExclusion.tag_id.in_(list(tag_ids)))
    rows = list(session.scalars(query).all())
    names = _names(session, (r.tag_id for r in rows))
    views = [_view(r, names) for r in rows]
    return [v for v in views if active_at is None or v.active_at(active_at)]


def periods(
    session: Session, tag_ids: Iterable[int], start: datetime, end: datetime
) -> dict[int, list[tuple[datetime, datetime, ExclusionKind]]]:
    """Exclusion and override periods overlapping [start, end] per tag (rule evaluation)."""
    ids = list(tag_ids)
    found: dict[int, list[tuple[datetime, datetime, ExclusionKind]]] = {}
    if not ids:
        return found
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
            found.setdefault(row.tag_id, []).append((row.starts_at, stop, ExclusionKind(row.kind)))
    return found
