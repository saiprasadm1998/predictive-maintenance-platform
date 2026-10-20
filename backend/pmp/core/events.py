"""In-process domain event bus (ARC-001 §4.1).

Modules react to each other through events such as ScoreComputed or AlertChanged
instead of direct calls. Handlers run synchronously, in subscription order. A
failing handler is logged and does not stop the others. Events between the web and
worker roles travel over PostgreSQL LISTEN/NOTIFY (added in sub-phase 5.3).
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class Event:
    """Base class for domain events. Subclasses are frozen dataclasses."""

    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


E = TypeVar("E", bound=Event)


class EventBus:
    def __init__(self) -> None:
        self._handlers: defaultdict[type[Event], list[Callable[[Any], None]]] = defaultdict(list)

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        """Call `handler` for every published event of `event_type` or a subclass."""
        self._handlers[event_type].append(handler)

    def publish(self, event: Event) -> None:
        for event_type in type(event).__mro__:
            for handler in self._handlers.get(event_type, []):
                try:
                    handler(event)
                except Exception:
                    logger.exception(
                        "Event handler %s failed for %s",
                        getattr(handler, "__qualname__", repr(handler)),
                        type(event).__name__,
                    )


EVENT_CHANNEL = "pmp_events"  # LISTEN/NOTIFY channel from the worker role to the web role


def notify(session: Session, payload: dict[str, Any]) -> None:
    """Queue a NOTIFY in the caller's transaction: delivered only if it commits (5.3 relays
    these to browsers as server-sent events)."""
    session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": EVENT_CHANNEL, "payload": json.dumps(payload, default=str)},
    )
