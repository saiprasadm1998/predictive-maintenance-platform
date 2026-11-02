"""Backup and restore against PostgreSQL (plan 9.1, NFR-REL-03).

"Done when": a backup restores into an empty database with the same data and artefacts.
Needs the PostgreSQL client tools (pg_dump and pg_restore, version 16).
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from pmp.core import Actor, BackupError, Database, last_backup, restore, run_backup
from pmp.registry import AssetLevel, AssetSpec, upsert_asset
from tests.integration.conftest import ADMIN_URL

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("pg_dump") is None, reason="no PostgreSQL client tools"),
]
RESTORED = "pmp_restore_test"
COUNTED = ("asset", "tag", "sample", "app_user", "backup_run")


def _admin(statement: str) -> None:
    engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text(statement))
    finally:
        engine.dispose()


@pytest.fixture
def empty_url() -> Iterator[str]:
    _admin(f"DROP DATABASE IF EXISTS {RESTORED} WITH (FORCE)")
    _admin(f"CREATE DATABASE {RESTORED}")
    yield make_url(ADMIN_URL).set(database=RESTORED).render_as_string(hide_password=False)
    _admin(f"DROP DATABASE IF EXISTS {RESTORED} WITH (FORCE)")


def _counts(url: str) -> dict[str, int]:
    db = Database(url)
    try:
        with db.session() as s:
            return {t: s.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() for t in COUNTED}
    finally:
        db.dispose()


def test_a_backup_restores_into_an_empty_database(
    database: Database, database_url: str, empty_url: str, tmp_path: Path
) -> None:
    with database.session() as s:
        s.execute(text("TRUNCATE backup_run"))
        upsert_asset(s, Actor.system(), AssetSpec("BK-1", "Backup test", AssetLevel.SITE))
    artefacts = tmp_path / "artefacts"
    (artefacts / "models" / "7").mkdir(parents=True)
    (artefacts / "models" / "7" / "model.joblib").write_bytes(b"trained")

    result = run_backup(database, database_url, artefacts, tmp_path / "backups")

    assert result.dump.stat().st_size > 0
    with database.session() as s:
        run = last_backup(s)
    assert run is not None
    assert (run.status, run.name, run.error) == ("succeeded", result.name, None)
    before = _counts(database_url)

    target = tmp_path / "restored-artefacts"
    summary = restore(empty_url, result.dump, result.artefacts, target)

    after = _counts(empty_url)
    assert after == before
    assert summary["artefact_files"] == 3  # two folders and the file
    assert (target / "models" / "7" / "model.joblib").read_bytes() == b"trained"
    restored = Database(empty_url)
    try:
        with restored.session() as s:
            assert s.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert s.execute(text("SELECT name FROM asset WHERE code = 'BK-1'")).scalar_one()
    finally:
        restored.dispose()

    with pytest.raises(BackupError, match="not empty"):
        restore(empty_url, result.dump, None, target)


def test_a_failed_backup_is_recorded(database: Database, tmp_path: Path) -> None:
    wrong = make_url(ADMIN_URL).set(database="no_such_database").render_as_string(False)
    with pytest.raises(BackupError, match="pg_dump failed"):
        run_backup(database, wrong, tmp_path, tmp_path / "backups")
    with database.session() as s:
        run = last_backup(s)
    assert run is not None
    assert run.status == "failed"
    assert run.error is not None
    assert "no_such_database" in run.error
    assert list((tmp_path / "backups").iterdir()) == []  # no half-written copy left
