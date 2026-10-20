"""Job queue against PostgreSQL (ARC-001 ADR-03, NFR-REL-01)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from sqlalchemy import text

from pmp.core import (
    Database,
    Job,
    JobRegistry,
    JobStatus,
    Worker,
    claim,
    complete,
    enqueue,
    fail,
    fail_expired,
    heartbeat,
    queue_depth,
)

pytestmark = pytest.mark.integration


def _job(db: Database, job_id: int) -> Job:
    with db.session() as session:
        job = session.get_one(Job, job_id)
        session.expunge(job)
        return job


def test_enqueued_job_is_claimed_once(clean_jobs: Database) -> None:
    db = clean_jobs
    with db.session() as session:
        job_id = enqueue(session, "train", {"model_id": 1})

    with db.session() as session:
        job = claim(session, "worker-a")
        assert job is not None
        assert job.id == job_id
        assert job.status == JobStatus.RUNNING
        assert job.attempts == 1
        assert job.locked_by == "worker-a"
        assert job.payload == {"model_id": 1}

    with db.session() as session:
        assert claim(session, "worker-b") is None


def test_job_is_not_queued_if_the_caller_rolls_back(clean_jobs: Database) -> None:
    db = clean_jobs

    def failing_change() -> None:
        with db.session() as session:
            enqueue(session, "train")
            raise RuntimeError("caller failed")

    with pytest.raises(RuntimeError):
        failing_change()

    with db.session() as session:
        assert queue_depth(session) == 0


def test_delayed_job_is_not_claimed_early(clean_jobs: Database) -> None:
    from datetime import timedelta

    db = clean_jobs
    with db.session() as session:
        enqueue(session, "train", delay=timedelta(hours=1))
    with db.session() as session:
        assert claim(session, "worker-a") is None


def test_two_workers_never_claim_the_same_job(clean_jobs: Database) -> None:
    db = clean_jobs
    with db.session() as session:
        first = enqueue(session, "train")
        second = enqueue(session, "train")

    # Worker A holds its claim transaction open while worker B claims.
    with db.session() as session_a:
        job_a = claim(session_a, "worker-a")
        with db.session() as session_b:
            job_b = claim(session_b, "worker-b")
        assert job_a is not None
        assert job_b is not None
        assert {job_a.id, job_b.id} == {first, second}


def test_completed_job_stores_its_result(clean_jobs: Database) -> None:
    db = clean_jobs
    with db.session() as session:
        job_id = enqueue(session, "train")
    with db.session() as session:
        claim(session, "worker-a")
    with db.session() as session:
        complete(session, job_id, {"version_id": 3})

    job = _job(db, job_id)
    assert job.status == JobStatus.SUCCEEDED
    assert job.result == {"version_id": 3}
    assert job.locked_by is None
    assert job.finished_at is not None


def test_failed_job_is_retried_later_then_fails_for_good(clean_jobs: Database) -> None:
    db = clean_jobs
    with db.session() as session:
        job_id = enqueue(session, "train", max_attempts=2)

    with db.session() as session:
        claim(session, "worker-a")
    with db.session() as session:
        assert fail(session, job_id, "first error") == JobStatus.QUEUED
    job = _job(db, job_id)
    assert job.run_after > job.created_at  # back-off pushed it into the future
    assert job.last_error == "first error"

    with db.session() as session:  # make it due now and fail again
        session.execute(text("UPDATE job SET run_after = now() WHERE id = :id"), {"id": job_id})
    with db.session() as session:
        claim(session, "worker-a")
    with db.session() as session:
        assert fail(session, job_id, "second error") == JobStatus.FAILED
    assert _job(db, job_id).attempts == 2


def test_expired_lock_is_reclaimed_by_another_worker(clean_jobs: Database) -> None:
    db = clean_jobs
    with db.session() as session:
        job_id = enqueue(session, "train")
    with db.session() as session:
        claim(session, "worker-a")

    # Worker A dies; its lock ages past the timeout.
    with db.session() as session:
        session.execute(
            text("UPDATE job SET locked_at = now() - interval '1 hour' WHERE id = :id"),
            {"id": job_id},
        )

    with db.session() as session:
        job = claim(session, "worker-b")
        assert job is not None
        assert job.id == job_id
        assert job.locked_by == "worker-b"
        assert job.attempts == 2


def test_expired_job_with_no_attempts_left_is_failed(clean_jobs: Database) -> None:
    db = clean_jobs
    with db.session() as session:
        job_id = enqueue(session, "train", max_attempts=1)
    with db.session() as session:
        claim(session, "worker-a")
    with db.session() as session:
        session.execute(
            text("UPDATE job SET locked_at = now() - interval '1 hour' WHERE id = :id"),
            {"id": job_id},
        )

    with db.session() as session:
        assert claim(session, "worker-b") is None
        assert len(fail_expired(session)) == 1
    assert _job(db, job_id).status == JobStatus.FAILED


def test_jobs_survive_a_process_restart(clean_jobs: Database, database_url: str) -> None:
    with clean_jobs.session() as session:
        job_id = enqueue(session, "train")

    restarted = Database(database_url)  # a new process: new engine, new connections
    try:
        with restarted.session() as session:
            job = claim(session, "worker-after-restart")
            assert job is not None
            assert job.id == job_id
    finally:
        restarted.dispose()


def test_worker_runs_handlers_and_records_outcomes(clean_jobs: Database) -> None:
    db = clean_jobs
    registry = JobRegistry()

    def succeed(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"doubled": payload["n"] * 2}

    def explode(_payload: Mapping[str, Any]) -> None:
        raise ValueError("bad input")

    registry.register("double", succeed)
    registry.register("explode", explode)

    with db.session() as session:
        ok_id = enqueue(session, "double", {"n": 21})
        bad_id = enqueue(session, "explode")
        unknown_id = enqueue(session, "no-such-type")

    worker = Worker(db, registry, name="worker-test")
    assert worker.run_once()
    assert worker.run_once()
    assert worker.run_once()
    assert not worker.run_once()

    assert _job(db, ok_id).result == {"doubled": 42}
    bad = _job(db, bad_id)
    assert bad.status == JobStatus.QUEUED  # will be retried after back-off
    assert bad.last_error == "ValueError: bad input"
    unknown = _job(db, unknown_id)
    assert unknown.status == JobStatus.FAILED
    assert "No handler" in (unknown.last_error or "")


def test_heartbeat_keeps_a_long_job_from_being_reclaimed(clean_jobs: Database) -> None:
    """A job that runs past the lock timeout keeps its lock while it is alive (4.4)."""
    db = clean_jobs
    with db.session() as session:
        job_id = enqueue(session, "train")
        claim(session, "worker-a")
        session.execute(
            text("UPDATE job SET locked_at = now() - interval '9 minutes' WHERE id = :id"),
            {"id": job_id},
        )
    with db.session() as session:
        assert heartbeat(session, job_id, "worker-a")
        assert not heartbeat(session, job_id, "worker-b")  # only the holder renews
    with db.session() as session:
        session.execute(text("SELECT 1"))
        assert claim(session, "worker-b") is None


def test_a_late_outcome_from_a_worker_that_lost_the_job_is_ignored(clean_jobs: Database) -> None:
    db = clean_jobs
    with db.session() as session:
        job_id = enqueue(session, "train")
        claim(session, "worker-a")
        session.execute(
            text("UPDATE job SET locked_at = now() - interval '1 hour' WHERE id = :id"),
            {"id": job_id},
        )
    with db.session() as session:
        assert claim(session, "worker-b") is not None
    with db.session() as session:
        complete(session, job_id, {"by": "a"}, worker="worker-a")  # too late: ignored
    assert _job(db, job_id).status == JobStatus.RUNNING
    with db.session() as session:
        complete(session, job_id, {"by": "b"}, worker="worker-b")
    job = _job(db, job_id)
    assert (job.status, job.result) == (JobStatus.SUCCEEDED, {"by": "b"})


def test_a_job_lost_for_good_tells_its_module(clean_jobs: Database) -> None:
    db = clean_jobs
    seen: list[tuple[Mapping[str, Any], str]] = []
    registry = JobRegistry()
    registry.register("train", lambda payload: None, on_failed=lambda p, e: seen.append((p, e)))
    with db.session() as session:
        job_id = enqueue(session, "train", {"version_id": 7}, max_attempts=1)
        claim(session, "worker-a")
        session.execute(
            text("UPDATE job SET locked_at = now() - interval '1 hour' WHERE id = :id"),
            {"id": job_id},
        )
    Worker(db, registry, name="w").expire_locks()
    assert seen == [({"version_id": 7}, "worker lost: lock expired")]


def test_a_handler_failing_for_good_tells_its_module(clean_jobs: Database) -> None:
    db = clean_jobs
    seen: list[str] = []

    def broken(payload: Mapping[str, Any]) -> None:
        raise RuntimeError("boom")

    registry = JobRegistry()
    registry.register("train", broken, on_failed=lambda p, e: seen.append(e))
    with db.session() as session:
        enqueue(session, "train", max_attempts=1)
    assert Worker(db, registry, name="w").run_once()
    assert seen == ["RuntimeError: boom"]
