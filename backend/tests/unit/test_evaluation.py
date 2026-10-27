"""AC-04 evaluation report (plan 7.4): reading the event history and the summary figures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pmp.evaluation import (
    AlertOutcome,
    Evaluation,
    EvaluationError,
    Event,
    EventOutcome,
    format_report,
    read_events,
)

ANCHOR = datetime(2026, 10, 21, tzinfo=UTC)


def test_event_times_may_be_relative_to_the_anchor(tmp_path: Path) -> None:
    path = tmp_path / "events.csv"
    path.write_text(
        "asset,start,end,description,detectable\n"
        "K-101,-21d,0d,Thrust bearing,yes\n"
        "P-205,-10h,-7h,Excursion,\n"
        "P-202,2026-10-19T00:00:00Z,2026-10-21T00:00:00Z,Link lost,no\n",
        encoding="utf-8",
    )
    k101, p205, p202 = read_events(path, ANCHOR)
    assert (k101.start, k101.end) == (ANCHOR - timedelta(days=21), ANCHOR)
    assert (p205.start, p205.end) == (ANCHOR - timedelta(hours=10), ANCHOR - timedelta(hours=7))
    assert p205.detectable  # empty means yes
    assert not p202.detectable


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("K-101,soon,0d,x", "is not a time"),
        ("K-101,2026-10-01T00:00:00,0d,x", "needs a time zone"),
        ("K-101,0d,-1d,x", "start must be before the end"),
    ],
)
def test_bad_event_rows_are_refused(tmp_path: Path, row: str, message: str) -> None:
    path = tmp_path / "events.csv"
    path.write_text(f"asset,start,end,description\n{row}\n", encoding="utf-8")
    with pytest.raises(EvaluationError, match=message):
        read_events(path, ANCHOR)


def test_the_summary_follows_ac_04() -> None:
    def event(asset: str, days: int) -> Event:
        return Event(asset, ANCHOR - timedelta(days=days), ANCHOR, f"{asset} fault")

    found = EventOutcome(event("K-101", 21), ANCHOR - timedelta(days=9))
    also = EventOutcome(event("K-201", 4), ANCHOR - timedelta(days=3))
    missed = EventOutcome(event("P-104A", 3), None)
    alerts = [
        AlertOutcome(1, "K-101", "K-101 / main", ANCHOR - timedelta(days=9), "Warning", "x"),
        AlertOutcome(2, "E-110", "E-110 / main", ANCHOR - timedelta(days=2), "Warning", None),
    ]
    result = Evaluation(ANCHOR - timedelta(days=28), ANCHOR, 8 * 4.0, [found, also, missed], alerts)
    assert result.detected_share == pytest.approx(2 / 3)
    assert result.median_lead_time == timedelta(days=6)  # median of 9 and 3 days
    assert result.false_alerts == 1
    assert result.false_per_model_week == pytest.approx(1 / 32)
    assert not result.meets_targets  # 67 % is below the 70 % starting target
    text = "\n".join(format_report(result))
    assert "MISSED" in text
    assert "FALSE (no event)" in text
    assert "Detectable events alerted: 67% (target at least 70%)" in text
