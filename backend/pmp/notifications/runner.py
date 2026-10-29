"""The notifier: a worker thread that collects events and delivers e-mail (plan 8.5).

One worker leads at a time (an advisory lock, like the scoring scheduler). Every pass
collects new alert and case events into the delivery log, writes the hourly summaries and
sends what is due, each in its own transaction, so a P1 alert is e-mailed within one pass
of being raised (FR-NOT-01: within 2 minutes).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from pmp.core import Database, LockKey, holds_advisory_lock, try_advisory_lock
from pmp.notifications.service import (
    Sender,
    collect_alerts,
    collect_cases,
    collect_overdue,
    collect_stale_sources,
    deliver,
    summarise,
)

logger = logging.getLogger(__name__)
INTERVAL_S = 15.0


@dataclass
class PassResult:
    queued: int = 0
    summaries: int = 0
    sent: int = 0
    failed: int = 0


class Notifier:
    def __init__(
        self,
        database: Database,
        sender: Sender,
        public_url: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        interval_s: float = INTERVAL_S,
    ) -> None:
        self.database = database
        self.sender = sender
        self.public_url = public_url
        self.clock = clock
        self.interval_s = interval_s

    def run_once(self) -> PassResult:
        now = self.clock()
        result = PassResult()
        with self.database.session() as session:
            result.queued += collect_alerts(session, now, self.public_url)
        with self.database.session() as session:
            result.queued += collect_cases(session, now, self.public_url)
        with self.database.session() as session:
            result.queued += collect_overdue(session, now, self.public_url, now.date())
        with self.database.session() as session:
            result.queued += collect_stale_sources(session, now, self.public_url)
        with self.database.session() as session:
            result.summaries = summarise(session, now, self.public_url)
        with self.database.session() as session:
            result.sent, result.failed = deliver(session, self.sender, now)
        return result

    def run_forever(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self._lead(stop)
            except Exception:
                logger.exception("Notifier connection failed; trying to lead again")
                stop.wait(5.0)
        logger.info("Notifier stopped")

    def _lead(self, stop: threading.Event) -> None:
        with self.database.engine.connect() as connection:
            while not stop.is_set() and not try_advisory_lock(connection, LockKey.NOTIFIER):
                stop.wait(self.interval_s)
            if stop.is_set():
                return
            logger.info("Notifier started as the leader")
            while not stop.is_set():
                if not holds_advisory_lock(connection, LockKey.NOTIFIER):
                    logger.warning("Notifier lost its lock; stepping down")
                    return
                try:
                    result = self.run_once()
                    if result.sent or result.failed:
                        logger.info("Notifications: %s sent, %s failed", result.sent, result.failed)
                except Exception:
                    logger.exception("Notification pass failed")
                stop.wait(self.interval_s)
