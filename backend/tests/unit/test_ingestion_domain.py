"""Ingestion payload rules (ARC §7.1.1, FR-ING-04, -05)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from pmp.ingestion import BatchIn, Quality, RejectReason, map_quality
from pmp.ingestion.domain import check_window

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
WEEK = timedelta(days=7)


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        (None, (Quality.GOOD, None)),  # omitted quality means Good
        ("Good", (Quality.GOOD, None)),
        ("Uncertain", (Quality.UNCERTAIN, None)),
        ("Bad", (Quality.BAD, None)),
        (0, (Quality.GOOD, 0)),
        (0x40000000, (Quality.UNCERTAIN, 0x40000000)),
        (0x80000000, (Quality.BAD, 0x80000000)),
        (0x80320000, (Quality.BAD, 0x80320000)),  # BadCommunicationError keeps its code
        (0xC0000000, (Quality.BAD, 0xC0000000)),  # reserved severity: treat as Bad
        (0x00D80000, (Quality.GOOD, 0x00D80000)),  # Good with sub-status bits
    ],
)
def test_quality_mapping(q: int | str | None, expected: tuple[Quality, int | None]) -> None:
    assert map_quality(q) == expected


@pytest.mark.parametrize("q", ["good", "GOOD", "OK", -1, 0x1_0000_0000])
def test_invalid_quality_is_refused(q: int | str) -> None:
    with pytest.raises(ValueError, match=r"quality|StatusCode"):
        map_quality(q)


def _batch(sample: dict[str, Any]) -> BatchIn:
    return BatchIn.model_validate({"source": "gw-site-a-01", "samples": [sample]})


def test_arc_example_payload_parses() -> None:
    batch = BatchIn.model_validate(
        {
            "source": "gw-site-a-01",
            "samples": [
                {"tag": "K101.TI1012.PV", "ts": "2026-10-08T14:20:00Z", "v": 78.42, "q": 0},
                {"tag": "K101.ZI1015.PV", "ts": "2026-10-08T14:20:00Z", "v": 412.0, "q": "Good"},
                {"tag": "K101.TI1018.PV", "ts": "2026-10-08T14:20:00Z", "v": 69.0, "q": "Bad"},
            ],
        }
    )
    assert len(batch.samples) == 3
    assert batch.samples[0].ts.utcoffset() == timedelta(0)


def test_timestamps_with_an_offset_are_accepted() -> None:
    sample = _batch({"tag": "T", "ts": "2026-10-08T18:20:00+04:00", "v": 1}).samples[0]
    assert sample.ts.astimezone(UTC).hour == 14
    assert sample.v == 1.0


@pytest.mark.parametrize(
    "sample",
    [
        {"tag": "T", "ts": "2026-10-08T14:20:00", "v": 1.0},  # no offset
        {"tag": "T", "ts": "yesterday", "v": 1.0},
        {"tag": "T", "ts": "2026-10-08T14:20:00Z"},  # value missing
        {"tag": "T", "ts": "2026-10-08T14:20:00Z", "v": "78.4"},
        {"tag": "T", "ts": "2026-10-08T14:20:00Z", "v": True},
        {"tag": "T", "ts": "2026-10-08T14:20:00Z", "v": 1.0, "q": True},
        {"tag": "T", "ts": "2026-10-08T14:20:00Z", "v": 1.0, "q": "good"},
        {"tag": "", "ts": "2026-10-08T14:20:00Z", "v": 1.0},
        {"tag": "T", "ts": "2026-10-08T14:20:00Z", "v": 1.0, "extra": 1},
    ],
)
def test_malformed_samples_fail_the_schema(sample: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _batch(sample)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_values_fail_the_schema(value: str) -> None:
    payload = json.loads(
        '{"source": "s", "samples": [{"tag": "T", "ts": "2026-10-08T14:20:00Z", "v": '
        + value
        + "}]}"
    )
    with pytest.raises(ValidationError):
        BatchIn.model_validate(payload)


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (timedelta(0), None),
        (timedelta(minutes=4, seconds=59), None),  # within the 5-minute future tolerance
        (timedelta(minutes=5, seconds=1), RejectReason.IN_FUTURE),
        (-timedelta(days=6, hours=23), None),  # late but inside the 7-day window
        (-timedelta(days=7, seconds=1), RejectReason.TOO_OLD),
    ],
)
def test_time_windows(offset: timedelta, expected: RejectReason | None) -> None:
    assert check_window(NOW + offset, NOW, WEEK) is expected
