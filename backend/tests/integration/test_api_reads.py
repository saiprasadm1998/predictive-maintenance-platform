"""Read endpoints for the screens (plan 5.2a; ARC §7.3, FR-HLT-01, FR-VIS-02, NFR-PERF-03)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from pmp.api import create_app
from pmp.core import Database, Role, RoleAssignment, Settings, create_user
from pmp.registry import AssetLevel, AssetSpec, find_asset, upsert_asset
from pmp.scoring import Scheduler
from tests.integration.test_scoring_cycle import (  # noqa: F401  (deployed is a fixture)
    ACTOR,
    LIVE,
    Clock,
    deployed,
)

pytestmark = pytest.mark.integration
PASSWORD = "correct horse battery"


@pytest.fixture
def api(
    request: pytest.FixtureRequest, database_url: str, tmp_path: Path
) -> Iterator[dict[str, Any]]:
    db: Database = request.getfixturevalue("deployed")
    with db.session() as s:
        s.execute(text("TRUNCATE app_user RESTART IDENTITY CASCADE"))
        upsert_asset(s, ACTOR, AssetSpec("SITE-B", "Site B", AssetLevel.SITE))
        site_b = find_asset(s, "SITE-B")
        assert site_b is not None
        for name, role, scope in (
            ("viewer", Role.VIEWER, None),
            ("bob", Role.ANALYST, site_b.id),
        ):
            create_user(
                s,
                ACTOR,
                username=name,
                display_name=name,
                password=PASSWORD,
                assignments=[RoleAssignment(role, scope)],
            )
    scheduler = Scheduler(db, clock=Clock(LIVE + timedelta(minutes=1, seconds=30)))
    for _ in range(3):
        scheduler.tick()
        scheduler.clock.now += timedelta(minutes=1)  # type: ignore[attr-defined]
    scheduler.clock.now = LIVE + timedelta(days=2, seconds=30)  # type: ignore[attr-defined]
    scheduler.tick()  # data stopped: Insufficient data, no DI
    settings = Settings(
        database_url=database_url, secret_key="t", artefact_dir=tmp_path, _env_file=None
    )
    with TestClient(create_app(settings=settings, database=db), base_url="https://t") as client:
        headers = {}
        for name in ("viewer", "bob"):
            token = client.post(
                "/api/v1/auth/token", json={"username": name, "password": PASSWORD}
            ).json()["access_token"]
            headers[name] = {"Authorization": f"Bearer {token}"}
        yield {"client": client, "headers": headers, "db": db}


def get(api: dict[str, Any], path: str, user: str = "viewer", **params: Any) -> Any:
    return api["client"].get(path, headers=api["headers"][user], params=params)


def test_reads_need_a_signed_in_user(api: dict[str, Any]) -> None:
    response = api["client"].get("/api/v1/assets")
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"


def test_the_tree_carries_the_health_roll_up(api: dict[str, Any]) -> None:
    roots = get(api, "/api/v1/assets", tree="true").json()
    site_a = next(r for r in roots if r["code"] == "SITE-A")
    (eq1,) = site_a["children"]
    assert eq1["code"] == "EQ-1"
    assert eq1["band"] == "Unknown"  # its latest cycle had insufficient data
    assert eq1["models"][0]["reason"].startswith("Insufficient data")
    assert site_a["band"] == "Unknown"
    assert site_a["counts"] == {"Unknown": 1}
    assert next(r for r in roots if r["code"] == "SITE-B")["band"] is None  # no model


def test_the_tree_counts_open_alerts_up_the_hierarchy(api: dict[str, Any]) -> None:
    def site_a() -> dict[str, Any]:
        roots = get(api, "/api/v1/assets", tree="true").json()
        found: dict[str, Any] = next(r for r in roots if r["code"] == "SITE-A")
        return found

    before = site_a()["open_alerts"]
    with api["db"].session() as s:
        model_id, version_id = s.execute(
            text("SELECT model_id, id FROM model_version WHERE status = 'Deployed'")
        ).one()
        for state in ("Active-Unacknowledged", "RTN-Unacknowledged", "Out of service", "Normal"):
            s.execute(
                text(
                    "INSERT INTO alert (model_id, kind, state, severity, priority, "
                    "condition_active, raised_at, version_id, trace) VALUES (:m, 'di', :st, "
                    "'Warning', 'P3', true, now(), :v, '{}')"
                ),
                {"m": model_id, "v": version_id, "st": state},
            )
    after = site_a()
    assert after["open_alerts"] == before + 2  # out of service and closed are not counted
    assert after["children"][0]["open_alerts"] == after["open_alerts"]  # all on EQ-1
    detail = get(api, f"/api/v1/assets/{after['id']}").json()
    assert detail["health"]["open_alerts"] == after["open_alerts"]


def test_flat_assets_are_paged_with_a_cursor(api: dict[str, Any]) -> None:
    first = get(api, "/api/v1/assets", limit=2).json()
    assert len(first["items"]) == 2
    rest = get(api, "/api/v1/assets", limit=2, cursor=first["next_cursor"]).json()
    codes = [a["code"] for a in first["items"] + rest["items"]]
    assert sorted(codes) == ["EQ-1", "SITE-A", "SITE-B"]
    assert rest["next_cursor"] is None
    assert get(api, "/api/v1/assets", cursor="!!").status_code == 400


def test_a_scoped_user_sees_only_their_part(api: dict[str, Any]) -> None:
    roots = get(api, "/api/v1/assets", "bob", tree="true").json()
    assert [r["code"] for r in roots] == ["SITE-B"]
    with api["db"].session() as s:
        eq1 = find_asset(s, "EQ-1")
    assert eq1 is not None
    assert get(api, f"/api/v1/assets/{eq1.id}", "bob").status_code == 404
    assert get(api, "/api/v1/models", "bob").json() == []
    assert get(api, "/api/v1/tags", "bob").json()["items"] == []


def test_one_asset_with_its_breadcrumb(api: dict[str, Any]) -> None:
    with api["db"].session() as s:
        eq1 = find_asset(s, "EQ-1")
    assert eq1 is not None
    body = get(api, f"/api/v1/assets/{eq1.id}").json()
    assert [c["code"] for c in body["ancestors"]] == ["SITE-A"]
    assert body["health"]["code"] == "EQ-1"
    assert get(api, "/api/v1/assets/99999").status_code == 404


def test_tags_types_and_sensor_health(api: dict[str, Any]) -> None:
    tags = get(api, "/api/v1/tags", asset="EQ-1").json()["items"]
    assert len(tags) == 4
    assert get(api, "/api/v1/tags", asset="NOPE").status_code == 404
    assert get(api, "/api/v1/asset-types").status_code == 200
    health = get(api, "/api/v1/sensors/health", asset="EQ-1").json()
    assert {h["status"] for h in health} == {"Failure"}  # data stopped two days ago


def test_models_with_runtime_and_rules(api: dict[str, Any]) -> None:
    (model,) = get(api, "/api/v1/models").json()
    assert model["runtime"]["status"] == "Insufficient data"
    assert model["in_service"]["status"] == "Deployed"
    detail = get(api, f"/api/v1/models/{model['id']}").json()
    assert len(detail["versions"][0]["sensors"]) == 4
    assert {r["kind"] for r in detail["alert_rules"]} == {"di", "sensor"}
    assert all(r["state"] for r in detail["alert_rules"])
    assert get(api, "/api/v1/models/999").status_code == 404


def test_score_trends_raw_and_downsampled(api: dict[str, Any]) -> None:
    (model,) = get(api, "/api/v1/models").json()
    path = f"/api/v1/models/{model['id']}/scores"
    start = LIVE.isoformat()
    raw = get(api, path, **{"from": start, "to": (LIVE + timedelta(hours=1)).isoformat()}).json()
    assert raw["raw"] is True
    assert len(raw["ts"]) == 3
    assert raw["min"]["di"] == raw["max"]["di"]
    long = get(
        api, path, px=10, **{"from": start, "to": (LIVE + timedelta(days=3)).isoformat()}
    ).json()
    assert long["raw"] is False
    assert long["bucket_s"] == pytest.approx(3 * 86400 / 10)
    assert len(long["ts"]) == 2  # the first hour's three cycles, and the one two days later
    assert long["min"]["di"][0] <= long["max"]["di"][0]
    assert long["min"]["di"][1] is None  # Insufficient data: no DI
    assert get(api, path, **{"from": "2026-06-01T00:00:00"}).status_code == 400  # no zone
    assert get(api, path, px=0).status_code == 400


def test_sensor_output_trends(api: dict[str, Any]) -> None:
    (model,) = get(api, "/api/v1/models").json()
    path = f"/api/v1/models/{model['id']}/outputs"
    period = {"from": LIVE.isoformat(), "to": (LIVE + timedelta(hours=1)).isoformat()}
    one = get(api, path, tags="EQ1.T1", **period).json()
    assert [t["source_name"] for t in one] == ["EQ1.T1"]
    assert len(one[0]["ts"]) == 3
    assert set(one[0]["min"]) == {"actual", "predicted", "residual", "q", "z"}
    assert len(get(api, path, **period).json()) == 4
    assert get(api, path, tags="EQ1.NOPE").status_code == 400


def test_errors_are_problem_details(api: dict[str, Any]) -> None:
    missing = get(api, "/api/v1/nowhere")
    assert (missing.status_code, missing.json()["code"]) == (404, "not_found")
    wrong = api["client"].delete("/api/v1/assets", headers=api["headers"]["viewer"])
    assert (wrong.status_code, wrong.json()["code"]) == (405, "method_not_allowed")
    assert api["client"].get("/readyz").json() == {"status": "ready"}
