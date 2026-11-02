"""Operational alerts and metrics (plan 9.1, ARC §10.3)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from pmp.api.ops import metrics_text, operational_alerts
from pmp.core import SCORING_STATE, Database, enqueue, record_state
from pmp.ingestion import server_now
from tests.integration.test_alerts import _run, _scheduler
from tests.integration.test_scoring_cycle import (  # noqa: F401  (deployed is a fixture)
    LIVE,
    deployed,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def ops(deployed: Database) -> Database:  # noqa: F811
    with deployed.session() as s:
        s.execute(text("TRUNCATE ops_state, backup_run, ingest_source"))
        s.execute(text("TRUNCATE job RESTART IDENTITY"))
    return deployed


def _kinds(db: Database, now_shift: timedelta = timedelta(0)) -> dict[str, str]:
    with db.session() as s:
        now = server_now(s) + now_shift
        return {a.kind: a.text for a in operational_alerts(s, now)}


def test_the_scheduler_records_its_duration_and_overruns_show(ops: Database) -> None:
    _run(_scheduler(ops), 1)
    with ops.session() as s:
        recorded = s.execute(text("SELECT data FROM ops_state WHERE name = 'scoring'")).scalar_one()
    assert recorded["cycle_s"] == 60
    assert recorded["models"] == 1
    with ops.session() as s:  # on the test clock, just after that cycle: all quiet
        assert operational_alerts(s, LIVE + timedelta(minutes=2)) == []

    with ops.session() as s:
        now = server_now(s)
        record_state(s, SCORING_STATE, {"duration_s": 45.2, "cycle_s": 60, "models": 1}, now)
    assert _kinds(ops) == {
        "cycle_overrun": "The last scoring cycle took 45 s, over half of the 60 s cycle."
    }
    assert _kinds(ops, timedelta(minutes=11)) == {
        "scheduler_silent": "No scoring cycle for 11 min: is the worker running?"
    }


def test_a_job_waiting_over_10_minutes_and_a_failed_backup_show(ops: Database) -> None:
    with ops.session() as s:
        enqueue(s, "scoring.rescore", {})
        now = server_now(s)
    assert _kinds(ops, timedelta(minutes=9)) == {}
    assert _kinds(ops, timedelta(minutes=11)) == {
        "job_queue": "1 job waiting, the oldest for 11 min: is the worker running?"
    }
    with ops.session() as s:
        s.execute(text("TRUNCATE job"))
        s.execute(
            text(
                "INSERT INTO backup_run (started_at, finished_at, status, name, removed) "
                "VALUES (:t, :t, 'succeeded', 'pmp-a', 0)"
            ),
            {"t": now - timedelta(hours=30)},
        )
    assert _kinds(ops) == {
        "backup_failed": "No successful backup for 30 h: is the backup service running?"
    }
    with ops.session() as s:
        s.execute(
            text(
                "INSERT INTO backup_run (started_at, status, name, removed, error) "
                "VALUES (:t, 'failed', 'pmp-b', 0, 'pg_dump failed: disk full')"
            ),
            {"t": now - timedelta(hours=2)},
        )
    (failed,) = _kinds(ops).values()
    assert failed.endswith("failed: pg_dump failed: disk full")


def test_metrics_in_the_prometheus_text_format(ops: Database) -> None:
    _run(_scheduler(ops), 1)
    with ops.session() as s:
        s.execute(
            text(
                "INSERT INTO ingest_source (source, last_received_at, last_sample_ts, "
                "accepted_total, rejected_total) VALUES ('gw \"1\"', now(), now(), 10, 2)"
            )
        )
        body = metrics_text(s, server_now(s), sse_clients=3)
    lines = body.splitlines()
    assert "# TYPE pmp_ingest_samples_accepted_total counter" in lines
    assert 'pmp_ingest_samples_accepted_total{source="gw \\"1\\""} 10' in lines
    assert 'pmp_ingest_samples_rejected_total{source="gw \\"1\\""} 2' in lines
    assert 'pmp_models{status="Running"} 1' in lines
    assert "pmp_jobs_queued 0" in lines
    assert "pmp_sse_clients 3" in lines
    assert "pmp_backup_last_failed 0" in lines
    assert any(line.startswith("pmp_scoring_cycle_duration_seconds ") for line in lines)
    assert body.endswith("\n")
