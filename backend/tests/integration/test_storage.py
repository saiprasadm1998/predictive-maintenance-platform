"""Time-series storage and retention (plan 5.4; ARC §6.3, NFR-DATA-01, FR-RUN-03).

The compression and continuous-aggregate checks need the real TimescaleDB extension (the
development database in Docker and CI); they are skipped on a plain PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from pmp.core import (
    AccessDeniedError,
    Actor,
    Database,
    Principal,
    RetentionError,
    Role,
    RoleAssignment,
    apply_retention,
    get_retention,
    set_retention,
)
from pmp.scoring import score_trend

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)


def _timescale(db: Database) -> bool:
    with db.session() as s:
        return bool(
            s.scalar(text("SELECT count(*) FROM pg_proc WHERE proname = 'add_compression_policy'"))
        )


@pytest.fixture
def db(database: Database) -> Database:
    with database.session() as s:
        s.execute(text("TRUNCATE sample, score, sensor_output"))
        s.execute(text("DELETE FROM retention_policy"))
    return database


def _scores(db: Database, start: datetime, hours: int, every: timedelta) -> None:
    with db.session() as s:
        s.execute(
            text(
                "INSERT INTO score (version_id, ts, model_id, status, band, di, health, coverage) "
                "SELECT 1, ts, 99, 'Running', 'Healthy', 10 + extract(hour FROM ts), 80, 1 "
                "FROM generate_series(:start, :start + :span, :every) ts"
            ),
            {"start": start, "span": timedelta(hours=hours), "every": every},
        )


def test_retention_removes_only_expired_data(db: Database) -> None:
    old, recent = NOW - timedelta(days=30 * 26), NOW - timedelta(days=1)
    with db.session() as s:
        for ts in (old, recent):
            s.execute(
                text("INSERT INTO sample (tag_id, ts, value, quality) VALUES (1, :ts, 1, 0)"),
                {"ts": ts},
            )
    _scores(db, old, 1, timedelta(minutes=1))
    _scores(db, recent, 1, timedelta(minutes=1))
    with db.session() as s:
        summary = apply_retention(s, NOW)
        policy = get_retention(s)
        samples = s.execute(text("SELECT ts FROM sample ORDER BY ts")).scalars().all()
        scores = s.execute(text("SELECT min(ts) FROM score")).scalar_one()
    assert samples == [recent]
    assert scores >= recent
    assert policy.raw_months == 24
    assert policy.last_run_at == NOW
    assert "raw before 2024-10-21" in summary


def test_only_administrators_change_retention(db: Database) -> None:
    analyst = Actor.user(Principal(7, "a", (RoleAssignment(Role.ANALYST),)))
    with db.session() as s, pytest.raises(AccessDeniedError):
        set_retention(s, analyst, raw_months=12, aggregate_months=60)
    with db.session() as s, pytest.raises(RetentionError):
        set_retention(s, Actor.system(), raw_months=24, aggregate_months=12)
    with db.session() as s:
        policy = set_retention(s, Actor.system(), raw_months=12, aggregate_months=36)
    assert (policy.raw_months, policy.aggregate_months) == (12, 36)


def test_long_trends_read_the_hourly_aggregates(db: Database) -> None:
    """ARC §6.3: aggregates for trends longer than 30 days; same min and max as raw."""
    start = NOW - timedelta(days=40)
    _scores(db, start, 40 * 24, timedelta(minutes=10))
    with db.session() as s:
        long = score_trend(s, 99, start, NOW, px=40)
        short = score_trend(s, 99, NOW - timedelta(days=10), NOW, px=10)
    assert long.source == "hourly"
    assert short.source == "raw"
    assert len(long.ts) == 40
    assert min(v for v in long.min["di"] if v is not None) == 10
    assert max(v for v in long.max["di"] if v is not None) == 33


def test_compression_chunks_and_aggregates_follow_arc_6_3(db: Database) -> None:
    if not _timescale(db):
        pytest.skip("needs the TimescaleDB extension")
    with db.session() as s:
        compressed: dict[str, bool] = dict(
            s.execute(
                text(
                    "SELECT hypertable_name, compression_enabled "
                    "FROM timescaledb_information.hypertables"
                )
            ).all()
        )
        policies = s.execute(
            text(
                "SELECT hypertable_name, proc_name FROM timescaledb_information.jobs "
                "WHERE proc_name IN ('policy_compression', 'policy_refresh_continuous_aggregate')"
            )
        ).all()
        score_chunk = s.scalar(
            text(
                "SELECT time_interval FROM timescaledb_information.dimensions "
                "WHERE hypertable_name = 'score'"
            )
        )
        aggregates = (
            s.execute(text("SELECT view_name FROM timescaledb_information.continuous_aggregates"))
            .scalars()
            .all()
        )
    for table in ("sample", "score", "sensor_output"):
        assert compressed[table] is True
    assert len([p for p in policies if p[1] == "policy_compression"]) == 3
    assert score_chunk == timedelta(days=7)
    assert set(aggregates) == {"sample_1h", "score_1h", "sensor_output_1h"}
