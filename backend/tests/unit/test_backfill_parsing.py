"""History-file parsing and validation without a database (UC-02, FR-ING-03)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pmp.ingestion import BackfillError, BackfillOptions, Layout
from pmp.ingestion import backfill as bf

FUTURE_LIMIT = pd.Timestamp("2026-10-15T12:05:00Z")
TAGS = {"K101.TI1012.PV": 1, "K101.ZI1015.PV": 2}


class FakeDatabase:
    @contextmanager
    def session(self) -> Iterator[None]:
        yield None


@pytest.fixture(autouse=True)
def _fake_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    def resolve(_session: Any, _source: str, names: Any) -> dict[str, int]:
        return {n: TAGS[n] for n in names if n in TAGS}

    monkeypatch.setattr(bf, "resolve_tag_ids", resolve)


def _long(rows: list[list[str]], **options: Any) -> tuple[pd.DataFrame, bf.BackfillReport]:
    frame = pd.DataFrame(rows, columns=["ts", "tag", "value", "quality"])
    report = bf.BackfillReport(layout=Layout.LONG)
    staged = bf._long_chunk(
        FakeDatabase(),  # type: ignore[arg-type]
        frame,
        0,
        BackfillOptions("gw", **options),
        report,
        FUTURE_LIMIT,
    )
    return staged, report


def test_long_rows_are_validated_row_by_row() -> None:
    staged, report = _long(
        [
            ["2026-10-01T00:00:00Z", "K101.TI1012.PV", "71.5", ""],  # 1 ok, Good
            ["2026-10-01T00:01:00+04:00", "K101.ZI1015.PV", "400", "Bad"],  # 2 ok, offset
            ["2026-10-01T00:02:00", "K101.TI1012.PV", "71.6", ""],  # 3 no offset
            ["not a time", "K101.TI1012.PV", "71.6", ""],  # 4 bad time
            ["2026-10-01T00:03:00Z", "K101.NOPE.PV", "1", ""],  # 5 unknown tag
            ["2026-10-01T00:04:00Z", "K101.TI1012.PV", "abc", ""],  # 6 bad value
            ["2026-10-01T00:05:00Z", "K101.TI1012.PV", "1", "great"],  # 7 bad quality
            ["2026-10-16T00:00:00Z", "K101.TI1012.PV", "1", ""],  # 8 future
            ["2026-10-01T00:06:00Z", "K101.TI1012.PV", "1", "2150760448"],  # 9 ok, raw code
            ["", "", "", ""],  # blank: ignored
        ]
    )
    assert report.rows_read == 9
    assert report.rejected == 6
    assert dict(report.rejected_by_reason) == {
        "timestamp_without_offset": 1,
        "invalid_timestamp": 1,
        "unregistered_tag": 1,
        "invalid_value": 1,
        "invalid_quality": 1,
        "in_future": 1,
    }
    assert [p.row for p in report.problems] == [3, 4, 5, 6, 7, 8]
    assert dict(report.unmapped) == {"K101.NOPE.PV": 1}
    assert len(staged) == 3
    assert list(staged["quality"]) == [0, 2, 2]
    assert staged["quality_code"].iloc[2] == 0x80320000
    assert staged["ts"].iloc[1] == pd.Timestamp("2026-09-30T20:01:00Z")


def test_naive_timestamps_can_be_read_as_utc() -> None:
    staged, report = _long([["2026-10-01 00:02:00", "K101.TI1012.PV", "1", ""]], naive_as_utc=True)
    assert report.rejected == 0
    assert staged["ts"].iloc[0] == pd.Timestamp("2026-10-01T00:02:00Z")


def test_wide_chunks_melt_into_samples_and_skip_empty_cells() -> None:
    frame = pd.DataFrame(
        {
            "ts": ["2026-10-01T00:00:00Z", "2026-10-01T00:01:00Z", "bad"],
            "K101.TI1012.PV": ["71.5", "", "72"],
            "K101.ZI1015.PV": ["400", "401", "402"],
            "UNKNOWN.PV": ["1", "2", ""],
        }
    )
    report = bf.BackfillReport(layout=Layout.WIDE)
    staged = bf._wide_chunk(frame, 0, BackfillOptions("gw"), report, TAGS, FUTURE_LIMIT)
    assert report.rows_read == 7  # non-empty cells
    assert report.rejected == 4  # 2 cells on the bad-time row, 2 in the unknown column
    assert dict(report.unmapped) == {"UNKNOWN.PV": 2}
    assert len(staged) == 3
    assert sorted(staged["tag_id"].tolist()) == [1, 2, 2]


def test_layout_detection() -> None:
    options = BackfillOptions("gw")
    assert bf.detect_layout(["TS", "Tag", "Value"], options) is Layout.LONG
    assert bf.detect_layout(["ts", "K101.TI1012.PV"], options) is Layout.WIDE
    with pytest.raises(BackfillError, match="timestamp column"):
        bf.detect_layout(["time", "tag", "value"], options)
    with pytest.raises(BackfillError, match="no tag columns"):
        bf.detect_layout(["ts"], options)


def test_csv_and_parquet_are_read_in_chunks(tmp_path: Path) -> None:
    csv = tmp_path / "h.csv"
    csv.write_text(
        "ts,tag,value\n"
        + "".join(f"2026-10-01T00:{i:02d}:00Z,K101.TI1012.PV,{i}\n" for i in range(25))
    )
    chunks = list(bf._chunks(csv, 10))
    assert [(offset, len(frame)) for offset, frame in chunks] == [(0, 10), (10, 10), (20, 5)]
    assert bf._total_rows(csv) == 25

    parquet = tmp_path / "h.parquet"
    table = pa.table(
        {
            "ts": pa.array(pd.date_range("2026-10-01", periods=25, freq="min", tz="UTC")),
            "tag": ["K101.TI1012.PV"] * 25,
            "value": [float(i) for i in range(25)],
        }
    )
    pq.write_table(table, parquet)
    assert bf._total_rows(parquet) == 25
    frame = next(bf._chunks(parquet, 100))[1]
    ts, reasons = bf._parse_timestamps(frame["ts"], naive_as_utc=False)
    assert reasons.isna().all()
    assert str(ts.dt.tz) == "UTC"


def test_unreadable_files_are_refused(tmp_path: Path) -> None:
    other = tmp_path / "h.xlsx"
    other.write_text("x")
    with pytest.raises(BackfillError, match=r"Only \.csv and \.parquet"):
        bf.check_file(other, BackfillOptions("gw"))


def test_options_survive_the_job_payload() -> None:
    options = BackfillOptions("gw", Layout.WIDE, bf.OverlapMode.OVERWRITE, True)
    assert BackfillOptions.from_payload(options.to_payload()) == options
