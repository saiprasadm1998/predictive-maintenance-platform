"""Append-only audit trail (FR-AUD-01, ARC-001 §6.2 `audit_log`, §9.3 FR 6).

`record_audit` must be called in the same transaction as the change it describes, so a
change and its audit entry are committed together or not at all. The table rejects
UPDATE, DELETE and TRUNCATE through a database trigger (migration 0001).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Index, String, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from pmp.core.db import Base


class ActorType(StrEnum):
    USER = "user"
    API_KEY = "api_key"
    SYSTEM = "system"


@dataclass(frozen=True)
class Actor:
    """Who is making a change: passed to every service call that writes."""

    actor_type: ActorType
    user_id: int | None = None
    ip: str | None = None

    @classmethod
    def system(cls) -> Actor:
        return cls(ActorType.SYSTEM)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_entity_entity_id", "entity", "entity_id"),
        Index("ix_audit_log_user_id", "user_id"),
        Index("ix_audit_log_ts", "ts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    actor_type: Mapped[str] = mapped_column(String(20))
    entity: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(100))
    before_after: Mapped[dict[str, Any]] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)


def record_audit(
    session: Session,
    *,
    actor_type: ActorType,
    entity: str,
    entity_id: str | int,
    action: str,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    user_id: int | None = None,
    ip: str | None = None,
) -> None:
    """Write one audit entry in the caller's transaction."""
    session.add(
        AuditLog(
            user_id=user_id,
            actor_type=actor_type,
            entity=entity,
            entity_id=str(entity_id),
            action=action,
            before_after={
                "before": dict(before) if before is not None else None,
                "after": dict(after) if after is not None else None,
            },
            ip=ip,
        )
    )


def audit_change(
    session: Session,
    actor: Actor,
    *,
    entity: str,
    entity_id: str | int,
    action: str,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
) -> None:
    """Shorthand for record_audit with the who-fields taken from an Actor."""
    record_audit(
        session,
        actor_type=actor.actor_type,
        user_id=actor.user_id,
        ip=actor.ip,
        entity=entity,
        entity_id=entity_id,
        action=action,
        before=before,
        after=after,
    )
