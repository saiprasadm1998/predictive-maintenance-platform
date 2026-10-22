"""Write endpoints follow the role matrix and the services' rules (plan 5.2c)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from pmp.api import create_app
from pmp.core import Database, Role, RoleAssignment, Settings, create_user
from tests.integration.test_scoring_cycle import (  # noqa: F401  (deployed is a fixture)
    ACTOR,
    LIVE,
    T0,
    deployed,
)

pytestmark = pytest.mark.integration
PASSWORD = "correct horse battery"


@pytest.fixture
def api(request: pytest.FixtureRequest, database_url: str, tmp_path: Path) -> Iterator[Any]:
    db: Database = request.getfixturevalue("deployed")
    with db.session() as s:
        s.execute(text("TRUNCATE app_user RESTART IDENTITY CASCADE"))
        for name, role in (
            ("vera", Role.VIEWER),
            ("eng", Role.MODEL_ENGINEER),
            ("root", Role.ADMINISTRATOR),
        ):
            create_user(
                s,
                ACTOR,
                username=name,
                display_name=name,
                password=PASSWORD,
                assignments=[RoleAssignment(role)],
            )
    settings = Settings(
        database_url=database_url, secret_key="t", artefact_dir=tmp_path, _env_file=None
    )
    with TestClient(create_app(settings=settings, database=db), base_url="https://t") as client:

        def as_(user: str) -> dict[str, str]:
            token = client.post(
                "/api/v1/auth/token", json={"username": user, "password": PASSWORD}
            ).json()["access_token"]
            return {"Authorization": f"Bearer {token}"}

        yield client, {u: as_(u) for u in ("vera", "eng", "root")}


def test_viewers_cannot_change_the_registry(api: Any) -> None:
    client, h = api
    site = {"code": "SITE-Q", "name": "Q", "level": "site"}
    assert client.post("/api/v1/assets", json=site, headers=h["vera"]).status_code == 403
    assert client.post("/api/v1/assets", json=site, headers=h["root"]).status_code == 201
    bad = client.post(
        "/api/v1/assets", json={**site, "code": "X", "level": "planet"}, headers=h["root"]
    )
    assert (bad.status_code, bad.json()["code"]) == (400, "invalid_level")


def test_a_rejected_model_lists_every_problem(api: Any) -> None:
    client, h = api
    definition = {
        "asset": "EQ-1",
        "name": "bad",
        "sensors": ["EQ1.NOPE"],
        "training_periods": [{"start": "-2d", "end": "-1d"}],
        "validation_period": {"start": "-3d", "end": "-1d"},
    }
    response = client.post("/api/v1/models", json=definition, headers=h["eng"])
    body = response.json()
    assert (response.status_code, body["code"]) == (400, "model_refused")
    assert len(body["problems"]) >= 2
    assert client.post("/api/v1/models", json=definition, headers=h["root"]).status_code == 403


def test_data_quality_changes_need_confirmation_when_much_is_excluded(api: Any) -> None:
    client, h = api
    harsh = {"scope": "global", "overrides": {"spike_pct": 0.001}, "days": 30}
    preview = client.post("/api/v1/dq/rules/preview", json=harsh, headers=h["eng"]).json()
    assert preview["warning"] is True
    refused = client.put("/api/v1/dq/rules", json=harsh, headers=h["eng"])
    assert (refused.status_code, refused.json()["code"]) == (409, "preview_warning")
    assert (
        client.put(
            "/api/v1/dq/rules", json={**harsh, "confirm": True}, headers=h["root"]
        ).status_code
        == 403
    )  # not an administrator's job
    saved = client.put("/api/v1/dq/rules", json={**harsh, "confirm": True}, headers=h["eng"])
    assert saved.json()["rules"]["version"] == 1
    assert (
        client.get("/api/v1/dq/rules", params={"scope": "nonsense"}, headers=h["eng"]).status_code
        == 400
    )


def test_administrators_manage_users_over_the_api(api: Any) -> None:
    client, h = api
    users = {u["username"]: u for u in client.get("/api/v1/users", headers=h["root"]).json()}
    assert client.get("/api/v1/users", headers=h["eng"]).status_code == 403
    vera = users["vera"]["id"]
    off = client.patch(f"/api/v1/users/{vera}", json={"active": False}, headers=h["root"])
    assert off.json()["active"] is False
    assert client.get("/api/v1/auth/me", headers=h["vera"]).status_code == 401  # session ended
    weak = client.post(
        "/api/v1/users",
        json={"username": "x-new", "password": "short", "roles": [{"role": "viewer"}]},
        headers=h["root"],
    )
    assert (weak.status_code, weak.json()["code"]) == (400, "user_refused")


def _eq1(**changes: Any) -> dict[str, Any]:
    definition: dict[str, Any] = {
        "asset": "EQ-1",
        "name": "main",
        "sensors": [{"tag": "EQ1.T1", "required": True}, "EQ1.T2", "EQ1.T3"],
        "training_periods": [
            {"start": T0.isoformat(), "end": (LIVE - (LIVE - T0) / 4).isoformat()}
        ],
        "validation_period": {
            "start": (LIVE - (LIVE - T0) / 4).isoformat(),
            "end": LIVE.isoformat(),
        },
        "mode_filters": ["EQ1.MOTOR > 120"],
    }
    return {**definition, **changes}


def test_the_training_data_preview_shows_what_each_rule_removes(api: Any) -> None:
    client, h = api
    url = "/api/v1/models/training-data"
    found = client.post(url, json=_eq1(), params={"px": 50}, headers=h["eng"]).json()
    assert found["cycles"] == 3 * 1440
    assert found["mode_removed"] == 0  # the motor runs throughout
    assert found["retained"] == found["cycles"] - found["quality_removed"]
    assert found["blocked"] is None
    assert [s["source_name"] for s in found["sensors"]] == ["EQ1.T1", "EQ1.T2", "EQ1.T3"]
    assert 40 <= len(found["buckets"]) <= 50
    assert found["bucket_s"] % 60 == 0
    assert len(found["excluded"]) == len(found["buckets"])
    assert all(0 <= x <= 1 for x in found["excluded"])
    assert set(found["values"]) == {"EQ1.T1", "EQ1.T2", "EQ1.T3"}
    assert all(len(v) == len(found["buckets"]) for v in found["values"].values())

    stopped = client.post(
        url,
        json=_eq1(mode_filters=["EQ1.MOTOR > 500"]),
        headers=h["eng"],
    ).json()
    assert (stopped["retained"], stopped["mode_removed"]) == (0, 3 * 1440)
    assert stopped["blocked"].startswith("Training blocked: only 0 clean samples")
    assert all(x == 1 for x in stopped["excluded"])

    refused = client.post(url, json=_eq1(sensors=["EQ1.NOPE"]), headers=h["eng"])
    assert (refused.status_code, refused.json()["code"]) == (400, "model_refused")
    assert client.post(url, json=_eq1(), headers=h["vera"]).status_code == 403


def test_a_new_draft_without_alert_rules_keeps_the_models_rules(api: Any) -> None:
    client, h = api
    model = next(m for m in client.get("/api/v1/models", headers=h["eng"]).json())
    before = client.get(f"/api/v1/models/{model['id']}", headers=h["eng"]).json()["alert_rules"]
    assert len(before) == 2
    saved = client.post("/api/v1/models", json=_eq1(), headers=h["eng"])
    assert saved.status_code == 201
    body = saved.json()
    assert (body["latest"]["status"], body["latest"]["version"]) == ("Draft", 2)
    assert [r["id"] for r in body["alert_rules"]] == [r["id"] for r in before]
