"""The scoring scheduler (FR-RUN-01, ARC §5.1): one leader, cycles on the wall clock.

Only one worker schedules at a time: the leader holds the SCHEDULER advisory lock on its
own connection, and if it dies PostgreSQL releases the lock so another worker takes over.

Each model's cycle times are whole multiples of its cycle (default 60 s, minimum 10 s).
Cycle T is scored once T + grace (default 20 s) has passed, so late gateway samples are
still included. Only the latest due cycle is scored: cycles missed while no scheduler was
running are not back-filled (ARC §5.1); re-scoring history is a separate job (8.7).
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pmp.alerting import expire_shelves, sync_out_of_service
from pmp.core import (
    Database,
    EventBus,
    LockKey,
    apply_retention,
    holds_advisory_lock,
    retention_due,
    try_advisory_lock,
)
from pmp.modelling import ActiveVersion, ModelCache, list_active_versions
from pmp.scoring.runtime import CycleResult, last_cycles, mark_out_of_service, score_models

logger = logging.getLogger(__name__)
MIN_CYCLE_S = 10


def latest_due_cycle(now: datetime, cycle_s: int, grace_s: int) -> datetime:
    """The newest cycle time T with T + grace <= now."""
    cycle_s = max(MIN_CYCLE_S, cycle_s)
    seconds = int((now - timedelta(seconds=grace_s)).timestamp()) // cycle_s * cycle_s
    return datetime.fromtimestamp(seconds, tz=UTC)


class Scheduler:
    def __init__(
        self,
        database: Database,
        *,
        grace_s: int = 20,
        bus: EventBus | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        poll_s: float = 1.0,
        retention_months: int | None = None,
    ) -> None:
        """`retention_months`: apply data retention once a day (the worker passes
        PMP_RETENTION_MONTHS as the default); None leaves retention off."""
        self.database = database
        self.retention_months = retention_months
        self.grace_s = grace_s
        self.bus = bus or EventBus()
        self.clock = clock
        self.poll_s = poll_s
        self.cache = ModelCache(self.bus)
        self._last: dict[int, datetime] | None = None

    def tick(self) -> list[CycleResult]:
        """Score every model whose latest due cycle has not been scored yet."""
        now = self.clock()
        with self.database.session() as session:
            active = list_active_versions(session)
            if self._last is None:
                self._last = last_cycles(session)
        last = self._last
        mark_out_of_service(self.database, (v.model_id for v in active))
        self._alert_housekeeping(now, active)
        self._retention(now)

        due: dict[datetime, list[ActiveVersion]] = defaultdict(list)
        for version in active:
            cycle = latest_due_cycle(now, version.cycle_s, self.grace_s)
            previous = last.get(version.version_id)
            if previous is None or cycle > previous:
                due[cycle].append(version)
        results: list[CycleResult] = []
        for cycle in sorted(due):
            batch = score_models(self.database, cycle, due[cycle], self.cache, bus=self.bus)
            for version in due[cycle]:
                last[version.version_id] = cycle
            results += batch
        return results

    def _retention(self, now: datetime) -> None:
        """NFR-DATA-01: the daily retention run, by the leader only."""
        if self.retention_months is None:
            return
        try:
            with self.database.session() as session:
                if retention_due(session, now):
                    apply_retention(session, now, self.retention_months)
        except Exception:
            logger.exception("Retention run failed; trying again on a later tick")

    def _alert_housekeeping(self, now: datetime, active: list[ActiveVersion]) -> None:
        """Shelving that has run out ends, and alerts follow their model in and out of
        service (paused or retired models; UC-10)."""
        deployed = [v.model_id for v in active if v.status.value == "Deployed"]
        with self.database.session() as session:
            changes = expire_shelves(session, now) + sync_out_of_service(session, deployed, now)
        for change in changes:
            self.bus.publish(change)

    def run_forever(self, stop: threading.Event) -> None:
        """Lead while holding the lock, ticking until stopped. If the lock connection
        drops, PostgreSQL releases the lock: this worker stops leading (checked before
        every tick) and waits to take it again, so two workers never lead at once.
        Closing the connection on the way out releases the lock for another worker."""
        while not stop.is_set():
            try:
                self._lead(stop)
            except Exception:
                logger.exception("Scheduler connection failed; trying to lead again")
                stop.wait(5.0)
        logger.info("Scoring scheduler stopped")

    def _lead(self, stop: threading.Event) -> None:
        with self.database.engine.connect() as connection:
            while not stop.is_set() and not try_advisory_lock(connection, LockKey.SCHEDULER):
                stop.wait(5.0)
            if stop.is_set():
                return
            logger.info("Scoring scheduler started as the leader")
            while not stop.is_set():
                if not holds_advisory_lock(connection, LockKey.SCHEDULER):
                    logger.warning("Scheduler lost its leader lock; stepping down")
                    self._last = None  # re-read the last cycles when leading again
                    return
                try:
                    self.tick()
                except Exception:
                    logger.exception("Scoring tick failed; trying again next tick")
                stop.wait(self.poll_s)
