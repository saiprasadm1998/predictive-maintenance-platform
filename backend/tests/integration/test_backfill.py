"""History import against PostgreSQL/TimescaleDB (UC-02, FR-ING-03, ARC §7.1.3)."""

from __future__ import annotations

import time
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import text

from pmp.core import Actor, Database, JobRegistry, JobStatus, Worker, enqueue, get_job
from pmp.ingestion import (
    BACKFILL_JOB,
    BackfillOptions,
    OverlapMode,
    count_samples,
    make_backfill_handler,
    run_backfill,
    server_now,
)
from pmp.registry import AssetLevel, AssetSpec, Criticality, TagSpec, upsert_asset, upsert_tag

pytestmark = pytest.mark.integration
ACTOR = Actor.system()
SOURCE = "gw-site-a-01"
TAGS = [f"K101.T{i}.PV" for i in range(1, 6)]


@pytest.fixture
def db(clean_ingestion: Database) -> Database:
    with clean_ingestion.session() as s:
        s.execute(text("TRUNCATE job RESTART IDENTITY"))
        upsert_asset(s, ACTOR, AssetSpec("SITE-A", "Site A", AssetLevel.SITE))
        upsert_asset(
            s, ACTOR, AssetSpec("K-101", "K-101", AssetLevel.EQUIPMENT, "SITE-A", Criticality.A)
        )
        for name in TAGS:
            upsert_tag(s, ACTOR, TagSpec(SOURCE, name, "K-101", "°C", 0, 150, 60))
    return clean_ingestion


def _now(db: Database) -> datetime:
    with db.session() as s:
        return server_now(s).replace(second=0, microsecond=0)


def _long_csv(path: Path, start: datetime, values: list[float]) -> Path:
    lines = ["ts,tag,value,quality"]
    lines += [
        f"{(start + timedelta(minutes=i)).isoformat()},{TAGS[0]},{v},Good"
        for i, v in enumerate(values)
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


def _values(db: Database) -> list[float]:
    with db.session() as s:
        return [r[0] for r in s.execute(text("SELECT value FROM sample ORDER BY ts"))]


def test_long_csv_loads_and_counts_reconcile(db: Database, tmp_path: Path) -> None:
    start = _now(db) - timedelta(days=30)
    path = _long_csv(tmp_path / "h.csv", start, [1.0, 2.0, 3.0])
    with path.open("a") as f:
        f.write(f"{start.isoformat()},{TAGS[0]},oops,Good\n")

    report = run_backfill(db, path, BackfillOptions(SOURCE))

    assert (report.rows_read, report.loaded, report.duplicates, report.rejected) == (4, 3, 0, 1)
    assert report.reconciles
    assert report.problems[0].row == 4
    assert _values(db) == [1.0, 2.0, 3.0]


def test_history_older_than_the_live_window_loads(db: Database, tmp_path: Path) -> None:
    path = _long_csv(tmp_path / "h.csv", _now(db) - timedelta(days=365), [1.0])
    assert run_backfill(db, path, BackfillOptions(SOURCE)).loaded == 1


def test_rerun_with_skip_changes_nothing(db: Database, tmp_path: Path) -> None:
    start = _now(db) - timedelta(days=2)
    run_backfill(db, _long_csv(tmp_path / "a.csv", start, [1.0, 2.0, 3.0]), BackfillOptions(SOURCE))
    report = run_backfill(
        db,
        _long_csv(tmp_path / "b.csv", start, [9.0, 9.0, 9.0]),
        BackfillOptions(SOURCE, mode=OverlapMode.SKIP),
    )
    assert (report.loaded, report.duplicates) == (0, 3)
    assert report.reconciles
    assert _values(db) == [1.0, 2.0, 3.0]


def test_overwrite_replaces_overlapping_samples(db: Database, tmp_path: Path) -> None:
    start = _now(db) - timedelta(days=2)
    run_backfill(db, _long_csv(tmp_path / "a.csv", start, [1.0, 2.0]), BackfillOptions(SOURCE))
    report = run_backfill(
        db,
        _long_csv(tmp_path / "b.csv", start, [5.0, 6.0, 7.0]),
        BackfillOptions(SOURCE, mode=OverlapMode.OVERWRITE),
    )
    assert (report.loaded, report.duplicates) == (1, 2)
    assert _values(db) == [5.0, 6.0, 7.0]


def test_preview_stores_nothing_and_reports_overlap(db: Database, tmp_path: Path) -> None:
    start = _now(db) - timedelta(days=2)
    run_backfill(db, _long_csv(tmp_path / "a.csv", start, [1.0, 2.0]), BackfillOptions(SOURCE))
    report = run_backfill(
        db,
        _long_csv(tmp_path / "b.csv", start, [1.0, 2.0, 3.0]),
        BackfillOptions(SOURCE),
        preview=True,
    )
    assert report.preview
    assert (report.rows_read, report.overlap, report.loaded) == (3, 2, 0)
    assert report.first_ts is not None
    with db.session() as s:
        assert count_samples(s) == 2


def _wide_parquet(path: Path, start: datetime, minutes: int) -> Path:
    rng = np.random.default_rng(7)
    columns: dict[str, Any] = {
        "ts": pa.array(pd.date_range(start, periods=minutes, freq="min", tz="UTC"))
    }
    for name in TAGS:
        columns[name] = rng.normal(70, 2, minutes)
    pq.write_table(pa.table(columns), path)
    return path


def test_a_month_of_minutes_for_five_tags_loads_and_reconciles(
    db: Database, tmp_path: Path
) -> None:
    """Scaled-down FR-ING-03 acceptance (the full 12 months x 50 tags is `make perf-backfill`)."""
    minutes = 30 * 24 * 60
    path = _wide_parquet(tmp_path / "month.parquet", _now(db) - timedelta(days=31), minutes)

    started = time.monotonic()
    report = run_backfill(db, path, BackfillOptions(SOURCE))
    elapsed = time.monotonic() - started

    assert report.rows_read == minutes * len(TAGS) == 216_000
    assert report.loaded == 216_000
    assert report.reconciles
    assert len(report.tags_found) == 5
    with db.session() as s:
        assert count_samples(s) == 216_000
    assert elapsed < 120, f"took {elapsed:.0f} s"


def test_backfill_runs_as_a_worker_job(db: Database, tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    _long_csv(uploads / "abc.csv", _now(db) - timedelta(days=1), [1.0, 2.0])
    registry = JobRegistry()
    registry.register(BACKFILL_JOB, make_backfill_handler(db, uploads))
    with db.session() as s:
        job_id = enqueue(
            s,
            BACKFILL_JOB,
            {
                "upload": "abc.csv",
                "options": BackfillOptions(SOURCE).to_payload(),
                "preview": False,
            },
        )

    assert Worker(db, registry, name="test").run_once()

    with db.session() as s:
        job = get_job(s, job_id)
    assert job is not None
    assert job.status is JobStatus.SUCCEEDED
    result: Mapping[str, Any] = job.result or {}
    assert (result["loaded"], result["reconciles"]) == (2, True)
    assert not (uploads / "abc.csv").exists()  # imported files are removed
