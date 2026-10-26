"""Score and sensor-output trends for the screens (FR-VIS-02, NFR-PERF-03, ARC ADR-06).

A trend over a long period is reduced in the database to at most `px` buckets (one per
pixel of chart width), each with the minimum and maximum of every series, so spikes stay
visible and the payload is proportional to the screen, not to the period. Periods shorter
than two days are returned raw (at most 2,880 cycles of one minute).

Series are columns (one list per value), which is compact and maps directly onto a chart.
Values that do not exist for a cycle (Health while Insufficient data, for example) are null.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

RAW_BELOW = timedelta(days=2)
HOURLY_ABOVE = timedelta(days=30)  # ARC §6.3: the hourly aggregates for longer trends
MAX_PX = 5000
SCORE_SERIES = ("di", "health")
OUTPUT_SERIES = ("actual", "predicted", "residual", "q", "z")


class TrendError(ValueError):
    """A trend request that cannot be answered (bad period or resolution)."""


@dataclass(frozen=True)
class Trend:
    """`ts` are cycle times (raw) or bucket starts. With raw data `min` and `max` hold the
    same values."""

    start: datetime
    end: datetime
    raw: bool
    bucket_s: float | None
    ts: list[datetime] = field(default_factory=list)
    min: dict[str, list[float | None]] = field(default_factory=dict)
    max: dict[str, list[float | None]] = field(default_factory=dict)
    source: str = "raw"  # "raw": every cycle's values; "hourly": the hourly aggregates


def _check(start: datetime, end: datetime, px: int) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise TrendError("Times need a time zone (ISO 8601 UTC)")
    if end <= start:
        raise TrendError("The end of the period must be after its start")
    if not 1 <= px <= MAX_PX:
        raise TrendError(f"px must be from 1 to {MAX_PX}")


def _bucket_s(start: datetime, end: datetime, px: int) -> float:
    return max((end - start).total_seconds() / px, 1.0)


def _build(
    start: datetime,
    end: datetime,
    raw: bool,
    bucket_s: float | None,
    series: Iterable[str],
    rows: Iterable[Mapping[str, object]],
) -> Trend:
    names = list(series)
    trend = Trend(start, end, raw, bucket_s, [], {n: [] for n in names}, {n: [] for n in names})
    for row in rows:
        trend.ts.append(row["ts"])  # type: ignore[arg-type]
        for n in names:
            low = row[f"{n}_min"] if not raw else row[n]
            high = row[f"{n}_max"] if not raw else row[n]
            trend.min[n].append(None if low is None else float(low))  # type: ignore[arg-type]
            trend.max[n].append(None if high is None else float(high))  # type: ignore[arg-type]
    return trend


def _aggregates(series: Iterable[str], hourly: bool = False) -> str:
    """min and max per bucket: of the values, or of the hourly minima and maxima."""
    if hourly:
        return ", ".join(f"min({n}_min) AS {n}_min, max({n}_max) AS {n}_max" for n in series)
    return ", ".join(f"min({n}) AS {n}_min, max({n}) AS {n}_max" for n in series)


def score_trend(
    session: Session,
    model_id: int,
    start: datetime,
    end: datetime,
    px: int = 1000,
    *,
    version_id: int | None = None,
) -> Trend:
    """DI and Health of a model over [start, end), across all its versions or one of them
    (historical comparison, SCR-03). The hourly aggregates are per model, so one version's
    long trend is computed from the raw scores."""
    _check(start, end, px)
    params: dict[str, object] = {"model_id": model_id, "start": start, "end": end}
    version_filter = ""
    if version_id is not None:
        params["version_id"] = version_id
        version_filter = " AND version_id = :version_id"
    if end - start < RAW_BELOW:
        rows = session.execute(
            text(
                "SELECT ts, di, health FROM score "
                f"WHERE model_id = :model_id{version_filter} AND ts >= :start AND ts < :end "
                "ORDER BY ts"
            ),
            params,
        ).mappings()
        return _build(start, end, True, None, SCORE_SERIES, [dict(r) for r in rows])
    bucket = _bucket_s(start, end, px)
    hourly = end - start > HOURLY_ABOVE and version_id is None
    table, ts, columns = (
        ("score_1h", "bucket", "di_min, di_max, health_min, health_max")
        if hourly
        else ("score", "ts", "di, health")
    )
    rows = session.execute(
        text(
            "SELECT :start + make_interval(secs => b * :bucket) AS ts, "
            f"{_aggregates(SCORE_SERIES, hourly)} "
            f"FROM (SELECT floor(extract(epoch FROM {ts} - :start) / :bucket) AS b, {columns} "
            f"      FROM {table} WHERE model_id = :model_id{version_filter} "
            f"      AND {ts} >= :start AND {ts} < :end) s "
            "GROUP BY b ORDER BY b"
        ),
        {**params, "bucket": bucket},
    ).mappings()
    trend = _build(start, end, False, bucket, SCORE_SERIES, [dict(r) for r in rows])
    return replace(trend, source="hourly" if hourly else "raw")


def output_trends(
    session: Session,
    version_ids: Iterable[int],
    tag_ids: Iterable[int],
    start: datetime,
    end: datetime,
    px: int = 1000,
) -> dict[int, Trend]:
    """Actual, predicted, residual, q and z per tag over [start, end), across the given
    versions of one model. One query for all tags."""
    _check(start, end, px)
    tags = sorted(set(tag_ids))
    versions = sorted(set(version_ids))
    out = {t: Trend(start, end, end - start < RAW_BELOW, None) for t in tags}
    if not tags or not versions:
        return out
    params = {"versions": versions, "tags": tags, "start": start, "end": end}
    where = "version_id = ANY(:versions) AND tag_id = ANY(:tags) AND ts >= :start AND ts < :end"
    if end - start < RAW_BELOW:
        query = f"SELECT tag_id, ts, {', '.join(OUTPUT_SERIES)} FROM sensor_output WHERE {where} "
        query += "ORDER BY tag_id, ts"
        bucket = None
    else:
        bucket = _bucket_s(start, end, px)
        params["bucket"] = bucket
        hourly = end - start > HOURLY_ABOVE
        table, ts = ("sensor_output_1h", "bucket") if hourly else ("sensor_output", "ts")
        columns = (
            ", ".join(f"{n}_min, {n}_max" for n in OUTPUT_SERIES)
            if hourly
            else ", ".join(OUTPUT_SERIES)
        )
        where = where.replace("ts >= :start AND ts < :end", f"{ts} >= :start AND {ts} < :end")
        query = (
            f"SELECT tag_id, :start + make_interval(secs => b * :bucket) AS ts, "
            f"{_aggregates(OUTPUT_SERIES, hourly)} FROM ("
            f"  SELECT tag_id, floor(extract(epoch FROM {ts} - :start) / :bucket) AS b, "
            f"  {columns} FROM {table} WHERE {where}) s "
            "GROUP BY tag_id, b ORDER BY tag_id, b"
        )
    grouped: dict[int, list[Mapping[str, object]]] = {t: [] for t in tags}
    for row in session.execute(text(query), params).mappings():
        grouped[int(row["tag_id"])].append(dict(row))
    return {t: _build(start, end, bucket is None, bucket, OUTPUT_SERIES, grouped[t]) for t in tags}


# ------------------------------------------------------------------ asset analysis (SCR-03)


@dataclass(frozen=True)
class StatusPeriod:
    """A stretch of cycles that were not scored normally (shaded on the DI trend)."""

    start: datetime
    end: datetime
    status: str
    reason: str | None


def status_periods(
    session: Session,
    model_id: int,
    start: datetime,
    end: datetime,
    *,
    version_id: int | None = None,
    max_periods: int = 500,
) -> list[StatusPeriod]:
    """Runs of consecutive cycles with the same non-Running status (outside the operating
    mode, insufficient data, error ...) over [start, end), oldest first. Each run ends at
    the next cycle's time, so it covers the gap until scoring resumed."""
    _check(start, end, 1)
    version_filter = " AND version_id = :version_id" if version_id is not None else ""
    rows = session.execute(
        text(
            "WITH s AS ("
            "  SELECT ts, status, reason, lead(ts) OVER (ORDER BY ts) AS next_ts,"
            "  row_number() OVER (ORDER BY ts)"
            "  - row_number() OVER (PARTITION BY status, coalesce(reason, '') ORDER BY ts) AS grp"
            f" FROM score WHERE model_id = :model_id{version_filter}"
            "  AND ts >= :start AND ts < :end)"
            " SELECT min(ts) AS start, max(coalesce(next_ts, ts)) AS end, status, reason "
            " FROM s WHERE status <> 'Running' GROUP BY grp, status, reason "
            " ORDER BY min(ts) LIMIT :limit"
        ),
        {
            "model_id": model_id,
            "version_id": version_id,
            "start": start,
            "end": end,
            "limit": max_periods,
        },
    ).mappings()
    return [StatusPeriod(r["start"], r["end"], r["status"], r["reason"]) for r in rows]


