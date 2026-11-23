"""Data retention (NFR-DATA-01, ARC §6.3, plan 5.4).

Raw time series (samples, scores, sensor outputs) are kept for `raw_months` (default 24,
PMP_RETENTION_MONTHS) and the hourly aggregates for `aggregate_months` (default 60). An
administrator can change both (ARC §9.2: retention); the worker applies them once a day.

With TimescaleDB, whole chunks older than the cutoff are dropped, which is cheap and
leaves no dead rows; without it (the development sandbox) old rows are deleted.
"""

from __future__ import annotations

import calendar
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, Session, mapped_column

from pmp.core.access import Permission, authorize
from pmp.core.audit import Actor, audit_change
from pmp.core.db import Base, Database

logger = logging.getLogger(__name__)
RETENTION_JOB = "retention"
DEFAULT_AGGREGATE_MONTHS = 60
RUN_EVERY = timedelta(days=1)


@dataclass(frozen=True)
class RetainedTable:
    """A raw hypertable and its hourly aggregate, named by the module that owns them
    (ARC §4: core never names another module's tables; plan 6.7)."""

    raw: str
    hourly: str


@dataclass(frozen=True)
class RetainedRecords:
    """Rows of one kind of record, named by the module that owns them: removed once the
    timestamp column is older than the kind's period (and `condition` holds, for example
    only closed alerts)."""

    kind: str
    table: str
    ts_column: str
    condition: str = ""


@dataclass(frozen=True)
class RetainedFiles:
    """Files of one kind in a directory, removed by age (uploaded history files)."""

    kind: str
    directory: Path


@dataclass(frozen=True)
class RetentionPlan:
    """Everything the clean-up looks after, gathered from the modules that own it."""

    tables: Sequence[RetainedTable] = ()  # raw samples and their roll-ups
    scores: Sequence[RetainedTable] = ()  # scores and sensor outputs and their roll-ups
    records: Sequence[RetainedRecords] = ()
    files: Sequence[RetainedFiles] = ()


@dataclass(frozen=True)
class Period:
    kind: str
    label: str
    default_days: int
    min_days: int
    unit: str  # how the screen shows it: "days" or "years"
    note: str


YEAR = 365
_NOTE_ALERTS = "ISA-18.2 record keeping; only closed alerts are removed"
_NOTE_CASES = "Only closed and cancelled cases; they feed the failure-mode library"
PERIODS: tuple[Period, ...] = (
    Period("raw", "Raw samples", 730, 90, "days", "1-minute values per tag; models train on them"),
    Period("hourly", "Hourly roll-ups", 5 * YEAR, YEAR, "years", "Min, max, mean and count"),
    Period(
        "scores", "Scores and sensor outputs", 2 * YEAR, 400, "years", "Re-scoring replaces rows"
    ),
    Period("forecasts", "Forecasts", 400, 90, "days", "None"),
    Period("alerts", "Alerts and their history", 7 * YEAR, 3 * YEAR, "years", _NOTE_ALERTS),
    Period("cases", "Cases, attachments and snapshots", 10 * YEAR, 5 * YEAR, "years", _NOTE_CASES),
    Period("uploads", "Uploaded history files", 90, 30, "days", "Imported samples stay stored"),
    Period("notifications", "Notification log", 180, 30, "days", "None"),
    Period("audit", "Audit log", 10 * YEAR, 7 * YEAR, "years", "Cannot be edited or removed early"),
)
PERIOD = {p.kind: p for p in PERIODS}


class RetentionError(ValueError):
    """A retention setting that is not allowed."""


class RetentionPolicyRow(Base):
    __tablename__ = "retention_policy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_months: Mapped[int] = mapped_column(Integer)
    aggregate_months: Mapped[int] = mapped_column(Integer)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_result: Mapped[str | None] = mapped_column(Text)
    last_removed: Mapped[int | None] = mapped_column(BigInteger)
    periods: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


