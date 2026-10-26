"""History import (UC-02, FR-ING-03, FR-ING-04, ARC-001 §7.1.3).

Reads CSV or Parquet in long format (ts, tag, value, quality) or wide format (ts plus
one column per tag), in chunks so files far larger than memory load safely. Every row is
validated; good rows load even when others are rejected, and every count reconciles:

    rows read = loaded + duplicates + rejected

Each chunk is committed on its own, so a long import shows progress and a crash loses at
most one chunk. Re-running is harmless: rows that already exist count as duplicates
(skip) or are replaced (overwrite). History is not subject to the live 7-day late window;
timestamps more than 5 minutes in the future are still rejected.
"""

from __future__ import annotations

import io
import math
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sqlalchemy import text

from pmp.core import Database, RetainedTable, refresh_hourly, report_progress
from pmp.ingestion.domain import FUTURE_TOLERANCE, map_quality
from pmp.ingestion.service import merge_staged, server_now, stage_text
from pmp.registry import resolve_tag_ids

CHUNK_CELLS = 200_000  # samples per chunk: bounds memory and transaction size
MAX_PROBLEMS = 100
_OFFSET = r"(?:[Zz]|[+-]\d{2}(?::?\d{2})?)$"


SAMPLES = RetainedTable("sample", "sample_1h")  # the module's time series (ARC §6.3)


class Layout(StrEnum):
    LONG = "long"
    WIDE = "wide"


class OverlapMode(StrEnum):
    SKIP = "skip"  # keep existing samples (UC-02 3a)
    OVERWRITE = "overwrite"


class Reason(StrEnum):
    INVALID_TIMESTAMP = "invalid_timestamp"
    NO_OFFSET = "timestamp_without_offset"
    UNREGISTERED_TAG = "unregistered_tag"
    INVALID_VALUE = "invalid_value"
    INVALID_QUALITY = "invalid_quality"
    IN_FUTURE = "in_future"


class BackfillError(Exception):
    """The file as a whole cannot be imported (unreadable, missing columns, ...)."""


@dataclass(frozen=True)
class BackfillOptions:
    source: str
    layout: Layout | None = None  # None: detect from the columns
    mode: OverlapMode = OverlapMode.SKIP
    naive_as_utc: bool = False  # treat timestamps without an offset as UTC
    ts_column: str = "ts"
    tag_column: str = "tag"
    value_column: str = "value"
    quality_column: str = "quality"

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["layout"] = self.layout.value if self.layout else None
        payload["mode"] = self.mode.value
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> BackfillOptions:
        values = dict(payload)
        values["layout"] = Layout(values["layout"]) if values.get("layout") else None
        values["mode"] = OverlapMode(values.get("mode", OverlapMode.SKIP))
        return cls(**values)


@dataclass(frozen=True)
class RowProblem:
    row: int  # 1-based data row (CSV line = row + 1, after the header)
    reason: str
    detail: str


