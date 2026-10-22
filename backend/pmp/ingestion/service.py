"""Ingestion services (UC-01, FR-ING-01, -04, -05, -06, NFR-PERF-04, NFR-REL-01).

A batch is written in the caller's transaction, so once the caller commits (before the
202 response) accepted samples are durable. Samples are bulk-loaded with COPY into a
temporary staging table and then upserted, which keeps 10,000-sample batches fast and
makes resending a batch harmless.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, String, func, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from pmp.core import Actor, Base, Permission, audit_change, authorize
from pmp.ingestion.domain import (
    BatchIn,
    Quality,
    RejectReason,
    check_window,
    map_quality,
    to_utc,
)
from pmp.registry import RegistryError, TagSpec, find_asset, resolve_tag_ids, upsert_tag


class UnmappedTag(Base):
    __tablename__ = "unmapped_tag"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(100))
    source_name: Mapped[str] = mapped_column(String(200))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    count: Mapped[int] = mapped_column(BigInteger)


class IngestSource(Base):
    __tablename__ = "ingest_source"

    source: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_sample_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_total: Mapped[int] = mapped_column(BigInteger)
    rejected_total: Mapped[int] = mapped_column(BigInteger)
    grace_s: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None: the default


@dataclass(frozen=True)
class Rejection:
    index: int
    reason: RejectReason


@dataclass
class IngestResult:
    accepted: int = 0
    rejected: list[Rejection] = field(default_factory=list)

    def as_response(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "rejected": [{"index": r.index, "reason": r.reason.value} for r in self.rejected],
        }


@dataclass(frozen=True)
class SampleRow:
    tag_id: int
    ts: datetime
    value: float
    quality: Quality
    quality_code: int | None


@dataclass(frozen=True)
class UnmappedTagView:
    source: str
    source_name: str
    first_seen: datetime
    last_seen: datetime
    count: int


@dataclass(frozen=True)
class SourceStats:
    source: str
    last_received_at: datetime
    last_sample_ts: datetime | None
    accepted_total: int
    rejected_total: int


def ingest_batch(
    session: Session, batch: BatchIn, *, now: datetime, late_window: timedelta
) -> IngestResult:
    """Map, check and store one batch. Writes in the caller's transaction."""
    result = IngestResult()
    tag_ids = resolve_tag_ids(session, batch.source, (s.tag for s in batch.samples))
    rows: dict[tuple[int, datetime], SampleRow] = {}
    unmapped: Counter[str] = Counter()

    for index, sample in enumerate(batch.samples):
        tag_id = tag_ids.get(sample.tag)
        if tag_id is None:
            result.rejected.append(Rejection(index, RejectReason.UNREGISTERED_TAG))
            unmapped[sample.tag] += 1
            continue
        ts = to_utc(sample.ts)
        reason = check_window(ts, now, late_window)
        if reason is not None:
            result.rejected.append(Rejection(index, reason))
            continue
        if sample.v is None:
            result.rejected.append(Rejection(index, RejectReason.NO_VALUE))
            continue
        quality, code = map_quality(sample.q)
        # Same tag and timestamp twice in one batch: the later one wins, as on a resend.
        rows[(tag_id, ts)] = SampleRow(tag_id, ts, sample.v, quality, code)
        result.accepted += 1

    write_samples(session, rows.values())
    _record_unmapped(session, batch.source, unmapped, now)
    _update_source_stats(session, batch.source, result, rows.values(), now)
    return result


def _prepare_stage(session: Session) -> None:
    session.execute(
        text(
            "CREATE TEMP TABLE IF NOT EXISTS sample_stage "
            "(tag_id integer, ts timestamptz, value double precision, quality smallint, "
            "quality_code bigint) ON COMMIT DELETE ROWS"
        )
    )
    session.execute(text("TRUNCATE sample_stage"))


def _copy_sql() -> str:
    return "COPY sample_stage (tag_id, ts, value, quality, quality_code) FROM STDIN"


def stage_rows(session: Session, rows: Iterable[SampleRow]) -> None:
    """Load rows into the per-transaction staging table with COPY."""
    _prepare_stage(session)
    raw = session.connection().connection.driver_connection
    assert raw is not None
    with raw.cursor() as cursor, cursor.copy(_copy_sql()) as copy:
        for row in rows:
            copy.write_row((row.tag_id, row.ts, row.value, int(row.quality), row.quality_code))


def stage_text(session: Session, data: str) -> None:
    """Load tab-separated rows (tag_id, ts, value, quality, quality_code; \\N for null)."""
    _prepare_stage(session)
    raw = session.connection().connection.driver_connection
    assert raw is not None
    with raw.cursor() as cursor, cursor.copy(_copy_sql()) as copy:
        copy.write(data)


