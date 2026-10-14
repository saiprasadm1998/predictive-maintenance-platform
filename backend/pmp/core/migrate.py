"""Run Alembic migrations (ARC-001 §10.4, NFR-MAIN-02).

Migrations are forward-only. When several web processes start together, the
advisory lock makes them run one at a time; the later ones find nothing to do.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from pmp.core.db import LockKey, advisory_lock

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def alembic_config(database_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def run_migrations(database_url: str) -> None:
    """Upgrade the database to the latest migration, holding the migrations lock."""
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection, advisory_lock(connection, LockKey.MIGRATIONS):
            logger.info("Running database migrations")
            command.upgrade(alembic_config(database_url), "head")
            logger.info("Database migrations complete")
    finally:
        engine.dispose()
