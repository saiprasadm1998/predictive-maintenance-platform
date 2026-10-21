"""Cursor paging (ARC §7.3: lists are paginated with cursors)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pmp.api.common import decode_cursor, encode_cursor, page
from pmp.api.problems import ProblemError


@given(st.lists(st.integers(), unique=True), st.integers(1, 7))
def test_walking_the_pages_returns_every_item_once(items: list[int], limit: int) -> None:
    items = sorted(items)
    seen: list[int] = []
    cursor = None
    while True:
        chunk, cursor = page(items, lambda x: x, cursor, limit)
        seen += chunk
        if cursor is None:
            break
    assert seen == items


def test_cursors_round_trip_and_bad_ones_are_refused() -> None:
    assert decode_cursor(encode_cursor(["1.5.9", 3])) == ["1.5.9", 3]
    with pytest.raises(ProblemError):
        decode_cursor("not a cursor")
