"""Alert, priority-matrix, job and fleet-KPI endpoints (plan 5.2b; UC-10, FR-ALM-02 to -04,
FR-VIS-01)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from pmp.api import create_app
from pmp.core import Database, Role, RoleAssignment, Settings, create_user
from pmp.registry import AssetLevel, AssetSpec, find_asset, upsert_asset
from tests.integration.test_alerts import _raise_one
from tests.integration.test_scoring_cycle import (  # noqa: F401  (deployed is a fixture)
    ACTOR,
    LIVE,
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
        upsert_asset(s, ACTOR, AssetSpec("SITE-Z", "Elsewhere", AssetLevel.SITE))
        site_z = find_asset(s, "SITE-Z")
        assert site_z is not None
        for name, role, scope in (
            ("vera", Role.VIEWER, None),
            ("ann", Role.ANALYST, None),
            ("zed", Role.ANALYST, site_z.id),
            ("eng", Role.MODEL_ENGINEER, None),
        ):
            create_user(
                s,
                ACTOR,
                username=name,
                display_name=name,
                password=PASSWORD,
                assignments=[RoleAssignment(role, scope)],
            )
    alert_id = _raise_one(db)  # a DI Warning, P2, on EQ-1 (criticality A)
    settings = Settings(
        database_url=database_url, secret_key="t", artefact_dir=tmp_path, _env_file=None
    )
    with TestClient(create_app(settings=settings, database=db), base_url="https://t") as client:
        headers = {}
        for name in ("vera", "ann", "zed", "eng"):
            token = client.post(
                "/api/v1/auth/token", json={"username": name, "password": PASSWORD}
            ).json()["access_token"]
            headers[name] = {"Authorization": f"Bearer {token}"}
        yield {"client": client, "h": headers, "db": db, "alert_id": alert_id}


def call(api: dict[str, Any], method: str, path: str, user: str, **kwargs: Any) -> Any:
    return api["client"].request(method, path, headers=api["h"][user], **kwargs)


def test_the_alert_list_with_filters_and_scope(api: dict[str, Any]) -> None:
    body = call(api, "GET", "/api/v1/alerts", "vera").json()
    (alert,) = body["items"]
    assert (alert["state"], alert["priority"], alert["asset_code"]) == (
        "Active-Unacknowledged",
        "P2",
        "EQ-1",
    )
    assert alert["kind"] == "di"
    assert (
        call(api, "GET", "/api/v1/alerts", "vera", params={"priority": "P1"}).json()["items"] == []
    )
    assert (
        len(call(api, "GET", "/api/v1/alerts", "vera", params={"asset": "SITE-A"}).json()["items"])
        == 1
    )
    assert call(api, "GET", "/api/v1/alerts", "zed").json()["items"] == []  # out of scope
    assert call(api, "GET", f"/api/v1/alerts/{alert['id']}", "zed").status_code == 404
    assert call(api, "GET", "/api/v1/alerts", "vera", params={"asset": "NOPE"}).status_code == 404


def test_one_alert_with_trace_and_history(api: dict[str, Any]) -> None:
    body = call(api, "GET", f"/api/v1/alerts/{api['alert_id']}", "vera").json()
    assert body["trace"]["rule"]["kind"] == "di"
    assert [h["action"] for h in body["history"]] == ["raise"]


def test_acting_on_alerts_follows_the_matrix(api: dict[str, Any]) -> None:
    alert_id = api["alert_id"]
    refused = call(api, "POST", f"/api/v1/alerts/{alert_id}/ack", "vera")
    assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")
    acked = call(api, "POST", f"/api/v1/alerts/{alert_id}/ack", "ann", json={"comment": "on it"})
    assert acked.status_code == 200
    assert acked.json()[0]["state"] == "Active-Acknowledged"
    again = call(api, "POST", "/api/v1/alerts/ack", "ann", json={"ids": [alert_id]})
    assert (again.status_code, again.json()["code"]) == (409, "invalid_state")
    too_long = call(
        api,
        "POST",
        "/api/v1/alerts/shelve",
        "ann",
        json={"ids": [alert_id], "reason": "work", "minutes": 8 * 24 * 60},
    )
    assert too_long.status_code == 409
    shelved = call(
        api,
        "POST",
        "/api/v1/alerts/shelve",
        "ann",
        json={"ids": [alert_id], "reason": "valve work", "minutes": 60},
    )
    assert shelved.json()[0]["state"] == "Shelved"
    back = call(api, "POST", f"/api/v1/alerts/{alert_id}/unshelve", "ann")
    assert back.json()[0]["state"] == "Active-Unacknowledged"
    assert call(api, "POST", "/api/v1/alerts/ack", "ann", json={"ids": [999]}).status_code == 404


def test_the_priority_matrix(api: dict[str, Any]) -> None:
    cells = call(api, "GET", "/api/v1/priority-matrix", "vera").json()
    assert {"criticality": "A", "severity": "Alert", "priority": "P1"} in cells
    cell = {"criticality": "A", "severity": "Warning", "priority": "P1"}
    assert call(api, "PUT", "/api/v1/priority-matrix", "ann", json=cell).status_code == 403
    try:
        changed = call(api, "PUT", "/api/v1/priority-matrix", "eng", json=cell).json()
        assert [(a["id"], a["priority"]) for a in changed] == [(api["alert_id"], "P1")]
    finally:
        cell["priority"] = "P2"
        call(api, "PUT", "/api/v1/priority-matrix", "eng", json=cell)


def test_fleet_kpis(api: dict[str, Any]) -> None:
    kpis = call(api, "GET", "/api/v1/fleet/kpis", "vera").json()
    assert kpis["open_alerts"] == {"P2": 1}
    assert kpis["unacknowledged_alerts"] == {"P2": 1}
    assert sum(kpis["assets_by_band"].values()) == 1
    assert sum(kpis["sensors_by_status"].values()) == 4
    assert kpis["models_by_status"] == {"Running": 1}
    assert len(kpis["stale_models"]) == 1  # the test's cycle is months before now
    scoped = call(api, "GET", "/api/v1/fleet/kpis", "zed").json()
    assert scoped["open_alerts"] == {}
    assert scoped["stale_models"] == []


def test_jobs_are_readable_by_users(api: dict[str, Any]) -> None:
    with api["db"].session() as s:
        job_id = s.execute(
            text(
                "INSERT INTO job (type, payload, status, attempts, max_attempts) "
                "VALUES ('model.train', '{}', 'queued', 0, 5) RETURNING id"
            )
        ).scalar_one()
    assert call(api, "GET", f"/api/v1/jobs/{job_id}", "vera").json()["status"] == "queued"
    assert api["client"].get(f"/api/v1/jobs/{job_id}").status_code == 401


def test_the_docs_offer_a_bearer_token(api: dict[str, Any]) -> None:
    schema = api["client"].get("/api/v1/openapi.json").json()
    assert "HTTPBearer" in schema["components"]["securitySchemes"]


def test_a_thousand_alerts_filter_in_under_a_second(api: dict[str, Any]) -> None:
    """NFR-PERF-03 / FR-ALM-03: filtering 1,000 alerts in under 1 s."""
    with api["db"].session() as s:
        s.execute(
            text(
                "INSERT INTO alert (model_id, kind, state, severity, priority, condition_active,"
                " raised_at, version_id, trace) "
                "SELECT a.model_id, 'di', (ARRAY['Active-Unacknowledged','Active-Acknowledged',"
                "'RTN-Unacknowledged','Shelved'])[1 + i % 4], 'Warning', 'P' || (1 + i % 4), true,"
                " :t + i * interval '1 minute', a.version_id, '{}' "
                "FROM alert a, generate_series(1, 1000) i WHERE a.id = :id"
            ),
            {"t": LIVE, "id": api["alert_id"]},
        )
    started = time.perf_counter()
    response = call(
        api,
        "GET",
        "/api/v1/alerts",
        "vera",
        params={"priority": ["P1", "P2"], "state": "Active-Unacknowledged", "limit": 1000},
    )
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert len(response.json()["items"]) == 251  # 250 P1 unacknowledged + the original P2
    assert elapsed < 1.0, f"{elapsed:.2f} s"
    page_one = call(api, "GET", "/api/v1/alerts", "vera", params={"limit": 400}).json()
    page_two = call(
        api,
        "GET",
        "/api/v1/alerts",
        "vera",
        params={"limit": 400, "cursor": page_one["next_cursor"]},
    ).json()
    ids = [a["id"] for a in page_one["items"] + page_two["items"]]
    assert len(ids) == len(set(ids)) == 800
    items = page_one["items"] + page_two["items"]
    unacked = [a["state"] in ("Active-Unacknowledged", "RTN-Unacknowledged") for a in items]
    assert unacked == sorted(unacked, reverse=True)  # every unacknowledged alert first
    first = [a["priority"] for a in items[: unacked.count(True)]]
    assert first == sorted(first)  # then by priority
