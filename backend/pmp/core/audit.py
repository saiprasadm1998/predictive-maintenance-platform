"""Append-only audit trail (FR-AUD-01, ARC-001 §6.2 `audit_log`, §9.3 FR 6).

`record_audit` must be called in the same transaction as the change it describes, so a
change and its audit entry are committed together or not at all. The table rejects
UPDATE, DELETE and TRUNCATE through a database trigger (migration 0001).
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Index, String, func, select
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from pmp.core.access import Permission, Principal, authorize
from pmp.core.db import Base


class ActorType(StrEnum):
    USER = "user"
    API_KEY = "api_key"
    SYSTEM = "system"


@dataclass(frozen=True)
class Actor:
    """Who is making a change: passed to every service call that writes. A user actor
    carries the Principal its permissions are checked against (5.1)."""

    actor_type: ActorType
    user_id: int | None = None
    ip: str | None = None
    principal: Principal | None = field(default=None, compare=False, repr=False)

    @classmethod
    def user(cls, principal: Principal, ip: str | None = None) -> Actor:
        return cls(ActorType.USER, principal.user_id, ip, principal)

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


# ------------------------------------------------------------------ review (UC-19)


@dataclass(frozen=True)
class AuditView:
    id: int
    ts: datetime
    user_id: int | None
    actor_type: str
    entity: str
    entity_id: str
    action: str
    before: Mapping[str, Any] | None
    after: Mapping[str, Any] | None
    ip: str | None


@dataclass(frozen=True)
class AuditFilter:
    """UC-19: by period, user, entity type and entity."""

    since: datetime | None = None
    until: datetime | None = None
    user_id: int | None = None
    entity: str | None = None
    entity_id: str | None = None


def query_audit(
    session: Session,
    actor: Actor,
    filters: AuditFilter = AuditFilter(),  # noqa: B008  (frozen)
    *,
    before_id: int | None = None,
    limit: int = 100,
) -> list[AuditView]:
    """Audit entries, newest first, `limit` at a time; pass the last ID as `before_id` for
    the next page. Only administrators review the audit log (ARC §9.2)."""
    authorize(actor, Permission.AUDIT_LOG, what="the audit log")
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(max(1, min(limit, 10_000)))
    if filters.since is not None:
        query = query.where(AuditLog.ts >= filters.since)
    if filters.until is not None:
        query = query.where(AuditLog.ts < filters.until)
    if filters.user_id is not None:
        query = query.where(AuditLog.user_id == filters.user_id)
    if filters.entity:
        query = query.where(AuditLog.entity == filters.entity)
    if filters.entity_id:
        query = query.where(AuditLog.entity_id == filters.entity_id)
    if before_id is not None:
        query = query.where(AuditLog.id < before_id)
    return [
        AuditView(
            id=r.id,
            ts=r.ts,
            user_id=r.user_id,
            actor_type=r.actor_type,
            entity=r.entity,
            entity_id=r.entity_id,
            action=r.action,
            before=(r.before_after or {}).get("before"),
            after=(r.before_after or {}).get("after"),
            ip=str(r.ip) if r.ip is not None else None,
        )
        for r in session.scalars(query).all()
    ]


CSV_COLUMNS = (
    "id",
    "ts",
    "user_id",
    "actor_type",
    "entity",
    "entity_id",
    "action",
    "before",
    "after",
    "ip",
)


def audit_csv(rows: Iterable[AuditView]) -> str:
    """UC-19: export as CSV (before and after values as JSON)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for r in rows:
        writer.writerow(
            [
                r.id,
                r.ts.isoformat(),
                r.user_id if r.user_id is not None else "",
                r.actor_type,
                r.entity,
                r.entity_id,
                r.action,
                json.dumps(r.before, sort_keys=True, default=str) if r.before is not None else "",
                json.dumps(r.after, sort_keys=True, default=str) if r.after is not None else "",
                r.ip or "",
            ]
        )
    return out.getvalue()