@dataclass(frozen=True)
class SensorReadingOut:
    """One sensor's outputs at one cycle (the sensor table and contributors, SCR-03)."""

    tag_id: int
    actual: float | None
    predicted: float | None
    residual: float | None
    z: float | None
    contribution: float | None
    dq_status: str
    dq_rule: str | None
    used: bool | None


def cycle_outputs(session: Session, version_id: int, ts: datetime) -> list[SensorReadingOut]:
    """Every sensor's outputs of one version at one cycle."""
    rows = session.execute(
        text(
            "SELECT tag_id, actual, predicted, residual, z, contribution, dq_status, dq_rule, "
            "used FROM sensor_output WHERE version_id = :v AND ts = :ts ORDER BY tag_id"
        ),
        {"v": version_id, "ts": ts},
    ).mappings()
    return [SensorReadingOut(**dict(r)) for r in rows]


def latest_cycle(session: Session, version_id: int, at: datetime | None = None) -> datetime | None:
    """The newest cycle a version was scored at (at or before `at`, if given)."""
    found: datetime | None = session.execute(
        text(
            "SELECT max(ts) FROM score WHERE version_id = :v "
            "AND (CAST(:at AS timestamptz) IS NULL OR ts <= :at)"
        ),
        {"v": version_id, "at": at},
    ).scalar()
    return found


