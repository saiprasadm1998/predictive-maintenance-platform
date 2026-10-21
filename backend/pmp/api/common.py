"""Shared API pieces (ARC §7.3): cursor pages, UTC times, scope filtering.

- Lists are paged with opaque cursors: pass `next_cursor` back as `cursor` for the next
  page. A cursor encodes the sort key of the last item, so pages stay stable while rows
  are added.
- Times are ISO 8601 with a time zone; a time without one is refused (400) rather than
  guessed.
- A user scoped to part of the hierarchy sees only that part: lists leave out what is
  outside, and a single item outside is "not found" (404), so its existence is not
  revealed.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from pmp.api.deps import SignedIn
from pmp.api.problems import ProblemError
from pmp.core import Permission

ItemT = TypeVar("ItemT")
MAX_LIMIT = 1000


class Page(BaseModel, Generic[ItemT]):  # noqa: UP046  (pydantic generic model)
    items: list[ItemT]
    next_cursor: str | None = Field(
        default=None, description="Pass as `cursor` for the next page; null on the last page"
    )


def encode_cursor(key: Any) -> str:
    return base64.urlsafe_b64encode(json.dumps(key, default=str).encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> Any:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (ValueError, json.JSONDecodeError):
        raise ProblemError(
            400, "invalid_cursor", "Invalid cursor", "Use next_cursor as given."
        ) from None


def page[T](
    items: Sequence[T], key: Callable[[T], Any], cursor: str | None, limit: int
) -> tuple[list[T], str | None]:
    """One page of `items` (already sorted by `key`) after `cursor`."""
    start = 0
    if cursor is not None:
        after = decode_cursor(cursor)
        start = next((i for i, item in enumerate(items) if _gt(key(item), after)), len(items))
    chunk = list(items[start : start + limit])
    more = start + limit < len(items)
    return chunk, (encode_cursor(key(chunk[-1])) if more and chunk else None)


def _gt(a: Any, b: Any) -> bool:
    return bool(json.loads(json.dumps(a, default=str)) > b)


def utc(value: datetime | None, name: str) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise ProblemError(
            400,
            "invalid_time",
            f"{name} needs a time zone",
            "Use ISO 8601, e.g. 2026-10-21T08:00Z.",
        )
    return value


def can_see(user: SignedIn, asset_path: str | None) -> bool:
    return user.session.principal.grant(Permission.VIEW, asset_path)


def not_found(what: str) -> ProblemError:
    return ProblemError(404, "not_found", f"{what} not found")
