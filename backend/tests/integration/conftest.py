"""Integration tests run against the development database (make db-up).

A fresh `pmp_test` database is created once per test run and migrated to head, so
tests exercise the real migrations, TimescaleDB extension and triggers.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from pmp.core import Database, run_migrations

ADMIN_URL = os.environ.get(
    "PMP_TEST_DATABASE_URL", "postgresql+psycopg://pmp:pmp@localhost:5433/pmp"
)
TEST_DB = "pmp_test"


@pytest.fixture(scope="session")
def database_url() -> str:
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
            connection.execute(text(f"CREATE DATABASE {TEST_DB}"))
    except OperationalError as error:
        pytest.fail(
            f"Cannot reach the development database at {make_url(ADMIN_URL).render_as_string()}. "
            f"Start it with `make db-up`.\n{error}",
            pytrace=False,
        )
    finally:
        admin.dispose()

    url = make_url(ADMIN_URL).set(database=TEST_DB).render_as_string(hide_password=False)
    run_migrations(url)
    return url


@pytest.fixture(scope="session")
def database(database_url: str) -> Iterator[Database]:
    db = Database(database_url)
    yield db
    db.dispose()


@pytest.fixture
def clean_jobs(database: Database) -> Database:
    with database.session() as session:
        session.execute(text("TRUNCATE job RESTART IDENTITY"))
    return database


REGISTRY_TABLES = "tag_role_map, tag, asset, type_role, asset_type"


@pytest.fixture
def clean_registry(database: Database) -> Database:
    with database.session() as session:
        session.execute(text(f"TRUNCATE {REGISTRY_TABLES} RESTART IDENTITY CASCADE"))
    return database


INGESTION_TABLES = "unmapped_tag, ingest_source, api_key"


@pytest.fixture
def clean_ingestion(clean_registry: Database) -> Database:
    with clean_registry.session() as session:
        session.execute(text("TRUNCATE sample"))  # hypertable: truncated on its own
        session.execute(text(f"TRUNCATE {INGESTION_TABLES} RESTART IDENTITY"))
    return clean_registry


DQ_TABLES = "dq_rule, sensor_status, sensor_exclusion"


@pytest.fixture
def clean_dq(clean_ingestion: Database) -> Database:
    with clean_ingestion.session() as session:
        session.execute(text(f"TRUNCATE {DQ_TABLES} RESTART IDENTITY"))
    return clean_ingestion


@pytest.fixture
def clean_models(clean_registry: Database) -> Database:
    """Models and alert rules (also emptied with the registry, through CASCADE)."""
    with clean_registry.session() as session:
        session.execute(text("TRUNCATE model RESTART IDENTITY CASCADE"))
    return clean_registry
