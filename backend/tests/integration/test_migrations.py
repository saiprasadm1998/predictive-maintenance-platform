"""Migration 0001 against a real PostgreSQL/TimescaleDB (ARC-001 §10.4, §12.1)."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from pmp.core import Database, run_migrations

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("extension", ["timescaledb", "ltree"])
def test_extensions_are_installed(database: Database, extension: str) -> None:
    with database.session() as session:
        installed = session.execute(
            text("SELECT count(*) FROM pg_extension WHERE extname = :name"), {"name": extension}
        ).scalar_one()
    assert installed == 1


def test_core_tables_exist(database: Database) -> None:
    tables = set(inspect(database.engine).get_table_names())
    assert {"job", "audit_log", "alembic_version"} <= tables
    assert {"asset", "tag", "asset_type", "type_role", "tag_role_map"} <= tables
    assert {"api_key", "sample", "unmapped_tag", "ingest_source"} <= tables
    assert {"dq_rule", "sensor_status", "sensor_exclusion"} <= tables
    assert {"model", "model_version", "model_sensor", "training_period", "mode_filter"} <= tables
    assert "alert_rule" in tables
    assert {"score", "sensor_output", "runtime_status"} <= tables
    assert {"alert", "alert_event", "alert_rule_state", "priority_matrix"} <= tables


def test_database_is_at_the_latest_revision(database: Database) -> None:
    with database.session() as session:
        version = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0013"


def test_running_migrations_again_is_harmless(database_url: str) -> None:
    run_migrations(database_url)


def test_sample_is_a_hypertable_with_one_day_chunks(database: Database) -> None:
    with database.session() as session:
        interval = session.execute(
            text(
                "SELECT time_interval FROM timescaledb_information.dimensions "
                "WHERE hypertable_name = 'sample'"
            )
        ).scalar_one()
    assert str(interval) == "1 day, 0:00:00"
