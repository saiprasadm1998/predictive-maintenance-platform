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
    session: Session, model_id: int, start: datetime, end: datetime, px: int = 1000
) -> Trend:
    """DI and Health of a model over [start, end), across all its versions."""
    _check(start, end, px)
    params = {"model_id": model_id, "start": start, "end": end}
    if end - start < RAW_BELOW:
        rows = session.execute(
            text(
                "SELECT ts, di, health FROM score "
                "WHERE model_id = :model_id AND ts >= :start AND ts < :end ORDER BY ts"
            ),
            params,
        ).mappings()
        return _build(start, end, True, None, SCORE_SERIES, [dict(r) for r in rows])
    bucket = _bucket_s(start, end, px)
    hourly = end - start > HOURLY_ABOVE
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
            f"      FROM {table} WHERE model_id = :model_id AND {ts} >= :start AND {ts} < :end) s "
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
