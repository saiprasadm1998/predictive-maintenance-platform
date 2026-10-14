"""Job queue logic that needs no database (ARC-001 ADR-03)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from pmp.core import JobRegistry
from pmp.core.jobs import backoff


@pytest.mark.parametrize(
    ("attempts", "expected"),
    [
        (1, timedelta(seconds=30)),
        (2, timedelta(seconds=60)),
        (3, timedelta(seconds=120)),
        (8, timedelta(seconds=3840)),
        (20, timedelta(hours=1)),
    ],
)
def test_backoff_doubles_and_is_capped_at_one_hour(attempts: int, expected: timedelta) -> None:
    assert backoff(attempts) == min(expected, timedelta(hours=1))


def test_registry_returns_registered_handlers() -> None:
    registry = JobRegistry()
    registry.register("train", lambda payload: {"ok": True})
    handler = registry.get("train")
    assert handler is not None
    assert handler({}) == {"ok": True}
    assert registry.get("unknown") is None


def test_registry_refuses_duplicate_job_types() -> None:
    registry = JobRegistry()
    registry.register("train", lambda payload: None)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("train", lambda payload: None)