@dataclass(frozen=True)
class RetentionPolicy:
    raw_months: int
    aggregate_months: int
    last_run_at: datetime | None
    last_result: str | None
    days: dict[str, int] = field(default_factory=dict)  # every kind in PERIODS
    last_removed: int | None = None


def _days(row: RetentionPolicyRow) -> dict[str, int]:
    """Days per kind: what was set, else raw and hourly from the months, else the default."""
    stored = dict(row.periods or {})
    out = {p.kind: int(stored.get(p.kind, p.default_days)) for p in PERIODS}
    if "raw" not in stored:
        out["raw"] = round(row.raw_months * 30.44)
    if "hourly" not in stored:
        out["hourly"] = round(row.aggregate_months * 30.44)
    if "scores" not in stored:
        out["scores"] = max(out["raw"], PERIOD["scores"].min_days)
    return out


def _row(session: Session, default_raw_months: int) -> RetentionPolicyRow:
    row = session.get(RetentionPolicyRow, 1)
    if row is None:
        row = RetentionPolicyRow(
            id=1,
            raw_months=default_raw_months,
            aggregate_months=max(DEFAULT_AGGREGATE_MONTHS, default_raw_months),
        )
        session.add(row)
        session.flush()
    return row


def _view(row: RetentionPolicyRow) -> RetentionPolicy:
    return RetentionPolicy(
        row.raw_months,
        row.aggregate_months,
        row.last_run_at,
        row.last_result,
        _days(row),
        row.last_removed,
    )


def set_retention_days(
    session: Session,
    actor: Actor,
    days: dict[str, int],
    default_raw_months: int = 24,
) -> RetentionPolicy:
    """Administrators only. Each kind is kept at least its minimum; roll-ups at least as
    long as raw samples. Shortening a period deletes data at the next run."""
    authorize(actor, Permission.ADMINISTRATION, what="retention")
    row = _row(session, default_raw_months)
    current = _days(row)
    unknown = sorted(set(days) - set(PERIOD))
    if unknown:
        raise RetentionError(f"Unknown kind of data: {', '.join(unknown)}")
    new = {**current, **{k: int(v) for k, v in days.items()}}
    for kind, value in new.items():
        p = PERIOD[kind]
        if value < p.min_days:
            raise RetentionError(f"{p.label} are kept at least {p.min_days} days")
    if new["hourly"] < new["raw"]:
        raise RetentionError("Hourly roll-ups are kept at least as long as raw samples")
    before = {"days": current}
    row.periods = new
    row.raw_months = max(1, round(new["raw"] / 30.44))
    row.aggregate_months = max(row.raw_months, round(new["hourly"] / 30.44))
    row.updated_at = func.now()
    audit_change(
        session,
        actor,
        entity="retention_policy",
        entity_id=1,
        action="update",
        before=before,
        after={"days": new},
    )
    return _view(row)


