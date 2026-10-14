"""Append-only audit trail (FR-AUD-01, ARC-001 §6.2)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from pmp.core import ActorType, AuditLog, Database, record_audit

pytestmark = pytest.mark.integration


def _entity_id() -> str:
    return uuid.uuid4().hex


def test_audit_entry_records_who_what_when_and_values(database: Database) -> None:
    entity_id = _entity_id()
    with database.session() as session:
        record_audit(
            session,
            actor_type=ActorType.USER,
            user_id=42,
            entity="tag",
            entity_id=entity_id,
            action="update",
            before={"unit": "degC"},
            after={"unit": "°C"},
            ip="10.0.0.5",
        )

    with database.session() as session:
        entry = session.scalars(select(AuditLog).where(AuditLog.entity_id == entity_id)).one()
        assert entry.user_id == 42
        assert entry.actor_type == "user"
        assert entry.action == "update"
        assert entry.before_after == {"before": {"unit": "degC"}, "after": {"unit": "°C"}}
        assert str(entry.ip) == "10.0.0.5"
        assert entry.ts is not None


def test_audit_entry_is_rolled_back_with_the_change(database: Database) -> None:
    entity_id = _entity_id()

    def failing_change() -> None:
        with database.session() as session:
            record_audit(
                session,
                actor_type=ActorType.SYSTEM,
                entity="model",
                entity_id=entity_id,
                action="deploy",
            )
            raise RuntimeError("the change failed")

    with pytest.raises(RuntimeError):
        failing_change()

    with database.session() as session:
        count = session.scalar(
            select(text("count(*)")).select_from(AuditLog).where(AuditLog.entity_id == entity_id)
        )
    assert count == 0


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET action = 'tampered'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
    ],
)
def test_audit_log_cannot_be_changed_or_deleted(database: Database, statement: str) -> None:
    with database.session() as session:
        record_audit(
            session,
            actor_type=ActorType.SYSTEM,
            entity="job",
            entity_id=_entity_id(),
            action="create",
        )

    with pytest.raises(DBAPIError, match="append-only"), database.session() as session:
        session.execute(text(statement))