def merge_staged(session: Session, *, overwrite: bool) -> tuple[int, int]:
    """Upsert the staged rows into sample. Returns (new rows, rows that already existed).

    With overwrite the existing rows are replaced; otherwise they are left alone. The
    time bounds let TimescaleDB look only at the chunks the batch touches.
    """
    bounds = session.execute(text("SELECT min(ts), max(ts), count(*) FROM sample_stage")).one()
    low, high, total = bounds
    if not total:
        return 0, 0
    existing = (
        session.scalar(
            text(
                "SELECT count(*) FROM sample_stage s JOIN sample t "
                "ON t.tag_id = s.tag_id AND t.ts = s.ts "
                "WHERE t.ts BETWEEN :low AND :high"
            ),
            {"low": low, "high": high},
        )
        or 0
    )
    action = (
        "DO UPDATE SET value = EXCLUDED.value, quality = EXCLUDED.quality, "
        "quality_code = EXCLUDED.quality_code"
        if overwrite
        else "DO NOTHING"
    )
    session.execute(
        text(
            "INSERT INTO sample (tag_id, ts, value, quality, quality_code) "
            "SELECT tag_id, ts, value, quality, quality_code FROM sample_stage "
            f"ON CONFLICT (tag_id, ts) {action}"
        )
    )
    return int(total) - int(existing), int(existing)


def write_samples(session: Session, rows: Iterable[SampleRow], *, overwrite: bool = True) -> int:
    """Bulk upsert samples keyed on (tag_id, ts). Returns the number of rows staged."""
    rows = list(rows)
    if not rows:
        return 0
    stage_rows(session, rows)
    merge_staged(session, overwrite=overwrite)
    return len(rows)


def _record_unmapped(session: Session, source: str, names: Counter[str], now: datetime) -> None:
    for name, count in names.items():
        session.execute(
            text(
                "INSERT INTO unmapped_tag (source, source_name, first_seen, last_seen, count) "
                "VALUES (:source, :name, :now, :now, :count) "
                "ON CONFLICT (source, source_name) DO UPDATE "
                "SET last_seen = EXCLUDED.last_seen, count = unmapped_tag.count + EXCLUDED.count"
            ),
            {"source": source, "name": name, "now": now, "count": count},
        )


def _update_source_stats(
    session: Session,
    source: str,
    result: IngestResult,
    rows: Iterable[SampleRow],
    now: datetime,
) -> None:
    latest = max((r.ts for r in rows), default=None)
    session.execute(
        text(
            "INSERT INTO ingest_source "
            "(source, last_received_at, last_sample_ts, accepted_total, rejected_total) "
            "VALUES (:source, :now, :latest, :accepted, :rejected) "
            "ON CONFLICT (source) DO UPDATE SET "
            "last_received_at = EXCLUDED.last_received_at, "
            "last_sample_ts = GREATEST(ingest_source.last_sample_ts, EXCLUDED.last_sample_ts), "
            "accepted_total = ingest_source.accepted_total + EXCLUDED.accepted_total, "
            "rejected_total = ingest_source.rejected_total + EXCLUDED.rejected_total"
        ),
        {
            "source": source,
            "now": now,
            "latest": latest,
            "accepted": result.accepted,
            "rejected": len(result.rejected),
        },
    )


# ------------------------------------------------------------------ queries


def read_samples(
    session: Session, tag_id: int, start: datetime, end: datetime
) -> list[tuple[datetime, float, Quality]]:
    """Raw samples for one tag in [start, end), oldest first."""
    rows = session.execute(
        text(
            "SELECT ts, value, quality FROM sample "
            "WHERE tag_id = :tag AND ts >= :start AND ts < :end ORDER BY ts"
        ),
        {"tag": tag_id, "start": start, "end": end},
    )
    return [(ts, value, Quality(q)) for ts, value, q in rows]


def read_last_samples(
    session: Session, tag_id: int, at: datetime, limit: int
) -> list[tuple[datetime, float, Quality]]:
    """The latest `limit` samples for one tag at or before `at`, oldest first."""
    rows = session.execute(
        text(
            "SELECT ts, value, quality FROM sample "
            "WHERE tag_id = :tag AND ts <= :at ORDER BY ts DESC LIMIT :limit"
        ),
        {"tag": tag_id, "at": at, "limit": limit},
    ).all()
    return [(ts, value, Quality(q)) for ts, value, q in reversed(rows)]


