"""Database-backed job queue (ARC-001 ADR-03, §6.2 `job` table, NFR-REL-01).

Jobs are claimed with SELECT ... FOR UPDATE SKIP LOCKED, so several workers never
take the same job. A job whose worker died is reclaimed once its lock is older than
the lock timeout. Failed jobs are retried with exponential back-off up to
`max_attempts`, then marked failed. Jobs live in the database, so they survive
process restarts.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from pmp.core.db import Base, Database

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_LOCK_TIMEOUT = timedelta(minutes=10)
BACKOFF_BASE = timedelta(seconds=30)
BACKOFF_MAX = timedelta(hours=1)


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (Index("ix_job_status_run_after", "status", "run_after"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=DEFAULT_MAX_ATTEMPTS)
    locked_by: Mapped[str | None] = mapped_column(String(200))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def enqueue(
    session: Session,
    job_type: str,
    payload: Mapping[str, Any] | None = None,
    *,
    delay: timedelta | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> int:
    """Add a job in the caller's transaction, so it is queued only if the caller commits."""
    job = Job(
        type=job_type,
        payload=dict(payload or {}),
        status=JobStatus.QUEUED,
        attempts=0,
        max_attempts=max_attempts,
    )
    if delay is not None:
        job.run_after = func.now() + delay
    session.add(job)
    session.flush()
    return job.id


_CLAIM_SQL = text(
    """
    UPDATE job
       SET status = 'running', locked_by = :worker, locked_at = now(),
           attempts = attempts + 1
     WHERE id = (
           SELECT id FROM job
            WHERE (status = 'queued' AND run_after <= now())
               OR (status = 'running' AND locked_at < now() - :lock_timeout
                   AND attempts < max_attempts)
            ORDER BY run_after, id
            FOR UPDATE SKIP LOCKED
            LIMIT 1)
    RETURNING id
    """
)


def claim(
    session: Session, worker: str, *, lock_timeout: timedelta = DEFAULT_LOCK_TIMEOUT
) -> Job | None:
    """Claim the next due job (or a job whose lock expired), or None if there is none."""
    job_id = session.execute(
        _CLAIM_SQL, {"worker": worker, "lock_timeout": lock_timeout}
    ).scalar_one_or_none()
    if job_id is None:
        return None
    return session.get(Job, job_id, populate_existing=True)


def complete(session: Session, job_id: int, result: Mapping[str, Any] | None = None) -> None:
    job = session.get_one(Job, job_id, with_for_update=True)
    job.status = JobStatus.SUCCEEDED
    job.result = dict(result) if result is not None else None
    job.locked_by = None
    job.locked_at = None
    job.finished_at = func.now()


def backoff(attempts: int) -> timedelta:
    """Delay before the next attempt: 30 s, 60 s, 120 s, ... capped at 1 h."""
    doublings = min(max(attempts - 1, 0), 20)
    delay: timedelta = BACKOFF_BASE * (1 << doublings)
    return min(delay, BACKOFF_MAX)


def fail(session: Session, job_id: int, error: str, *, retry: bool = True) -> JobStatus:
    """Record a failure. Retries with back-off until attempts run out, then fails."""
    job = session.get_one(Job, job_id, with_for_update=True)
    job.last_error = error
    job.locked_by = None
    job.locked_at = None
    if retry and job.attempts < job.max_attempts:
        job.status = JobStatus.QUEUED
        job.run_after = func.now() + backoff(job.attempts)
    else:
        job.status = JobStatus.FAILED
        job.finished_at = func.now()
    return JobStatus(job.status)


def fail_expired(session: Session, *, lock_timeout: timedelta = DEFAULT_LOCK_TIMEOUT) -> int:
    """Mark running jobs with expired locks and no attempts left as failed."""
    rows = session.execute(
        text(
            """
            UPDATE job
               SET status = 'failed', locked_by = NULL, locked_at = NULL,
                   finished_at = now(),
                   last_error = coalesce(last_error, 'worker lost: lock expired')
             WHERE status = 'running' AND locked_at < now() - :lock_timeout
               AND attempts >= max_attempts
            """
        ),
        {"lock_timeout": lock_timeout},
    )
    return int(rows.rowcount)  # type: ignore[attr-defined]


def queue_depth(session: Session) -> int:
    return (
        session.scalar(select(func.count()).select_from(Job).where(Job.status == JobStatus.QUEUED))
        or 0
    )


JobHandler = Callable[[Mapping[str, Any]], Mapping[str, Any] | None]


class JobRegistry:
    """Maps job types to handler functions. Modules register their handlers at start-up."""

    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str, handler: JobHandler) -> None:
        if job_type in self._handlers:
            raise ValueError(f"A handler for job type {job_type!r} is already registered")
        self._handlers[job_type] = handler

    def get(self, job_type: str) -> JobHandler | None:
        return self._handlers.get(job_type)


def default_worker_name() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


class Worker:
    """Claims and runs jobs one at a time.

    The claim, the work and the outcome are separate transactions: the claim is
    committed before the handler runs, so a crash mid-job leaves the job running with
    a lock that expires and is reclaimed.
    """

    def __init__(
        self,
        database: Database,
        registry: JobRegistry,
        *,
        name: str | None = None,
        poll_interval: float = 1.0,
        lock_timeout: timedelta = DEFAULT_LOCK_TIMEOUT,
    ) -> None:
        self.database = database
        self.registry = registry
        self.name = name or default_worker_name()
        self.poll_interval = poll_interval
        self.lock_timeout = lock_timeout

    def run_once(self) -> bool:
        """Run one job if one is due. Returns True if a job was processed."""
        with self.database.session() as session:
            job = claim(session, self.name, lock_timeout=self.lock_timeout)
            if job is None:
                return False
            job_id, job_type, payload = job.id, job.type, dict(job.payload)

        handler = self.registry.get(job_type)
        if handler is None:
            with self.database.session() as session:
                fail(
                    session, job_id, f"No handler registered for job type {job_type!r}", retry=False
                )
            logger.error("Job %s failed: no handler for type %s", job_id, job_type)
            return True

        try:
            result = handler(payload)
        except Exception as exc:
            with self.database.session() as session:
                status = fail(session, job_id, f"{type(exc).__name__}: {exc}")
            logger.exception("Job %s (%s) raised; now %s", job_id, job_type, status)
            return True

        with self.database.session() as session:
            complete(session, job_id, result)
        logger.info("Job %s (%s) succeeded", job_id, job_type)
        return True

    def run_forever(self, stop: threading.Event) -> None:
        logger.info("Worker %s started", self.name)
        while not stop.is_set():
            with self.database.session() as session:
                fail_expired(session, lock_timeout=self.lock_timeout)
            if not self.run_once():
                stop.wait(self.poll_interval)
        logger.info("Worker %s stopped", self.name)
