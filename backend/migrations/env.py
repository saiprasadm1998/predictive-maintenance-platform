"""Alembic environment. Migrations are hand-written and forward-only (ARC-001 §10.4)."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from pmp.core import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    url = context.config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("sqlalchemy.url is not set; run migrations through `pmp migrate`")
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported")
run_migrations_online()
