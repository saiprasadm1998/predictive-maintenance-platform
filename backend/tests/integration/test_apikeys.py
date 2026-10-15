"""Machine API keys (FR-SEC-02, UC-17): shown once, hashed, scoped, revocable, rotatable."""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from pmp.core import (
    Actor,
    ApiKeyScope,
    AuditLog,
    Database,
    issue_api_key,
    list_api_keys,
    revoke_api_key,
    rotate_api_key,
    verify_api_key,
)

pytestmark = pytest.mark.integration
ACTOR = Actor.system()


def test_only_the_hash_is_stored(clean_ingestion: Database) -> None:
    with clean_ingestion.session() as s:
        issued = issue_api_key(s, ACTOR, name="Site A gateway", scope=ApiKeyScope.INGEST)
    with clean_ingestion.session() as s:
        stored = s.execute(text("SELECT prefix, key_hash FROM api_key")).one()
    assert stored.prefix == issued.prefix
    assert issued.key not in stored.key_hash
    assert len(stored.key_hash) == 64


def test_verify_accepts_the_key_and_records_use(clean_ingestion: Database) -> None:
    with clean_ingestion.session() as s:
        issued = issue_api_key(s, ACTOR, name="gw", scope=ApiKeyScope.INGEST)
    with clean_ingestion.session() as s:
        view = verify_api_key(s, issued.key)
        assert view is not None
        assert view.scope is ApiKeyScope.INGEST
        assert view.last_used_at is not None
        assert verify_api_key(s, issued.key + "x") is None
        assert verify_api_key(s, f"pmp_{issued.prefix}_guess") is None


def test_revoked_keys_stop_working(clean_ingestion: Database) -> None:
    with clean_ingestion.session() as s:
        issued = issue_api_key(s, ACTOR, name="gw", scope=ApiKeyScope.INGEST)
        revoke_api_key(s, ACTOR, issued.id)
    with clean_ingestion.session() as s:
        assert verify_api_key(s, issued.key) is None
        assert not list_api_keys(s)[0].active


def test_rotation_overlaps_until_the_old_key_is_revoked(clean_ingestion: Database) -> None:
    with clean_ingestion.session() as s:
        old = issue_api_key(s, ACTOR, name="gw", scope=ApiKeyScope.INGEST)
        new = rotate_api_key(s, ACTOR, old.id)
    with clean_ingestion.session() as s:
        assert verify_api_key(s, old.key) is not None
        assert verify_api_key(s, new.key) is not None
        revoke_api_key(s, ACTOR, old.id)
    with clean_ingestion.session() as s:
        assert verify_api_key(s, old.key) is None
        assert verify_api_key(s, new.key) is not None


def test_key_administration_is_audited_without_the_secret(clean_ingestion: Database) -> None:
    with clean_ingestion.session() as s:
        issued = issue_api_key(s, ACTOR, name="gw", scope=ApiKeyScope.INGEST)
        revoke_api_key(s, ACTOR, issued.id)
    with clean_ingestion.session() as s:
        entries = s.scalars(
            select(AuditLog)
            .where(AuditLog.entity == "api_key", AuditLog.entity_id == str(issued.id))
            .order_by(AuditLog.id)
        ).all()
    assert [e.action for e in entries][-2:] == ["issue", "revoke"]
    assert all(issued.key not in str(e.before_after) for e in entries)
