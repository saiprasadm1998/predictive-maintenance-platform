"""Load synthetic history through the real history-import path (plan 1.4 -> 1.3)."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy.orm import Session

from pmp.core import Database
from pmp.demo.generator import PlantSimulator
from pmp.demo.model import DemoTag
from pmp.ingestion import BackfillOptions, BackfillReport, Layout, OverlapMode, run_backfill
from pmp.registry import list_tags

WINDOW = timedelta(days=7)


def demo_tags(session: Session) -> list[DemoTag]:
    """Every registered tag, with what the simulator needs to know about it."""
    return [
        DemoTag(t.source, t.source_name, t.asset_code, t.role_code, t.unit, t.range_lo, t.range_hi)
        for t in list_tags(session)
    ]


def write_history_files(
    simulator: PlantSimulator,
    start: datetime,
    end: datetime,
    directory: Path,
    on_progress: Callable[[float], None] | None = None,
) -> dict[str, Path]:
    """Long-format Parquet, one file per gateway source, written a week at a time."""
    writers: dict[str, pq.ParquetWriter] = {}
    paths: dict[str, Path] = {}
    window_start = start
    total = (end - start).total_seconds()
    try:
        while window_start < end:
            window_end = min(window_start + WINDOW, end)
            frame = simulator.samples_between(window_start, window_end)
            for source, group in frame.groupby("source", sort=True):
                table = pa.Table.from_pandas(
                    group[["ts", "tag", "value", "quality"]], preserve_index=False
                )
                name = str(source)
                if name not in writers:
                    paths[name] = directory / f"{name}.parquet"
                    writers[name] = pq.ParquetWriter(paths[name], table.schema)
                writers[name].write_table(table)
            window_start = window_end
            if on_progress is not None:
                on_progress(100.0 * (window_start - start).total_seconds() / total)
    finally:
        for writer in writers.values():
            writer.close()
    return paths


def load_history(
    database: Database,
    simulator: PlantSimulator,
    *,
    days: int,
    work_dir: Path,
    on_progress: Callable[[str, float], None] | None = None,
) -> dict[str, BackfillReport]:
    """Generate `days` of 1-minute history ending at the anchor and import it (overwrite,
    so running it again is harmless). Returns one import report per gateway source."""
    end = simulator.anchor
    start = end - timedelta(days=days)
    work_dir.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="demo-history-", dir=work_dir))
    try:
        paths = write_history_files(
            simulator,
            start,
            end,
            directory,
            partial(on_progress, "generate") if on_progress else None,
        )
        reports = {}
        for source, path in sorted(paths.items()):
            options = BackfillOptions(source, layout=Layout.LONG, mode=OverlapMode.OVERWRITE)
            callback = partial(on_progress, f"load {source}") if on_progress else None
            reports[source] = run_backfill(database, path, options, on_progress=callback)
        return reports
    finally:
        shutil.rmtree(directory, ignore_errors=True)