@dataclass
class BackfillReport:
    layout: Layout | None = None
    preview: bool = False
    rows_read: int = 0  # samples found: long rows, or non-empty wide cells
    loaded: int = 0
    duplicates: int = 0  # already in the database, or repeated within the file
    rejected: int = 0
    overlap: int = 0  # preview: samples that already exist
    rejected_by_reason: Counter[str] = field(default_factory=Counter)
    unmapped: Counter[str] = field(default_factory=Counter)
    problems: list[RowProblem] = field(default_factory=list)
    tags_found: set[int] = field(default_factory=set)
    first_ts: datetime | None = None
    last_ts: datetime | None = None

    @property
    def reconciles(self) -> bool:
        if self.preview:
            return True
        return self.loaded + self.duplicates + self.rejected == self.rows_read

    def as_dict(self) -> dict[str, Any]:
        return {
            "layout": self.layout.value if self.layout else None,
            "preview": self.preview,
            "rows_read": self.rows_read,
            "loaded": self.loaded,
            "duplicates": self.duplicates,
            "rejected": self.rejected,
            "overlap": self.overlap,
            "reconciles": self.reconciles,
            "rejected_by_reason": dict(self.rejected_by_reason),
            "unmapped_tags": dict(self.unmapped),
            "tags_found": len(self.tags_found),
            "first_ts": self.first_ts.isoformat() if self.first_ts else None,
            "last_ts": self.last_ts.isoformat() if self.last_ts else None,
            "problems": [asdict(p) for p in self.problems],
        }

    def summary(self) -> str:
        head = "Preview (nothing stored)" if self.preview else "History import finished"
        lines = [
            f"{head}: {self.layout.value if self.layout else '?'} format",
            f"  rows read   {self.rows_read:>12,}",
        ]
        if self.preview:
            lines.append(
                f"  would load  {self.rows_read - self.rejected:>12,}"
                f"  ({self.overlap:,} already stored)"
            )
        else:
            lines += [
                f"  loaded      {self.loaded:>12,}",
                f"  duplicates  {self.duplicates:>12,}",
            ]
        lines.append(f"  rejected    {self.rejected:>12,}  {dict(self.rejected_by_reason)}")
        if self.first_ts:
            lines.append(
                f"  time range  {self.first_ts:%Y-%m-%d %H:%M} to "
                f"{self.last_ts:%Y-%m-%d %H:%M} UTC, {len(self.tags_found)} tags"
            )
        if self.unmapped:
            lines.append(f"  unmapped    {', '.join(sorted(self.unmapped))}")
        if not self.preview:
            lines.append(f"  counts reconcile: {'yes' if self.reconciles else 'NO'}")
        for problem in self.problems[:10]:
            lines.append(f"  row {problem.row}: {problem.reason} ({problem.detail})")
        return "\n".join(lines)


# ------------------------------------------------------------------ reading


def _normalise(name: object) -> str:
    return str(name).strip().lower()


def _columns(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            header = pd.read_csv(path, nrows=0, encoding="utf-8-sig")
            return [str(c) for c in header.columns]
        if suffix == ".parquet":
            return list(pq.ParquetFile(path).schema_arrow.names)
    except (OSError, ValueError, pd.errors.ParserError) as error:
        raise BackfillError(f"Cannot read {path.name}: {error}") from None
    raise BackfillError("Only .csv and .parquet files can be imported")


def _total_rows(path: Path) -> int:
    if path.suffix.lower() == ".parquet":
        return int(pq.ParquetFile(path).metadata.num_rows)
    lines = 0
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            lines += block.count(b"\n")
    return max(lines - 1, 1)


def _chunks(path: Path, rows_per_chunk: int) -> Iterator[tuple[int, pd.DataFrame]]:
    """Yield (row offset, chunk). CSV values arrive as text; Parquet keeps its types."""
    if path.suffix.lower() == ".parquet":
        offset = 0
        for batch in pq.ParquetFile(path).iter_batches(batch_size=rows_per_chunk):
            frame = batch.to_pandas()
            yield offset, frame
            offset += len(frame)
        return
    offset = 0
    reader = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
        chunksize=rows_per_chunk,
        encoding="utf-8-sig",
        skip_blank_lines=False,
    )
    for frame in reader:
        yield offset, frame
        offset += len(frame)


# ------------------------------------------------------------------ validation helpers


def _parse_timestamps(series: pd.Series, naive_as_utc: bool) -> tuple[pd.Series, pd.Series]:
    """Return (UTC timestamps, reason per row or None)."""
    reasons = pd.Series(None, index=series.index, dtype=object)
    if pd.api.types.is_datetime64_any_dtype(series):
        if getattr(series.dt, "tz", None) is not None:
            return series.dt.tz_convert("UTC"), reasons
        if not naive_as_utc:
            reasons[:] = Reason.NO_OFFSET.value
        return series.dt.tz_localize("UTC"), reasons
    text = series.astype(str).str.strip()
    parsed = pd.to_datetime(text, utc=True, errors="coerce", format="ISO8601")
    reasons[parsed.isna()] = Reason.INVALID_TIMESTAMP.value
    if not naive_as_utc:
        naive = ~text.str.contains(_OFFSET, regex=True) & parsed.notna()
        reasons[naive] = Reason.NO_OFFSET.value
    return parsed, reasons