def retention_sizes(
    session: Session,
    tables: Sequence[RetainedTable],
    scores: Sequence[RetainedTable],
    records: Sequence[RetainedRecords],
    files: Sequence[RetainedFiles],
) -> tuple[dict[str, int | None], int, int | None]:
    """Bytes stored per kind, the database size and the approximate number of raw samples.
    A size is None when it cannot be measured (an aggregate kept as a plain view)."""
    timescale = _timescale(session)

    def size(name: str) -> int | None:
        found = session.execute(
            text(
                "SELECT CASE WHEN to_regclass(:t) IS NULL THEN NULL "
                "ELSE pg_total_relation_size(to_regclass(:t)) END"
            ),
            {"t": name},
        ).scalar_one()
        return None if found is None else int(found)

    def hyper(name: str) -> int | None:
        """A hypertable or continuous aggregate by its stored chunks; a plain table or view
        otherwise. Never raises: a size that cannot be read is None."""
        if not timescale:
            return size(name)
        try:
            with session.begin_nested():
                found = session.execute(
                    text(
                        "SELECT hypertable_size(format('%I.%I', s, n)::regclass) FROM ("
                        " SELECT hypertable_schema AS s, hypertable_name AS n"
                        " FROM timescaledb_information.hypertables WHERE hypertable_name = :t"
                        " UNION ALL"
                        " SELECT materialization_hypertable_schema, materialization_hypertable_name"
                        " FROM timescaledb_information.continuous_aggregates WHERE view_name = :t"
                        ") AS h LIMIT 1"
                    ),
                    {"t": name},
                ).scalar()
        except SQLAlchemyError:
            found = None
        return int(found) if found is not None else size(name)

    def total(values: Sequence[int | None]) -> int | None:
        known = [v for v in values if v is not None]
        return sum(known) if known else None

    out: dict[str, int | None] = {
        "raw": total([hyper(t.raw) for t in tables]),
        "hourly": total([hyper(t.hourly) for t in (*tables, *scores)]),
        "scores": total([hyper(t.raw) for t in scores]),
    }
    for kind in {r.kind for r in records}:
        out[kind] = total([size(r.table) for r in records if r.kind == kind])
    for f in files:
        out[f.kind] = (
            sum(p.stat().st_size for p in f.directory.iterdir() if p.is_file())
            if f.directory.is_dir()
            else 0
        )
    database = int(
        session.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
    )
    raw_rows = None
    for t in tables:
        estimate = session.execute(
            text("SELECT reltuples::bigint FROM pg_class WHERE oid = to_regclass(:t)"), {"t": t.raw}
        ).scalar()
        if timescale:
            try:
                with session.begin_nested():
                    estimate = session.execute(
                        text("SELECT approximate_row_count(to_regclass(:t))"), {"t": t.raw}
                    ).scalar()
            except SQLAlchemyError:
                pass
        if estimate is not None and estimate >= 0:
            raw_rows = (raw_rows or 0) + int(estimate)
    return out, database, raw_rows


def get_retention(session: Session, default_raw_months: int = 24) -> RetentionPolicy:
    return _view(_row(session, default_raw_months))


def set_retention(
    session: Session,
    actor: Actor,
    *,
    raw_months: int,
    aggregate_months: int,
    default_raw_months: int = 24,
) -> RetentionPolicy:
    """Administrators only (ARC §9.2). Shortening it deletes data at the next run."""
    authorize(actor, Permission.ADMINISTRATION, what="retention")
    if raw_months < 1 or aggregate_months < raw_months:
        raise RetentionError("Raw data needs at least 1 month, and aggregates at least as long")
    row = _row(session, default_raw_months)
    before = {"raw_months": row.raw_months, "aggregate_months": row.aggregate_months}
    row.raw_months, row.aggregate_months = raw_months, aggregate_months
    row.updated_at = func.now()
    audit_change(
        session,
        actor,
        entity="retention_policy",
        entity_id=1,
        action="update",
        before=before,
        after={"raw_months": raw_months, "aggregate_months": aggregate_months},
    )
    return _view(row)


def months_before(now: datetime, months: int) -> datetime:
    """`now` moved back by whole calendar months (the day clamped to the month's end)."""
    year, month0 = divmod(now.year * 12 + now.month - 1 - months, 12)
    day = min(now.day, calendar.monthrange(year, month0 + 1)[1])
    return now.replace(year=year, month=month0 + 1, day=day)


def _timescale(session: Session) -> bool:
    found = session.execute(
        text("SELECT count(*) FROM pg_proc WHERE proname = 'drop_chunks'")
    ).scalar_one()
    return bool(found)