def read_last_samples_many(
    session: Session, tag_ids: Iterable[int], at: datetime, limit: int
) -> dict[int, list[tuple[datetime, float, Quality]]]:
    """The latest `limit` samples at or before `at` for many tags in one query, oldest
    first per tag (the scoring cycle reads thousands of tags)."""
    ids = sorted(set(tag_ids))
    result: dict[int, list[tuple[datetime, float, Quality]]] = {t: [] for t in ids}
    if not ids:
        return result
    rows = session.execute(
        text(
            "SELECT t.tag_id, s.ts, s.value, s.quality "
            "FROM unnest(CAST(:ids AS integer[])) AS t(tag_id) "
            "CROSS JOIN LATERAL (SELECT ts, value, quality FROM sample "
            "  WHERE sample.tag_id = t.tag_id AND ts <= :at ORDER BY ts DESC LIMIT :limit) s "
            "ORDER BY t.tag_id, s.ts"
        ),
        {"ids": ids, "at": at, "limit": limit},
    )
    for tag_id, ts, value, quality in rows:
        result[int(tag_id)].append((ts, value, Quality(quality)))
    return result


def count_samples(session: Session, tag_ids: Iterable[int] | None = None) -> int:
    if tag_ids is None:
        return session.scalar(text("SELECT count(*) FROM sample")) or 0
    ids = list(tag_ids)
    return (
        session.scalar(text("SELECT count(*) FROM sample WHERE tag_id = ANY(:ids)"), {"ids": ids})
        or 0
    )


def list_unmapped_tags(session: Session, source: str | None = None) -> list[UnmappedTagView]:
    """Unknown tag names seen by ingestion that are still not registered (FR-ING-06)."""
    query = select(UnmappedTag).order_by(UnmappedTag.source, UnmappedTag.source_name)
    if source is not None:
        query = query.where(UnmappedTag.source == source)
    rows = session.scalars(query).all()
    registered: set[tuple[str, str]] = set()  # registered since (e.g. by an import)
    for name in {r.source for r in rows}:
        found = resolve_tag_ids(session, name, [r.source_name for r in rows if r.source == name])
        registered |= {(name, tag) for tag in found}
    return [
        UnmappedTagView(row.source, row.source_name, row.first_seen, row.last_seen, row.count)
        for row in rows
        if (row.source, row.source_name) not in registered
    ]


def promote_unmapped_tag(
    session: Session, actor: Actor, spec: TagSpec, *, role_code: str | None = None
) -> None:
    """Register an unmapped tag (UC-03 2a). The registry validates and audits it. A name
    that is registered already is refused: promoting is not a way to move a tag."""
    target = find_asset(session, spec.asset_code)
    authorize(actor, Permission.REGISTRY, target.path if target else None, what="tags")
    if resolve_tag_ids(session, spec.source.strip(), [spec.source_name.strip()]):
        raise RegistryError(f"{spec.source_name} is registered already; change it on the tag")
    upsert_tag(session, actor, spec, role_code=role_code)
    session.execute(
        text("DELETE FROM unmapped_tag WHERE source = :source AND source_name = :name"),
        {"source": spec.source.strip(), "name": spec.source_name.strip()},
    )


def source_stats(session: Session, source: str) -> SourceStats | None:
    row = session.get(IngestSource, source)
    if row is None:
        return None
    return SourceStats(
        row.source,
        row.last_received_at,
        row.last_sample_ts,
        row.accepted_total,
        row.rejected_total,
    )


MAX_GRACE_S = 600


class IngestError(Exception):
    """An ingestion setting that is not allowed; the message is for the user."""


def set_source_grace(session: Session, actor: Actor, source: str, grace_s: int | None) -> None:
    """How long scoring waits for a source's late samples (ARC §5.1); None: the default.
    Configuration, so an Administrator's change, audited. The source must have sent data."""
    authorize(actor, Permission.ADMINISTRATION, what="scoring grace of a source")
    if grace_s is not None and not 0 <= grace_s <= MAX_GRACE_S:
        raise IngestError(f"The grace is 0 to {MAX_GRACE_S} seconds")
    row = session.get(IngestSource, source)
    if row is None:
        raise IngestError(f"Source {source!r} has not sent any data yet")
    before = row.grace_s
    row.grace_s = grace_s
    audit_change(
        session,
        actor,
        entity="ingest_source",
        entity_id=source,
        action="set_grace",
        before={"grace_s": before},
        after={"grace_s": grace_s},
    )


def source_graces(session: Session) -> dict[str, int]:
    """The sources that have their own scoring grace."""
    rows = session.execute(
        select(IngestSource.source, IngestSource.grace_s).where(IngestSource.grace_s.is_not(None))
    ).all()
    return {str(source): int(grace) for source, grace in rows if grace is not None}


def server_now(session: Session) -> datetime:
    """The database clock, so all timestamps compare against one clock."""
    value: datetime | None = session.scalar(select(func.now()))
    assert value is not None
    return value
