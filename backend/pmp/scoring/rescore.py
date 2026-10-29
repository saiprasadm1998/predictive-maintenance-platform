"""Re-scoring a past period (FR-RUN-05, UCS §6.2, plan 8.7).

A re-score replaces one version's scores and sensor outputs for a period with ones
computed again from the stored samples, the version's model and its current DI limits.
It runs as a background job, an hour of cycles per transaction, under the same lock as
the live cycle, so a live cycle of the same version waits at most for one hour of work.

A re-score changes no alert, sends no notification and leaves the live runtime status
alone: the alert rules are not evaluated, so a re-scored band follows the DI limits only.
The version's latest live cycle and everything after it are never replaced, so the
current band and Health stay those of the live cycle (decision 8.7).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from pmp.core import (
    Actor,
    Database,
    LockKey,
    Permission,
    audit_change,
    authorize,
    enqueue,
    lock_for_transaction,
    refresh_hourly,
    report_progress,
)
from pmp.dataquality import read_sensors
from pmp.modelling import LoadedModel, ModelCache, ModelError, asset_path, model_of_version
from pmp.scoring.models import RuntimeStatusRow, ScoreRow, SensorOutputRow
from pmp.scoring.runtime import CycleResult, evaluate, limits_for, references_for, write_result

logger = logging.getLogger(__name__)

RESCORE_JOB = "scoring.rescore"
MAX_RESCORE_DAYS = 366
CHUNK = timedelta(hours=1)


class RescoreError(Exception):
    """A re-score that cannot be queued or run (the message says why)."""


@dataclass(frozen=True)
class RescoreRequest:
    version_id: int
    start: datetime
    end: datetime  # exclusive

    def to_payload(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> RescoreRequest:
        return cls(
            int(payload["version_id"]),
            datetime.fromisoformat(str(payload["start"])),
            datetime.fromisoformat(str(payload["end"])),
        )

    def check(self, now: datetime) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise RescoreError("Start and end need a time zone")
        if self.start >= self.end:
            raise RescoreError("The period must end after it starts")
        if self.end > now:
            raise RescoreError("The period cannot end in the future")
        if self.end - self.start > timedelta(days=MAX_RESCORE_DAYS):
            raise RescoreError(f"At most {MAX_RESCORE_DAYS} days can be re-scored at once")


@dataclass(frozen=True)
class RescoreResult:
    version_id: int
    start: datetime
    end: datetime  # the end actually used: never past the latest live cycle
    cycles: int
    replaced: int  # score rows removed before the period was scored again

    def as_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "cycles": self.cycles,
            "replaced": self.replaced,
        }


def queue_rescore(session: Session, actor: Actor, request: RescoreRequest, now: datetime) -> int:
    """Check and queue a re-score in the caller's transaction; returns the job ID.

    Model engineers and administrators, for models of assets they may see."""
    authorize(actor, Permission.MODELS, None, what="model re-scores")
    try:
        model = model_of_version(session, request.version_id)
    except ModelError:
        raise RescoreError(f"Model version {request.version_id} does not exist") from None
    authorize(actor, Permission.MODELS, asset_path(session, model.asset_code), what="this model")
    request.check(now)
    try:
        ModelCache().get(session, request.version_id)
    except ModelError as error:
        raise RescoreError(f"This version cannot be scored: {error}") from None
    job_id = enqueue(session, RESCORE_JOB, request.to_payload(), max_attempts=3)
    audit_change(
        session,
        actor,
        entity="model_version",
        entity_id=request.version_id,
        action="rescore",
        after={**request.to_payload(), "job_id": job_id},
    )
    return job_id


def _cycles(start: datetime, end: datetime, cycle_s: int) -> list[datetime]:
    """Cycle times in [start, end) on whole multiples of cycle_s, as the live cycle."""
    step = max(cycle_s, 1)
    first = -(-int(start.timestamp()) // step) * step
    stop = end.timestamp()
    out = []
    at = first
    while at < stop:
        out.append(datetime.fromtimestamp(at, UTC))
        at += step
    return out


def _live_end(session: Session, model: LoadedModel, end: datetime) -> datetime:
    row = session.get(RuntimeStatusRow, model.model_id)
    if row is None or row.version_id != model.version_id or row.last_cycle is None:
        return end
    return min(end, row.last_cycle)


def rescore_period(
    database: Database,
    request: RescoreRequest,
    *,
    progress: Callable[..., None] = report_progress,
) -> RescoreResult:
    """Replace the version's outputs in [start, end) (see the module docstring)."""
    with database.session() as session:
        try:
            model = ModelCache().get(session, request.version_id)
        except ModelError as error:
            raise RescoreError(f"This version cannot be scored: {error}") from None
        limits = limits_for(session, model)
        end = _live_end(session, model, request.end)
    references = references_for([model])
    tag_ids = {*model.tag_ids.values(), *model.filter_tag_ids.values()}
    cycles = _cycles(request.start, end, model.cycle_s)
    replaced = done = 0
    chunk_start = request.start
    while chunk_start < end:
        chunk_end = min(chunk_start + CHUNK, end)
        with database.session() as session:
            lock_for_transaction(session, LockKey.SCORE_CYCLE, model.version_id)
            replaced += _delete(session, model.version_id, chunk_start, chunk_end)
            for cycle in (c for c in cycles if chunk_start <= c < chunk_end):
                readings = read_sensors(session, cycle, tag_ids, references=references, store=False)
                status, reason, output = evaluate(model, readings, limits)
                result = CycleResult(
                    model.model_id, model.version_id, cycle, status, reason, output, False
                )
                write_result(session, model, result, readings, live=False)
                done += 1
        progress(100 * done / max(len(cycles), 1), cycles=done)
        chunk_start = chunk_end
    if end > request.start:
        for aggregate in ("score_1h", "sensor_output_1h"):
            refresh_hourly(database, aggregate, request.start, end)
    logger.info(
        "Re-scored version %s from %s to %s: %s cycles", model.version_id, request.start, end, done
    )
    return RescoreResult(model.version_id, request.start, end, done, replaced)


def _delete(session: Session, version_id: int, start: datetime, end: datetime) -> int:
    in_period = (ScoreRow.version_id == version_id) & (ScoreRow.ts >= start) & (ScoreRow.ts < end)
    session.execute(
        delete(SensorOutputRow).where(
            (SensorOutputRow.version_id == version_id)
            & (SensorOutputRow.ts >= start)
            & (SensorOutputRow.ts < end)
        )
    )
    removed = session.scalars(delete(ScoreRow).where(in_period).returning(ScoreRow.ts)).all()
    return len(removed)


def make_rescore_handler(
    database: Database,
) -> Callable[[Mapping[str, Any]], Mapping[str, Any]]:
    """The worker's handler for re-score jobs."""

    def handle(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return rescore_period(database, RescoreRequest.from_payload(payload)).as_dict()

    return handle