def apply_retention(
    session: Session,
    now: datetime,
    default_raw_months: int,
    tables: Sequence[RetainedTable],
    *,
    scores: Sequence[RetainedTable] = (),
    records: Sequence[RetainedRecords] = (),
    files: Sequence[RetainedFiles] = (),
) -> str:
    """Remove what is older than its period: raw samples and their roll-ups (`tables`),
    scores and sensor outputs (`scores`), records of other kinds and uploaded files.
    Returns a summary; the number of rows and files removed is kept with it."""
    row = _row(session, default_raw_months)
    days = _days(row)
    cutoff = {kind: now - timedelta(days=d) for kind, d in days.items()}
    removed: list[str] = []
    count = 0
    timescale = _timescale(session)

    def series(name: str, when: datetime, raw: bool) -> None:
        nonlocal count
        if timescale:
            dropped = session.execute(
                text("SELECT count(*) FROM drop_chunks(:t, older_than => :cutoff)"),
                {"t": name, "cutoff": when},
            ).scalar_one()
            removed.append(f"{name}: {dropped} chunks")
        elif raw:  # without TimescaleDB the roll-ups are plain views with nothing to remove
            result = session.execute(
                text(f"DELETE FROM {name} WHERE ts < :cutoff"), {"cutoff": when}
            )
            n = int(result.rowcount)  # type: ignore[attr-defined]
            count += n
            removed.append(f"{name}: {n} rows")

    for table in tables:
        series(table.raw, cutoff["raw"], True)
        series(table.hourly, cutoff["hourly"], False)
    for table in scores:
        series(table.raw, cutoff["scores"], True)
        series(table.hourly, cutoff["hourly"], False)
    # Lets the audit log's append-only trigger accept deletes of rows past their minimum.
    session.execute(text("SELECT set_config('pmp.retention', 'on', true)"))
    for rec in records:
        where = f" AND ({rec.condition})" if rec.condition else ""
        result = session.execute(
            text(f'DELETE FROM "{rec.table}" WHERE {rec.ts_column} < :cutoff{where}'),
            {"cutoff": cutoff[rec.kind]},
        )
        n = int(result.rowcount)  # type: ignore[attr-defined]
        count += n
        if n:
            removed.append(f"{rec.table}: {n} rows")
    for f in files:
        if not f.directory.is_dir():
            continue
        limit = cutoff[f.kind].timestamp()
        old = [p for p in f.directory.iterdir() if p.is_file() and p.stat().st_mtime < limit]
        for path in old:
            path.unlink(missing_ok=True)
        count += len(old)
        if old:
            removed.append(f"{f.kind}: {len(old)} files")
    summary = (
        f"raw before {cutoff['raw']:%Y-%m-%d}, roll-ups before {cutoff['hourly']:%Y-%m-%d}: "
        + (", ".join(removed) or "nothing to remove")
    )
    row.last_run_at, row.last_result, row.last_removed = now, summary, count
    logger.info("Retention applied: %s", summary)
    return summary


def retention_due(session: Session, now: datetime) -> bool:
    row = session.get(RetentionPolicyRow, 1)
    return row is None or row.last_run_at is None or now - row.last_run_at >= RUN_EVERY


def refresh_hourly(database: Database, aggregate: str, start: datetime, end: datetime) -> None:
    """Bring the hourly aggregate of `table` up to date for [start, end) after data was
    written there out of time order (a history import). Live data needs no call: the
    aggregates' refresh policy and real-time aggregation cover it. Without TimescaleDB the
    aggregates are plain views and nothing needs refreshing."""
    begin = start.replace(minute=0, second=0, microsecond=0)
    finish = end.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    with database.engine.connect() as connection:
        connection = connection.execution_options(isolation_level="AUTOCOMMIT")
        found = connection.execute(
            text("SELECT count(*) FROM pg_proc WHERE proname = 'refresh_continuous_aggregate'")
        ).scalar_one()
        if not found:
            return
        connection.execute(
            text("CALL refresh_continuous_aggregate(:view, :start, :end)"),
            {"view": aggregate, "start": begin, "end": finish},
        )
