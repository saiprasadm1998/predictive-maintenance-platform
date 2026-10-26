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
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import DateTime, Integer, Text, func, text
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


class RetentionError(ValueError):
    """A retention setting that is not allowed."""


class RetentionPolicyRow(Base):
    __tablename__ = "retention_policy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_months: Mapped[int] = mapped_column(Integer)
    aggregate_months: Mapped[int] = mapped_column(Integer)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_result: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


@dataclass(frozen=True)
class RetentionPolicy:
    raw_months: int
    aggregate_months: int
    last_run_at: datetime | None
    last_result: str | None


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
    return RetentionPolicy(row.raw_months, row.aggregate_months, row.last_run_at, row.last_result)


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
) -> str:
    """Remove raw data and aggregates older than the policy allows from the owners'
    `tables`. Returns a summary."""
    row = _row(session, default_raw_months)
    raw_cutoff = months_before(now, row.raw_months)
    aggregate_cutoff = months_before(now, row.aggregate_months)
    removed = []
    timescale = _timescale(session)
    for table in tables:
        for name, cutoff, raw in (
            (table.raw, raw_cutoff, True),
            (table.hourly, aggregate_cutoff, False),
        ):
            if timescale:
                dropped = session.execute(
                    text("SELECT count(*) FROM drop_chunks(:t, older_than => :cutoff)"),
                    {"t": name, "cutoff": cutoff},
                ).scalar_one()
                removed.append(f"{name}: {dropped} chunks")
            elif raw:  # the plain views hold nothing of their own
                result = session.execute(
                    text(f"DELETE FROM {name} WHERE ts < :cutoff"), {"cutoff": cutoff}
                )
                removed.append(f"{name}: {result.rowcount} rows")  # type: ignore[attr-defined]
    summary = (
        f"raw before {raw_cutoff:%Y-%m-%d}, aggregates before {aggregate_cutoff:%Y-%m-%d}: "
        + ", ".join(removed)
    )
    row.last_run_at, row.last_result = now, summary
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
