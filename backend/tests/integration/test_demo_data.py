"""Demo plant end to end (plan 1.4 "Done when"): history through the history import,
live replay through the ingestion API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from pmp.api import create_app
from pmp.core import Actor, ApiKeyScope, Database, Settings, issue_api_key
from pmp.demo import PlantSimulator, demo_tags, load_history, replay
from pmp.ingestion import count_samples
from pmp.registry import import_files

pytestmark = pytest.mark.integration
ACTOR = Actor.system()
REGISTRY = Path(__file__).resolve().parents[3] / "data" / "demo" / "registry" / "registry.xlsx"


@pytest.fixture
def demo_db(clean_ingestion: Database) -> Database:
    with clean_ingestion.session() as s:
        report = import_files(s, ACTOR, [REGISTRY])
        assert report.ok, report.summary()
    return clean_ingestion


def _samples_per_tag(db: Database) -> dict[str, int]:
    with db.session() as s:
        rows = s.execute(
            text(
                "SELECT t.source_name, count(*) FROM sample s JOIN tag t ON t.id = s.tag_id "
                "GROUP BY t.source_name"
            )
        )
        return {str(name): int(n) for name, n in rows}


def test_demo_history_loads_for_every_asset(demo_db: Database, tmp_path: Path) -> None:
    with demo_db.session() as s:
        tags = demo_tags(s)
    assert len(tags) == 60
    simulator = PlantSimulator(tags)

    reports = load_history(demo_db, simulator, days=2, work_dir=tmp_path)

    assert set(reports) == {"gw-site-a-01", "gw-site-b-01"}
    assert all(r.reconciles and r.rejected == 0 for r in reports.values())
    per_tag = _samples_per_tag(demo_db)
    assert len(per_tag) == 54  # P-202's 6 tags sent nothing in the last 2 days
    assert per_tag["K101.TI1012.PV"] == 2 * 1440
    assert per_tag["K201.FI2203.PV"] == 2 * 1440 - 3 * 60  # stale for the last 3 hours
    assert "P202.PI2021.PV" not in per_tag  # gateway link lost for the last 2 days
    assert list(tmp_path.iterdir()) == []  # work files removed

    again = load_history(demo_db, simulator, days=2, work_dir=tmp_path)  # harmless re-run
    assert all(r.loaded == 0 and r.reconciles for r in again.values())
    assert _samples_per_tag(demo_db) == per_tag


def test_live_replay_feeds_the_ingestion_api(
    demo_db: Database, database_url: str, tmp_path: Path
) -> None:
    with demo_db.session() as s:
        key = issue_api_key(s, ACTOR, name="demo", scope=ApiKeyScope.INGEST).key
        tags = demo_tags(s)
    settings = Settings(
        database_url=database_url, secret_key="t", artefact_dir=tmp_path, _env_file=None
    )
    with TestClient(create_app(settings=settings, database=demo_db)) as client:

        def post(url: str, api_key: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            response = client.post(
                url, json=payload, headers={"Authorization": f"ApiKey {api_key}"}
            )
            body: dict[str, Any] = response.json()
            return response.status_code, body

        start = datetime.now(UTC) - timedelta(minutes=30)  # recent past: never ahead
        stats = replay(
            PlantSimulator(tags),
            url="/api/v1/ingest/samples",
            key=key,
            start=start,
            minutes=3,
            speed=1e6,
            post=post,
            log=lambda _: None,
            sleep=lambda _: None,
        )

    assert stats.failed_batches == 0
    assert stats.rejected == 0
    with demo_db.session() as s:
        assert count_samples(s) == stats.accepted > 0
