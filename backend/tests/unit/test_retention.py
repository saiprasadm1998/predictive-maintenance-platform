"""Retention cut-offs (NFR-DATA-01)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pmp.core import months_before


@pytest.mark.parametrize(
    ("now", "months", "expected"),
    [
        (datetime(2026, 10, 21, 8, tzinfo=UTC), 24, datetime(2024, 10, 21, 8, tzinfo=UTC)),
        (datetime(2026, 3, 31, tzinfo=UTC), 1, datetime(2026, 2, 28, tzinfo=UTC)),
        (datetime(2028, 3, 31, tzinfo=UTC), 1, datetime(2028, 2, 29, tzinfo=UTC)),
        (datetime(2026, 1, 15, tzinfo=UTC), 60, datetime(2021, 1, 15, tzinfo=UTC)),
    ],
)
def test_whole_calendar_months(now: datetime, months: int, expected: datetime) -> None:
    assert months_before(now, months) == expected