def _parse_values(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        values = series.astype("float64")
    else:
        values = pd.to_numeric(series.astype(str).str.strip(), errors="coerce")
    return values.where(np.isfinite(values))


def _quality_lookup(raw: object) -> tuple[int, int | None] | None:
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        q: int | str | None = None
    else:
        text = str(raw).strip()
        if not text:
            q = None
        elif text.isdigit():
            q = int(text)
        else:
            q = text
    try:
        category, code = map_quality(q)
    except ValueError:
        return None
    return int(category), code


def _parse_quality(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (category, raw code, invalid mask)."""
    lookup = {value: _quality_lookup(value) for value in series.unique()}
    mapped = series.map(lookup)
    invalid = mapped.isna()
    category = mapped.map(lambda m: m[0] if m else 0)
    code = mapped.map(lambda m: m[1] if m else None).astype("Int64")
    return category, code, invalid


def _flag(reasons: pd.Series, mask: pd.Series, reason: Reason) -> None:
    """Set a reason where none is set yet (the first failing check wins)."""
    reasons[mask & reasons.isna()] = reason.value


# ------------------------------------------------------------------ the import


def detect_layout(columns: list[str], options: BackfillOptions) -> Layout:
    names = {_normalise(c) for c in columns}
    if _normalise(options.ts_column) not in names:
        raise BackfillError(f"The file has no timestamp column '{options.ts_column}'")
    long = {_normalise(options.tag_column), _normalise(options.value_column)} <= names
    if options.layout is Layout.LONG and not long:
        raise BackfillError(
            f"Long format needs the columns '{options.tag_column}' and '{options.value_column}'"
        )
    if options.layout is not None:
        return options.layout
    if long:
        return Layout.LONG
    if len(names) < 2:
        raise BackfillError("The file has no tag columns")
    return Layout.WIDE


def check_file(path: Path, options: BackfillOptions) -> Layout:
    """Cheap up-front check (readable, right columns). Raises BackfillError."""
    return detect_layout(_columns(path), options)


def run_backfill(
    database: Database,
    path: Path,
    options: BackfillOptions,
    *,
    preview: bool = False,
    on_progress: Callable[[float], None] | None = None,
) -> BackfillReport:
    """Import (or preview) one file. File-level problems raise BackfillError."""
    columns = _columns(path)
    layout = detect_layout(columns, options)
    report = BackfillReport(layout=layout, preview=preview)
    ts_col = _normalise(options.ts_column)
    # Long files: match column names case-insensitively. Wide files: tag columns keep
    # their exact names (they are tag names); only the timestamp column is matched.
    if layout is Layout.LONG:
        rename = {c: _normalise(c) for c in columns}
    else:
        rename = {c: ts_col for c in columns if _normalise(c) == ts_col}

    with database.session() as session:
        now = server_now(session)
    future_limit = pd.Timestamp(now + FUTURE_TOLERANCE)

    tag_columns: dict[str, int] = {}
    if layout is Layout.WIDE:
        tag_names = [c for c in columns if _normalise(c) != ts_col]
        with database.session() as session:
            tag_columns = resolve_tag_ids(session, options.source, tag_names)
        if not tag_columns:
            raise BackfillError(
                f"None of the {len(tag_names)} tag columns is registered for source "
                f"'{options.source}'"
            )
        rows_per_chunk = max(1_000, CHUNK_CELLS // max(len(tag_names), 1))
    else:
        rows_per_chunk = CHUNK_CELLS

    total = _total_rows(path)
    done = 0
    for offset, frame in _chunks(path, rows_per_chunk):
        frame = frame.rename(columns=rename)
        if layout is Layout.LONG:
            staged = _long_chunk(database, frame, offset, options, report, future_limit)
        else:
            staged = _wide_chunk(frame, offset, options, report, tag_columns, future_limit)
        _store_chunk(database, staged, options, report, preview)
        done += len(frame)
        percent = min(100.0, 100.0 * done / total)
        report_progress(percent, rows_read=report.rows_read, loaded=report.loaded)
        if on_progress is not None:
            on_progress(percent)
    if not preview and report.loaded and report.first_ts and report.last_ts:
        # history lands behind the hourly aggregate's refresh window (ARC §6.3)
        refresh_hourly(database, SAMPLES.hourly, report.first_ts, report.last_ts)
    return report


def _record_rejections(
    report: BackfillReport, reasons: pd.Series, rows: pd.Series, details: pd.Series
) -> None:
    rejected = reasons.notna()
    count = int(rejected.sum())
    if not count:
        return
    report.rejected += count
    for reason, n in reasons[rejected].value_counts().items():
        report.rejected_by_reason[str(reason)] += int(n)
    room = MAX_PROBLEMS - len(report.problems)
    if room > 0:
        for row, reason, detail in zip(
            rows[rejected][:room],
            reasons[rejected][:room],
            details[rejected][:room],
            strict=True,
        ):
            report.problems.append(RowProblem(int(row), str(reason), str(detail)[:200]))


def _long_chunk(
    database: Database,
    frame: pd.DataFrame,
    offset: int,
    options: BackfillOptions,
    report: BackfillReport,
    future_limit: pd.Timestamp,
) -> pd.DataFrame:
    tag_col, value_col = _normalise(options.tag_column), _normalise(options.value_column)
    ts_col, quality_col = _normalise(options.ts_column), _normalise(options.quality_column)
    rows = pd.Series(np.arange(offset + 1, offset + len(frame) + 1), index=frame.index)
    text = frame.astype(str)
    blank = (text.apply(lambda c: c.str.strip()) == "").all(axis=1)
    frame, rows, text = frame[~blank], rows[~blank], text[~blank]
    report.rows_read += len(frame)

    ts, reasons = _parse_timestamps(frame[ts_col], options.naive_as_utc)
    tags = frame[tag_col].astype(str).str.strip()
    with database.session() as session:
        ids = resolve_tag_ids(session, options.source, tags.unique())
    tag_ids = tags.map(ids)
    unknown = tag_ids.isna()
    _flag(reasons, unknown, Reason.UNREGISTERED_TAG)
    for name, n in tags[unknown & reasons.eq(Reason.UNREGISTERED_TAG.value)].value_counts().items():
        report.unmapped[str(name)] += int(n)
    values = _parse_values(frame[value_col])
    _flag(reasons, values.isna(), Reason.INVALID_VALUE)
    if quality_col in frame.columns:
        category, code, bad_quality = _parse_quality(frame[quality_col])
        _flag(reasons, bad_quality, Reason.INVALID_QUALITY)
    else:
        category = pd.Series(0, index=frame.index)
        code = pd.Series(pd.NA, index=frame.index, dtype="Int64")
    _flag(reasons, ts.notna() & (ts > future_limit), Reason.IN_FUTURE)

    detail = text[ts_col] + " | " + text[tag_col] + " | " + text[value_col]
    _record_rejections(report, reasons, rows, detail)
    ok = reasons.isna()
    return pd.DataFrame(
        {
            "tag_id": tag_ids[ok].astype("int64"),
            "ts": ts[ok],
            "value": values[ok],
            "quality": category[ok].astype("int64"),
            "quality_code": code[ok],
        }
    )


def _wide_chunk(
    frame: pd.DataFrame,
    offset: int,
    options: BackfillOptions,
    report: BackfillReport,
    tag_columns: Mapping[str, int],
    future_limit: pd.Timestamp,
) -> pd.DataFrame:
    ts_col = _normalise(options.ts_column)
    ts, ts_reasons = _parse_timestamps(frame[ts_col], options.naive_as_utc)
    rows = pd.Series(np.arange(offset + 1, offset + len(frame) + 1), index=frame.index)
    parts = []
    for column in frame.columns:
        if column == ts_col:
            continue
        cells = frame[column]
        present = cells.notna() & (cells.astype(str).str.strip() != "")
        n = int(present.sum())
        if not n:
            continue
        report.rows_read += n
        reasons = ts_reasons[present].copy()
        name = str(column)
        if name not in tag_columns:
            reasons[:] = reasons.fillna(Reason.UNREGISTERED_TAG.value)
            report.unmapped[str(column)] += int(reasons.eq(Reason.UNREGISTERED_TAG.value).sum())
            _record_rejections(
                report, reasons, rows[present], cells[present].astype(str).radd(f"{column} = ")
            )
            continue
        values = _parse_values(cells[present])
        _flag(reasons, values.isna(), Reason.INVALID_VALUE)
        cell_ts = ts[present]
        _flag(reasons, cell_ts.notna() & (cell_ts > future_limit), Reason.IN_FUTURE)
        _record_rejections(
            report, reasons, rows[present], cells[present].astype(str).radd(f"{column} = ")
        )
        ok = reasons.isna()
        parts.append(
            pd.DataFrame(
                {
                    "tag_id": tag_columns[name],
                    "ts": cell_ts[ok],
                    "value": values[ok],
                    "quality": 0,
                    "quality_code": pd.Series(pd.NA, index=cell_ts[ok].index, dtype="Int64"),
                }
            )
        )
    if not parts:
        return pd.DataFrame(columns=["tag_id", "ts", "value", "quality", "quality_code"])
    return pd.concat(parts, ignore_index=True)


def _store_chunk(
    database: Database,
    staged: pd.DataFrame,
    options: BackfillOptions,
    report: BackfillReport,
    preview: bool,
) -> None:
    if staged.empty:
        return
    before = len(staged)
    staged = staged.drop_duplicates(subset=["tag_id", "ts"], keep="last")
    repeated = before - len(staged)  # the same tag and time twice in the file: last wins
    report.tags_found.update(int(t) for t in staged["tag_id"].unique())
    low: datetime = staged["ts"].min().to_pydatetime()
    high: datetime = staged["ts"].max().to_pydatetime()
    report.first_ts = min(report.first_ts, low) if report.first_ts else low
    report.last_ts = max(report.last_ts, high) if report.last_ts else high

    buffer = io.StringIO()
    staged.to_csv(
        buffer,
        sep="\t",
        header=False,
        index=False,
        na_rep="\\N",
        columns=["tag_id", "ts", "value", "quality", "quality_code"],
    )
    with database.session() as session:
        stage_text(session, buffer.getvalue())
        if preview:  # count what already exists; nothing is written
            report.overlap += repeated + int(
                session.scalar(
                    text(
                        "SELECT count(*) FROM sample_stage s JOIN sample t "
                        "ON t.tag_id = s.tag_id AND t.ts = s.ts WHERE t.ts BETWEEN :low AND :high"
                    ),
                    {"low": low, "high": high},
                )
                or 0
            )
            return
        new, existing = merge_staged(session, overwrite=options.mode is OverlapMode.OVERWRITE)
    report.loaded += new
    report.duplicates += existing + repeated


# ------------------------------------------------------------------ background job

BACKFILL_JOB = "ingest.backfill"


def make_backfill_handler(
    database: Database, upload_dir: Path
) -> Callable[[Mapping[str, Any]], Mapping[str, Any]]:
    """The worker's handler for history-import jobs (ARC §7.1.3: processed as a job).

    Payload: {"upload": file name in upload_dir, "options": {...}, "preview": bool}.
    The uploaded file is deleted after a successful import; previews keep it so the same
    upload can then be loaded without sending it again.
    """

    def handle(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        path = upload_dir / Path(str(payload["upload"])).name
        options = BackfillOptions.from_payload(payload["options"])
        preview = bool(payload.get("preview", False))
        try:
            report = run_backfill(database, path, options, preview=preview)
        except BackfillError as error:
            return {"error": str(error)}
        if not preview:
            path.unlink(missing_ok=True)
        return report.as_dict()

    return handle
