"""Migration 0001 against a real PostgreSQL/TimescaleDB (ARC-001 §10.4, §12.1)."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from pmp.core import Database, run_migrations

pytestmark = pytest.mark.integration


def test_timescaledb_extension_is_installed(database: Database) -> None:
    with database.session() as session:
        installed = session.execute(
            text("SELECT count(*) FROM pg_extension WHERE extname = 'timescaledb'")
        ).scalar_one()
    assert installed == 1


def test_core_tables_exist(database: Database) -> None:
    tables = set(inspect(database.engine).get_table_names())
    assert {"job", "audit_log", "alembic_version"} <= tables


def test_database_is_at_the_latest_revision(database: Database) -> None:
    with database.session() as session:
        version = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0001"


def test_running_migrations_again_is_harmless(database_url: str) -> None:
    run_migrations(database_url)
