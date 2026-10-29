"""Ingestion health (FR-ING-07, ARC §11 T-02, plan 8.7).

Per source: last received time, newest sample time, throughput, accepted and rejected
totals, a stale warning and a clock-skew warning; per tag: its newest sample.

* A source is stale when nothing has arrived for more than STALE_INTERVALS of its
  shortest tag scan interval (DEFAULT_INTERVAL_S if it has no registered tag), so a
  stopped feed shows, and is e-mailed, within 3 scan intervals (FR-ING-07).
* Clock skew is receive time minus the newest sample time, warned above 60 s
  (ARC T-02): sample times come from the gateway's clock.
* A tag is stale on the same rule with its own interval; a tag that never sent is "never".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from pmp.core import Actor, Permission, authorize
from pmp.ingestion.service import IngestSource, read_last_samples_many
from pmp.registry import list_tags

STALE_INTERVALS = 2
DEFAULT_INTERVAL_S = 60
MAX_SKEW_S = 60
THROUGHPUT_WINDOW = timedelta(minutes=5)


@dataclass(frozen=True)
class TagHealth:
    tag_id: int
    source: str
    source_name: str
    asset_code: str
    interval_s: int
    last_sample_ts: datetime | None
    stale: bool


@dataclass(frozen=True)
class SourceHealth:
    source: str
    last_received_at: datetime | None  # None: tags registered, nothing received yet
    last_sample_ts: datetime | None
    accepted_total: int
    rejected_total: int
    per_minute: float  # samples stored per minute over the last 5 minutes
    interval_s: int  # the shortest scan interval of its tags
    tags: int
    stale: bool
    skew_s: float | None  # receive time minus newest sample time
    skewed: bool

    @property
    def stale_after(self) -> timedelta:
        return timedelta(seconds=STALE_INTERVALS * self.interval_s)


@dataclass(frozen=True)
class IngestionHealth:
    checked_at: datetime
    sources: list[SourceHealth]
    tags: list[TagHealth]


def _is_stale(last: datetime | None, interval_s: int, now: datetime) -> bool:
    return last is None or now - last > timedelta(seconds=STALE_INTERVALS * interval_s)


def _per_minute(session: Session, now: datetime) -> dict[str, float]:
    rows = session.execute(
        text(
            "SELECT t.source, count(*) FROM sample s JOIN tag t ON t.id = s.tag_id "
            "WHERE s.ts > :since AND s.ts <= :now GROUP BY t.source"
        ),
        {"since": now - THROUGHPUT_WINDOW, "now": now},
    ).all()
    minutes = THROUGHPUT_WINDOW.total_seconds() / 60
    return {source: count / minutes for source, count in rows}


def source_health(session: Session, now: datetime) -> list[SourceHealth]:
    """Every source that has sent data or has registered tags, by name. No access check:
    the notifier calls it; people go through ingestion_health."""
    tags = list_tags(session)
    intervals: dict[str, int] = {}
    counts: dict[str, int] = {}
    for tag in tags:
        intervals[tag.source] = min(intervals.get(tag.source, tag.interval_s), tag.interval_s)
        counts[tag.source] = counts.get(tag.source, 0) + 1
    rows = {r.source: r for r in session.scalars(select(IngestSource)).all()}
    rates = _per_minute(session, now)
    out = []
    for source in sorted({*rows, *intervals}):
        row = rows.get(source)
        interval = intervals.get(source, DEFAULT_INTERVAL_S)
        received = row.last_received_at if row else None
        newest = row.last_sample_ts if row else None
        skew = (received - newest).total_seconds() if received and newest else None
        out.append(
            SourceHealth(
                source=source,
                last_received_at=received,
                last_sample_ts=newest,
                accepted_total=row.accepted_total if row else 0,
                rejected_total=row.rejected_total if row else 0,
                per_minute=round(rates.get(source, 0.0), 1),
                interval_s=interval,
                tags=counts.get(source, 0),
                stale=_is_stale(received, interval, now),
                skew_s=skew,
                skewed=skew is not None and abs(skew) > MAX_SKEW_S,
            )
        )
    return out


def ingestion_health(session: Session, actor: Actor, now: datetime) -> IngestionHealth:
    """The ingestion-health screen (SCR-14 Administration): administrators."""
    authorize(actor, Permission.ADMINISTRATION, what="ingestion health")
    tags = list_tags(session)
    last = read_last_samples_many(session, (t.id for t in tags), now, 1)
    tag_health = [
        TagHealth(
            tag_id=t.id,
            source=t.source,
            source_name=t.source_name,
            asset_code=t.asset_code,
            interval_s=t.interval_s,
            last_sample_ts=last[t.id][-1][0] if last.get(t.id) else None,
            stale=_is_stale(last[t.id][-1][0] if last.get(t.id) else None, t.interval_s, now),
        )
        for t in sorted(tags, key=lambda t: (t.source, t.source_name))
    ]
    return IngestionHealth(now, source_health(session, now), tag_health)
