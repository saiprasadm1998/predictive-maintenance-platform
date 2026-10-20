"""History upload over HTTP: preview, load, job status (UC-02, ARC §7.1.3)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from pmp.api import create_app
from pmp.core import (
    Actor,
    ApiKeyScope,
    Database,
    JobRegistry,
    Settings,
    Worker,
    issue_api_key,
)
from pmp.ingestion import BACKFILL_JOB, count_samples, make_backfill_handler, server_now
from pmp.registry import AssetLevel, AssetSpec, Criticality, TagSpec, upsert_asset, upsert_tag

pytestmark = pytest.mark.integration
ACTOR = Actor.system()
SOURCE = "gw-site-a-01"
TAG = "K101.TI1012.PV"


@pytest.fixture
def env(clean_ingestion: Database, database_url: str, tmp_path: Path) -> Iterator[dict[str, Any]]:
    db = clean_ingestion
    with db.session() as s:
        s.execute(text("TRUNCATE job RESTART IDENTITY"))
        upsert_asset(s, ACTOR, AssetSpec("SITE-A", "Site A", AssetLevel.SITE))
        upsert_asset(
            s, ACTOR, AssetSpec("K-101", "K-101", AssetLevel.EQUIPMENT, "SITE-A", Criticality.A)
        )
        upsert_tag(s, ACTOR, TagSpec(SOURCE, TAG, "K-101", "°C", 0, 150, 60))
        key = issue_api_key(s, ACTOR, name="gw", scope=ApiKeyScope.INGEST).key
        start = server_now(s) - timedelta(days=3)
    settings = Settings(
        database_url=database_url, secret_key="t", artefact_dir=tmp_path, _env_file=None
    )
    registry = JobRegistry()
    registry.register(BACKFILL_JOB, make_backfill_handler(db, tmp_path / "uploads"))
    csv = "ts,tag,value\n" + "".join(
        f"{(start + timedelta(minutes=i)).isoformat()},{TAG},{i}\n" for i in range(10)
    )
    with TestClient(create_app(settings=settings, database=db)) as client:
        yield {
            "db": db,
            "client": client,
            "headers": {"Authorization": f"ApiKey {key}"},
            "worker": Worker(db, registry, name="test"),
            "csv": csv.encode(),
            "uploads": tmp_path / "uploads",
        }


def _upload(
    env: dict[str, Any], *, preview: bool, name: str = "h.csv", data: bytes | None = None
) -> Any:
    return env["client"].post(
        "/api/v1/ingest/backfill",
        headers=env["headers"],
        files={"file": (name, data if data is not None else env["csv"], "text/csv")},
        data={"source": SOURCE, "preview": str(preview).lower()},
    )


def _job(env: dict[str, Any], job_id: int) -> dict[str, Any]:
    response = env["client"].get(f"/api/v1/jobs/{job_id}", headers=env["headers"])
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def _count(env: dict[str, Any]) -> int:
    with env["db"].session() as s:
        return count_samples(s)


def test_preview_then_load_the_same_upload(env: dict[str, Any]) -> None:
    queued = _upload(env, preview=True)
    assert queued.status_code == 202
    job_id, upload_id = queued.json()["job_id"], queued.json()["upload_id"]
    assert _job(env, job_id)["status"] == "queued"

    assert env["worker"].run_once()
    preview = _job(env, job_id)
    assert preview["status"] == "succeeded"
    assert preview["result"]["preview"] is True
    assert preview["result"]["rows_read"] == 10
    assert _count(env) == 0  # nothing stored by a preview

    loaded = env["client"].post(
        f"/api/v1/ingest/backfill/{upload_id}/load", headers=env["headers"], json={"source": SOURCE}
    )
    assert loaded.status_code == 202
    assert env["worker"].run_once()
    result = _job(env, loaded.json()["job_id"])["result"]
    assert (result["loaded"], result["reconciles"]) == (10, True)
    assert _count(env) == 10
    assert not any(env["uploads"].iterdir())  # removed after a successful import


def test_upload_without_preview_imports_directly(env: dict[str, Any]) -> None:
    queued = _upload(env, preview=False)
    assert env["worker"].run_once()
    assert _job(env, queued.json()["job_id"])["result"]["loaded"] == 10


def test_unsupported_file_type_is_415(env: dict[str, Any]) -> None:
    assert _upload(env, preview=True, name="h.xlsx").status_code == 415


def test_file_without_a_timestamp_column_is_400(env: dict[str, Any]) -> None:
    response = _upload(env, preview=True, data=b"time,tag,value\nx,y,1\n")
    assert response.status_code == 400
    assert "timestamp column" in response.json()["detail"]
    assert not any(env["uploads"].iterdir())


def test_unknown_upload_and_job_are_404(env: dict[str, Any]) -> None:
    load = env["client"].post(
        f"/api/v1/ingest/backfill/{'0' * 32}/load", headers=env["headers"], json={"source": SOURCE}
    )
    assert load.status_code == 404
    assert env["client"].get("/api/v1/jobs/999", headers=env["headers"]).status_code == 404


def test_upload_needs_an_ingest_key(env: dict[str, Any]) -> None:
    response = env["client"].post(
        "/api/v1/ingest/backfill",
        files={"file": ("h.csv", env["csv"], "text/csv")},
        data={"source": SOURCE},
    )
    assert response.status_code == 401


def test_an_ingest_key_reads_only_its_own_history_jobs(env: dict[str, Any]) -> None:
    """ARC §1.2: a leaked ingest key can only write samples; it cannot read other jobs."""
    job_id = _upload(env, preview=True).json()["job_id"]
    with env["db"].session() as s:
        other = issue_api_key(s, ACTOR, name="other", scope=ApiKeyScope.INGEST).key
        s.execute(
            text(
                "INSERT INTO job (type, payload, status, attempts, max_attempts) "
                "VALUES ('model.train', '{\"version_id\": 1}', 'succeeded', 1, 5)"
            )
        )
        training_id = s.execute(text("SELECT max(id) FROM job")).scalar_one()
    client = env["client"]
    assert client.get(f"/api/v1/jobs/{job_id}", headers=env["headers"]).status_code == 200
    stranger = {"Authorization": f"ApiKey {other}"}
    assert client.get(f"/api/v1/jobs/{job_id}", headers=stranger).status_code == 404
    assert client.get(f"/api/v1/jobs/{training_id}", headers=env["headers"]).status_code == 404
