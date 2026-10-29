"""Database engine, sessions and advisory locks (ARC-001 §2.2, §5.1, §10.4)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from enum import IntEnum

from sqlalchemy import Connection, Engine, MetaData, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all ORM tables. Each table belongs to exactly one module."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class LockKey(IntEnum):
    """Application-wide PostgreSQL advisory lock keys."""

    MIGRATIONS = 7_410_001
    SCHEDULER = 7_410_002
    SCORE_CYCLE = 7_410_003  # with a model version ID: one writer per version and cycle
    NOTIFIER = 7_410_004  # one notifier leads (plan 8.5)


class Database:
    """Owns the connection pool and hands out transactional sessions."""

    def __init__(self, url: str) -> None:
        self.engine: Engine = create_engine(url, pool_pre_ping=True)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """A session in one transaction: committed on success, rolled back on error."""
        with self._sessions.begin() as session:
            yield session

    def dispose(self) -> None:
        self.engine.dispose()


@contextmanager
def advisory_lock(connection: Connection, key: LockKey) -> Iterator[None]:
    """Hold a session-level advisory lock, waiting until it is free."""
    connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": int(key)})
    connection.commit()
    try:
        yield
    finally:
        connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": int(key)})
        connection.commit()


def try_advisory_lock(connection: Connection, key: LockKey) -> bool:
    """Take a session-level advisory lock if it is free; never waits."""
    acquired = connection.execute(
        text("SELECT pg_try_advisory_lock(:key)"), {"key": int(key)}
    ).scalar_one()
    connection.commit()
    return bool(acquired)


def lock_for_transaction(session: Session, key: LockKey, item: int) -> None:
    """Take a transaction-level advisory lock on (key, item), waiting until it is free.
    PostgreSQL releases it at commit or rollback."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(:key, :item)"), {"key": int(key), "item": item}
    )


def holds_advisory_lock(connection: Connection, key: LockKey) -> bool:
    """Whether this connection still holds the session-level lock `key` (False if the
    connection has dropped, which releases it)."""
    try:
        held = connection.execute(
            text(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                "AND pid = pg_backend_pid() AND granted "
                "AND ((classid::bigint << 32) | objid::bigint) = :key"
            ),
            {"key": int(key)},
        ).scalar_one()
        connection.commit()
    except Exception:
        return False
    return bool(held)
