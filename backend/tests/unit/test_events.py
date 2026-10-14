"""In-process event bus (ARC-001 §4.1)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest

from pmp.core import Event, EventBus


@dataclass(frozen=True, kw_only=True)
class ScoreComputed(Event):
    model_id: int


@dataclass(frozen=True, kw_only=True)
class AlertChanged(Event):
    alert_id: int


def test_subscribers_receive_published_events_in_order() -> None:
    bus = EventBus()
    received: list[str] = []
    bus.subscribe(ScoreComputed, lambda e: received.append(f"first:{e.model_id}"))
    bus.subscribe(ScoreComputed, lambda e: received.append(f"second:{e.model_id}"))

    bus.publish(ScoreComputed(model_id=7))

    assert received == ["first:7", "second:7"]


def test_subscribers_only_receive_their_event_type() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(AlertChanged, received.append)

    bus.publish(ScoreComputed(model_id=1))

    assert received == []


def test_base_class_subscription_receives_every_event() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(Event, received.append)

    bus.publish(ScoreComputed(model_id=1))
    bus.publish(AlertChanged(alert_id=2))

    assert [type(e).__name__ for e in received] == ["ScoreComputed", "AlertChanged"]


def test_failing_handler_is_logged_and_does_not_stop_others(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = EventBus()
    received: list[int] = []

    def broken(_event: ScoreComputed) -> None:
        raise RuntimeError("boom")

    bus.subscribe(ScoreComputed, broken)
    bus.subscribe(ScoreComputed, lambda e: received.append(e.model_id))

    with caplog.at_level(logging.ERROR):
        bus.publish(ScoreComputed(model_id=3))

    assert received == [3]
    assert "broken" in caplog.text
    assert "ScoreComputed" in caplog.text


def test_events_carry_a_utc_timestamp() -> None:
    event = ScoreComputed(model_id=1)
    assert event.occurred_at.utcoffset() is not None
    assert event.occurred_at.utcoffset().total_seconds() == 0  # type: ignore[union-attr]