@dataclass(frozen=True)
class UnusedPeriod:
    """A run of cycles in which a sensor was not used in scoring (FR-VIS-02 overlays)."""

    start: datetime  # first cycle
    end: datetime  # last cycle
    status: str  # NE 107
    rule: str | None


def unused_periods(
    session: Session,
    version_ids: Iterable[int],
    tag_ids: Iterable[int],
    start: datetime,
    end: datetime,
    limit: int = 500,
) -> dict[int, list[UnusedPeriod]]:
    """Per tag: the runs of consecutive cycles where it was excluded from scoring (bad
    data, stale, flatline, manual exclusion ...), with the NE 107 status and rule. One
    query; at most `limit` runs per tag, the newest kept."""
    tags = sorted(set(tag_ids))
    out: dict[int, list[UnusedPeriod]] = {t: [] for t in tags}
    versions = sorted(set(version_ids))
    if not tags or not versions:
        return out
    rows = session.execute(
        text(
            "SELECT tag_id, min(ts) AS first, max(ts) AS last, dq_status, dq_rule FROM ("
            "  SELECT tag_id, ts, dq_status, dq_rule, used,"
            "    row_number() OVER (PARTITION BY tag_id ORDER BY ts)"
            "    - row_number() OVER (PARTITION BY tag_id, used, dq_status, dq_rule ORDER BY ts)"
            "    AS run"
            "  FROM sensor_output WHERE version_id = ANY(:versions) AND tag_id = ANY(:tags)"
            "  AND ts >= :start AND ts < :end) s "
            "WHERE used IS NOT TRUE "
            "GROUP BY tag_id, run, dq_status, dq_rule ORDER BY tag_id, first"
        ),
        {"versions": versions, "tags": tags, "start": start, "end": end},
    ).all()
    for tag_id, first, last, status, rule in rows:
        out[int(tag_id)].append(UnusedPeriod(first, last, str(status), rule))
    return {t: runs[-limit:] for t, runs in out.items()}
