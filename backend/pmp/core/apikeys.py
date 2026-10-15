"""Machine credentials for the OT gateway and other systems (FR-SEC-02, UC-17, ARC §9.3).

A key is shown once when issued; only its SHA-256 hash is stored. Keys are random
(256 bits), so a fast hash is enough, unlike passwords, which need Argon2id. Each key
has one scope: `ingest` (write samples) or `results-read` (read results). Keys can be
revoked, and rotated by issuing a replacement while the old key still works.

Key format: pmp_<prefix>_<secret>. The prefix is stored in clear to find the row.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Identity, Integer, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from pmp.core.audit import Actor, audit_change
from pmp.core.db import Base


class ApiKeyScope(StrEnum):
    INGEST = "ingest"
    RESULTS_READ = "results-read"


class ApiKeyError(Exception):
    """An API key operation was refused."""


class ApiKey(Base):
    __tablename__ = "api_key"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    prefix: Mapped[str] = mapped_column(String(16), unique=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    scope: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(Integer)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


@dataclass(frozen=True)
class IssuedKey:
    id: int
    key: str  # the full key: show it once, never store or log it
    prefix: str


@dataclass(frozen=True)
class ApiKeyView:
    id: int
    prefix: str
    name: str
    scope: ApiKeyScope
    created_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None

    @property
    def active(self) -> bool:
        return self.revoked_at is None


def _hash(secret_key: str) -> str:
    return hashlib.sha256(secret_key.encode()).hexdigest()


def generate_key() -> tuple[str, str]:
    """Return (full key, prefix)."""
    prefix = secrets.token_hex(6)  # 12 hex characters
    return f"pmp_{prefix}_{secrets.token_urlsafe(32)}", prefix


def parse_prefix(key: str) -> str | None:
    parts = key.split("_", 2)
    if len(parts) != 3 or parts[0] != "pmp" or len(parts[1]) != 12:
        return None
    return parts[1]


def _view(row: ApiKey) -> ApiKeyView:
    return ApiKeyView(
        id=row.id,
        prefix=row.prefix,
        name=row.name,
        scope=ApiKeyScope(row.scope),
        created_at=row.created_at,
        revoked_at=row.revoked_at,
        last_used_at=row.last_used_at,
    )


def issue_api_key(session: Session, actor: Actor, *, name: str, scope: ApiKeyScope) -> IssuedKey:
    name = name.strip()
    if not name:
        raise ApiKeyError("A key needs a name, e.g. 'Site A gateway'")
    key, prefix = generate_key()
    row = ApiKey(
        prefix=prefix, key_hash=_hash(key), name=name, scope=scope.value, created_by=actor.user_id
    )
    session.add(row)
    session.flush()
    audit_change(
        session,
        actor,
        entity="api_key",
        entity_id=row.id,
        action="issue",
        after={"name": name, "scope": scope.value, "prefix": prefix},
    )
    return IssuedKey(id=row.id, key=key, prefix=prefix)


def verify_api_key(session: Session, key: str) -> ApiKeyView | None:
    """The key's details if it is valid and not revoked; None otherwise."""
    prefix = parse_prefix(key)
    if prefix is None:
        return None
    row = session.scalars(select(ApiKey).where(ApiKey.prefix == prefix)).one_or_none()
    if row is None or not hmac.compare_digest(row.key_hash, _hash(key)):
        return None
    if row.revoked_at is not None:
        return None
    row.last_used_at = func.now()
    session.flush()
    session.refresh(row)
    return _view(row)


def revoke_api_key(session: Session, actor: Actor, key_id: int) -> None:
    row = session.get(ApiKey, key_id)
    if row is None:
        raise ApiKeyError(f"API key {key_id} does not exist")
    if row.revoked_at is not None:
        return
    row.revoked_at = func.now()
    session.flush()
    audit_change(
        session,
        actor,
        entity="api_key",
        entity_id=key_id,
        action="revoke",
        before={"active": True},
        after={"active": False},
    )


def rotate_api_key(session: Session, actor: Actor, key_id: int) -> IssuedKey:
    """Issue a replacement with the same name and scope. Revoke the old key once the
    system using it has switched over."""
    row = session.get(ApiKey, key_id)
    if row is None or row.revoked_at is not None:
        raise ApiKeyError(f"API key {key_id} does not exist or is revoked")
    issued = issue_api_key(session, actor, name=row.name, scope=ApiKeyScope(row.scope))
    audit_change(
        session,
        actor,
        entity="api_key",
        entity_id=key_id,
        action="rotate",
        after={"replacement_id": issued.id},
    )
    return issued


def list_api_keys(session: Session) -> list[ApiKeyView]:
    return [_view(r) for r in session.scalars(select(ApiKey).order_by(ApiKey.id)).all()]
