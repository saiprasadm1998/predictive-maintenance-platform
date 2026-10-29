"""The API contract (plan 5.2c; FR-API-01, ARC §7.3).

1. /api/v1/openapi.json is a valid OpenAPI 3.1 document.
2. Every documented operation is called at least once in a realistic flow, and every JSON
   response body matches the schema the document gives for its status code. So the
   document and the API cannot drift apart: an endpoint added without a call here, or a
   response that no longer matches its schema, fails this test.
3. The ARC §9.2 role matrix at every endpoint (FR-SEC-01, AC-07; plan 6.7): every
   operation is classified by the permission it needs, and each call the flow made is
   made again as every role the matrix refuses, which must get 403.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate
from sqlalchemy import text

from pmp.api import create_app
from pmp.core import (
    MATRIX,
    Database,
    JobRegistry,
    Permission,
    Role,
    RoleAssignment,
    Settings,
    Worker,
    create_user,
)
from pmp.ingestion import BACKFILL_JOB, make_backfill_handler
from tests.integration.test_alerts import _raise_one
from tests.integration.test_prognostics import seed_di_ramp
from tests.integration.test_scoring_cycle import (  # noqa: F401  (deployed is a fixture)
    ACTOR,
    LIVE,
    deployed,
)

pytestmark = pytest.mark.integration
PASSWORD = "correct horse battery"
DATA = Path(__file__).parents[3] / "data" / "demo"


# The permission each operation needs (ARC §9.2); None: any signed-in user or no sign-in
# (reads are VIEW, filtered by scope), "key": an API key.
V, A = Permission.VIEW, Permission.ALERT_ACTIONS
PERMISSIONS: dict[tuple[str, str], Permission | str | None] = {
    ("GET", "/healthz"): None,
    ("GET", "/readyz"): None,
    ("POST", "/api/v1/auth/login"): None,
    ("POST", "/api/v1/auth/token"): None,
    ("POST", "/api/v1/auth/logout"): None,
    ("GET", "/api/v1/auth/me"): None,
    ("POST", "/api/v1/auth/password"): None,
    ("GET", "/api/v1/api-keys"): Permission.ADMINISTRATION,
    ("POST", "/api/v1/api-keys"): Permission.ADMINISTRATION,
    ("POST", "/api/v1/api-keys/{key_id}/revoke"): Permission.ADMINISTRATION,
    ("POST", "/api/v1/api-keys/{key_id}/rotate"): Permission.ADMINISTRATION,
    ("GET", "/api/v1/audit"): Permission.AUDIT_LOG,
    ("GET", "/api/v1/audit.csv"): Permission.AUDIT_LOG,
    ("GET", "/api/v1/retention"): Permission.ADMINISTRATION,
    ("PUT", "/api/v1/retention"): Permission.ADMINISTRATION,
    ("GET", "/api/v1/assets"): V,
    ("POST", "/api/v1/assets"): Permission.REGISTRY,
    ("GET", "/api/v1/assets/{asset_id}"): V,
    ("PATCH", "/api/v1/assets/{asset_id}"): Permission.REGISTRY,
    ("GET", "/api/v1/tags"): V,
    ("POST", "/api/v1/tags"): Permission.REGISTRY,
    ("PATCH", "/api/v1/tags/{tag_id}"): Permission.REGISTRY,
    ("POST", "/api/v1/tags/import"): Permission.REGISTRY,
    ("GET", "/api/v1/asset-types"): V,
    ("POST", "/api/v1/asset-types"): Permission.REGISTRY,
    ("POST", "/api/v1/asset-types/{type_id}/roles"): Permission.REGISTRY,
    ("GET", "/api/v1/unmapped-tags"): V,
    ("POST", "/api/v1/unmapped-tags/promote"): Permission.REGISTRY,
    ("GET", "/api/v1/sensors/health"): V,
    ("POST", "/api/v1/sensors/{tag_id}/exclusions"): Permission.SENSOR_EXCLUSION,
    ("POST", "/api/v1/sensor-exclusions/{exclusion_id}/end"): Permission.SENSOR_EXCLUSION,
    ("GET", "/api/v1/sensor-exclusions"): V,
    ("GET", "/api/v1/library"): V,
    ("GET", "/api/v1/library/{mode_id}/versions"): V,
    ("PUT", "/api/v1/library"): Permission.FAILURE_MODES,
    ("POST", "/api/v1/library/{mode_id}/retire"): Permission.FAILURE_MODES,
    ("GET", "/api/v1/models/{model_id}/diagnostics"): V,
    ("POST", "/api/v1/forecasts"): Permission.RUN_FORECASTS,
    ("GET", "/api/v1/forecasts"): V,
    ("GET", "/api/v1/forecasts/{forecast_id}"): V,
    ("GET", "/api/v1/cases"): V,
    ("POST", "/api/v1/cases"): Permission.MANAGE_CASES,
    ("GET", "/api/v1/cases/{case_id}"): V,
    ("PATCH", "/api/v1/cases/{case_id}"): Permission.MANAGE_CASES,
    ("GET", "/api/v1/cases/{case_id}/people"): V,
    ("POST", "/api/v1/cases/{case_id}/transition"): Permission.MANAGE_CASES,
    ("POST", "/api/v1/cases/{case_id}/alerts"): Permission.MANAGE_CASES,
    ("POST", "/api/v1/cases/{case_id}/activities"): Permission.WORK_ON_CASES,
    ("POST", "/api/v1/cases/{case_id}/actions/{action_id}/done"): Permission.WORK_ON_CASES,
    ("POST", "/api/v1/cases/{case_id}/attachments"): Permission.WORK_ON_CASES,
    ("GET", "/api/v1/cases/{case_id}/attachments/{attachment_id}"): V,
    ("POST", "/api/v1/cases/{case_id}/close"): Permission.WORK_ON_CASES,
    ("GET", "/api/v1/model-templates"): V,
    ("GET", "/api/v1/model-templates/{template_id}"): V,
    ("PUT", "/api/v1/model-templates"): Permission.MODELS,
    ("POST", "/api/v1/model-templates/{template_id}/apply"): Permission.MODELS,
    ("GET", "/api/v1/notifications/events"): V,
    ("GET", "/api/v1/notifications/subscriptions"): Permission.OWN_SUBSCRIPTIONS,
    ("POST", "/api/v1/notifications/subscriptions"): Permission.OWN_SUBSCRIPTIONS,
    ("PUT", "/api/v1/notifications/subscriptions/{subscription_id}"): (
        Permission.OWN_SUBSCRIPTIONS
    ),
    ("DELETE", "/api/v1/notifications/subscriptions/{subscription_id}"): (
        Permission.OWN_SUBSCRIPTIONS
    ),
    ("GET", "/api/v1/notifications/log"): Permission.ADMINISTRATION,
    ("POST", "/api/v1/notifications/test"): Permission.ADMINISTRATION,
    ("GET", "/api/v1/alerts/settings"): V,
    ("GET", "/api/v1/models/{model_id}/versions"): V,
    ("GET", "/api/v1/asset-types/{type_id}/roles"): V,
    ("GET", "/api/v1/models"): V,
    ("POST", "/api/v1/models"): Permission.MODELS,
    ("GET", "/api/v1/models/{model_id}"): V,
    ("GET", "/api/v1/models/{model_id}/scores"): V,
    ("GET", "/api/v1/models/{model_id}/outputs"): V,
    ("GET", "/api/v1/models/{model_id}/status-periods"): V,
    ("GET", "/api/v1/models/{model_id}/latest"): V,
    ("POST", "/api/v1/models/training-data"): Permission.MODELS,
    ("PUT", "/api/v1/models/{model_id}/alert-rules"): Permission.MODELS,
    ("POST", "/api/v1/models/{model_id}/versions"): Permission.MODELS,
    ("POST", "/api/v1/versions/{version_id}/{action}"): Permission.MODELS,
    ("GET", "/api/v1/alerts"): V,
    ("GET", "/api/v1/alerts/{alert_id}"): V,
    ("POST", "/api/v1/alerts/ack"): A,
    ("POST", "/api/v1/alerts/shelve"): A,
    ("POST", "/api/v1/alerts/unshelve"): A,
    ("POST", "/api/v1/alerts/{alert_id}/ack"): A,
    ("POST", "/api/v1/alerts/{alert_id}/shelve"): A,
    ("POST", "/api/v1/alerts/{alert_id}/unshelve"): A,
    ("GET", "/api/v1/priority-matrix"): V,
    ("PUT", "/api/v1/priority-matrix"): Permission.MODELS,  # decision 5.1
    ("GET", "/api/v1/fleet/kpis"): V,
    ("GET", "/api/v1/dq/rules"): V,
    ("POST", "/api/v1/dq/rules/preview"): V,
    ("PUT", "/api/v1/dq/rules"): Permission.DATA_QUALITY_RULES,
    ("GET", "/api/v1/users"): Permission.ADMINISTRATION,
    ("POST", "/api/v1/users"): Permission.ADMINISTRATION,
    ("PATCH", "/api/v1/users/{user_id}"): Permission.ADMINISTRATION,
    ("GET", "/api/v1/events"): V,
    ("POST", "/api/v1/ingest/samples"): "key",
    ("POST", "/api/v1/ingest/backfill"): Permission.REGISTRY,  # or an ingest key
    ("POST", "/api/v1/ingest/backfill/{upload_id}/load"): Permission.REGISTRY,
    ("GET", "/api/v1/jobs/{job_id}"): V,
}


@dataclass(frozen=True)
class Made:
    """A call the flow made as the signed-in user, to make again as other roles."""

    method: str
    url: str
    template: str
    kwargs: dict[str, Any]


class Recorder:
    """Calls the API, remembers which documented operation answered, and checks the body."""

    def __init__(self, client: TestClient, schema: dict[str, Any]) -> None:
        self.client, self.schema = client, schema
        self.called: set[tuple[str, str]] = set()
        self.made: list[Made] = []
        self.headers: dict[str, str] = {}

    def __call__(self, method: str, url: str, expect: int, **kwargs: Any) -> Any:
        own_headers = kwargs.pop("headers", {})
        headers = {**self.headers, **own_headers}
        response = self.client.request(method, url, headers=headers, **kwargs)
        assert response.status_code == expect, (method, url, response.text)
        template = self._template(method, url)
        self.called.add((method, template))
        self._check(method, template, response)
        if 200 <= expect < 300 and not own_headers and "Authorization" in self.headers:
            self.made.append(Made(method, url, template, dict(kwargs)))
        return response

    def _template(self, method: str, url: str) -> str:
        """The documented path that answers: literal segments win over parameters."""
        path = url.split("?")[0]
        candidates = [
            template
            for template, operations in self.schema["paths"].items()
            if method.lower() in operations
            and re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", template), path)
        ]
        assert candidates, f"No documented operation for {method} {url}"
        return str(min(candidates, key=lambda t: t.count("{")))

    def _check(self, method: str, template: str, response: Any) -> None:
        operation = self.schema["paths"][template][method.lower()]
        documented = operation["responses"].get(str(response.status_code))
        documented = documented or operation["responses"]["default"]
        content_type = response.headers.get("content-type", "").split(";")[0]
        if response.status_code == 204:
            assert not response.content, f"{method} {template}: 204 with a body"
            return
        if content_type not in ("application/json", "application/problem+json"):
            return
        body_schema = documented.get("content", {}).get(content_type, {}).get("schema")
        assert body_schema is not None, f"{method} {template} {response.status_code} undocumented"
        validator = Draft202012Validator({**body_schema, "components": self.schema["components"]})
        errors = sorted(validator.iter_errors(response.json()), key=str)
        assert not errors, f"{method} {template}: {errors[0].message}"


@pytest.fixture
def api(
    request: pytest.FixtureRequest, database_url: str, tmp_path: Path
) -> Iterator[tuple[Recorder, Database, Path]]:
    db: Database = request.getfixturevalue("deployed")
    with db.session() as s:
        s.execute(text("TRUNCATE app_user, api_key RESTART IDENTITY CASCADE"))
        s.execute(text("TRUNCATE unmapped_tag, ingest_source"))
        create_user(
            s,
            ACTOR,
            username="root",
            display_name="Root",
            password=PASSWORD,
            assignments=[RoleAssignment(Role.ADMINISTRATOR), RoleAssignment(Role.MODEL_ENGINEER)],
        )
    settings = Settings(
        database_url=database_url, secret_key="t", artefact_dir=tmp_path, _env_file=None
    )
    with TestClient(create_app(settings=settings, database=db), base_url="https://t") as client:
        schema = client.get("/api/v1/openapi.json").json()
        yield Recorder(client, schema), db, tmp_path


def test_the_document_is_valid_openapi_3_1(api: tuple[Recorder, Database, Path]) -> None:
    call, _, _ = api
    assert call.schema["openapi"].startswith("3.1")
    validate(call.schema)
    for path in call.schema["paths"].values():
        for operation in path.values():
            assert "422" not in operation["responses"]  # the API answers 400 (problem details)


def test_every_operation_is_exercised_and_matches_its_schema(
    api: tuple[Recorder, Database, Path],
) -> None:
    call, db, tmp_path = api
    v1 = "/api/v1"
    call("GET", "/healthz", 200)
    call("GET", "/readyz", 200)

    # sign in: cookie, then token (used from here on)
    login = call("POST", f"{v1}/auth/login", 200, json={"username": "root", "password": PASSWORD})
    csrf = login.json()["csrf_token"]
    token = call("POST", f"{v1}/auth/token", 200, json={"username": "root", "password": PASSWORD})
    call.client.cookies.clear()
    call.headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
    assert csrf
    call("GET", f"{v1}/auth/me", 200)
    call("GET", f"{v1}/assets", 401, headers={"Authorization": "Bearer nonsense"})

    # API keys and ingestion
    issued = call("POST", f"{v1}/api-keys", 201, json={"name": "gw", "scope": "ingest"}).json()
    rotated = call("POST", f"{v1}/api-keys/{issued['id']}/rotate", 201).json()
    call("POST", f"{v1}/api-keys/{issued['id']}/revoke", 204)
    call("GET", f"{v1}/api-keys", 200)
    key = {"Authorization": f"ApiKey {rotated['key']}"}
    now = datetime.now(UTC).replace(microsecond=0)
    batch = {
        "source": "gw-1",
        "samples": [
            {"tag": "EQ1.T1", "ts": now.isoformat(), "v": 100.0},
            {"tag": "EQ1.NEW", "ts": now.isoformat(), "v": 1.0},
        ],
    }
    call("POST", f"{v1}/ingest/samples", 202, json=batch, headers=key)
    csv = f"ts,tag,value\n{(now - timedelta(days=1)).isoformat()},EQ1.T1,99\n"
    upload = call(
        "POST",
        f"{v1}/ingest/backfill",
        202,
        headers=key,
        files={"file": ("h.csv", csv.encode(), "text/csv")},
        data={"source": "gw-1", "preview": "true"},
    ).json()
    queued = call(
        "POST",
        f"{v1}/ingest/backfill/{upload['upload_id']}/load",
        202,
        headers=key,
        json={"source": "gw-1"},
    ).json()
    registry = JobRegistry()
    registry.register(BACKFILL_JOB, make_backfill_handler(db, tmp_path / "uploads"))
    while Worker(db, registry, name="t").run_once():
        pass
    call("GET", f"{v1}/jobs/{queued['job_id']}", 200, headers=key)
    call("GET", f"{v1}/jobs/{queued['job_id']}", 200)  # as a user

    # registry
    call("GET", f"{v1}/asset-types", 200)
    pump = call("POST", f"{v1}/asset-types", 201, json={"code": "pump", "name": "Pump"}).json()
    call("POST", f"{v1}/asset-types/{pump['id']}/roles", 201, json={"code": "flow", "name": "Flow"})
    roles = call("GET", f"{v1}/asset-types/{pump['id']}/roles", 200).json()
    assert [r["code"] for r in roles] == ["flow"]
    mode = call(
        "PUT",
        f"{v1}/library",
        200,
        json={
            "asset_type": "pump",
            "code": "blockage",
            "name": "Blockage",
            "iso_code": "PLU",
            "symptoms": [{"role": "flow", "direction": "down", "weight": 1}],
            "tasks": ["Check the strainer"],
        },
    ).json()
    call("GET", f"{v1}/library", 200, params={"asset_type": "pump"})
    template = call(
        "PUT",
        f"{v1}/model-templates",
        200,
        json={
            "asset_type": "pump",
            "name": "standard",
            "definition": {
                "sensors": [{"role": "flow", "required": True}],
                "training_periods": [{"start": "-90d", "end": "-30d"}],
                "validation_period": {"start": "-30d", "end": "-10d"},
            },
        },
    ).json()
    call("PUT", f"{v1}/model-templates", 400, json={**template, "definition": {"sensors": []}})
    call("GET", f"{v1}/model-templates", 200, params={"asset_type": "pump"})
    call("GET", f"{v1}/model-templates/{template['id']}", 200)
    report = call(
        "POST", f"{v1}/model-templates/{template['id']}/apply", 200, json={"preview": True}
    ).json()
    assert report == []  # no pump in the registry yet
    call("GET", f"{v1}/library/{mode['id']}/versions", 200)
    call("POST", f"{v1}/library/{mode['id']}/retire", 200)
    site = call(
        "POST", f"{v1}/assets", 201, json={"code": "SITE-C", "name": "Site C", "level": "site"}
    ).json()
    call("POST", f"{v1}/assets", 409, json={"code": "SITE-C", "name": "x", "level": "site"})
    call("PATCH", f"{v1}/assets/{site['id']}", 200, json={"name": "Site C (new)"})
    call("GET", f"{v1}/assets/{site['id']}", 200)
    call("GET", f"{v1}/assets", 200, params={"tree": "true"})
    tag = call(
        "POST",
        f"{v1}/tags",
        201,
        json={
            "source": "gw-1",
            "source_name": "EQ1.T9",
            "asset": "EQ-1",
            "unit": "u",
            "range_lo": 0,
            "range_hi": 10,
            "interval_s": 60,
        },
    ).json()
    call("PATCH", f"{v1}/tags/{tag['id']}", 200, json={"unit": "bar"})
    call("GET", f"{v1}/tags", 200, params={"asset": "EQ-1"})
    with (DATA / "registry" / "registry.xlsx").open("rb") as workbook:
        call(
            "POST",
            f"{v1}/tags/import",
            200,
            params={"dry_run": "true"},
            files=[
                (
                    "files",
                    ("registry.xlsx", io.BytesIO(workbook.read()), "application/octet-stream"),
                )
            ],
        )
    call("GET", f"{v1}/unmapped-tags", 200)
    call(
        "POST",
        f"{v1}/unmapped-tags/promote",
        201,
        json={
            "source": "gw-1",
            "source_name": "EQ1.NEW",
            "asset": "EQ-1",
            "unit": "u",
            "range_lo": 0,
            "range_hi": 10,
            "interval_s": 60,
        },
    )
    call("GET", f"{v1}/sensors/health", 200, params={"scope": "EQ-1"})
    until = (datetime.now(UTC) + timedelta(hours=8)).isoformat()
    excluded = call(
        "POST",
        f"{v1}/sensors/{tag['id']}/exclusions",
        201,
        json={"kind": "exclude", "reason": "calibration", "until": until},
    ).json()
    call("GET", f"{v1}/sensor-exclusions", 200)
    call("POST", f"{v1}/sensor-exclusions/{excluded['id']}/end", 200)

    # models
    (model,) = call("GET", f"{v1}/models", 200).json()
    detail = call("GET", f"{v1}/models/{model['id']}", 200).json()
    period = {"from": LIVE.isoformat(), "to": (LIVE + timedelta(hours=1)).isoformat()}
    call("GET", f"{v1}/models/{model['id']}/scores", 200, params=period)
    call("GET", f"{v1}/models/{model['id']}/outputs", 200, params=period)
    call("GET", f"{v1}/models/{model['id']}/status-periods", 200, params=period)
    call("GET", f"{v1}/models/{model['id']}/latest", 200)
    call("GET", f"{v1}/models/{model['id']}/diagnostics", 200)
    assert call("GET", f"{v1}/models/{model['id']}/versions", 200).json() == detail["versions"]
    call("GET", f"{v1}/alerts/settings", 200)
    rules = {"di": {"warning": 15, "alert": 25}, "sensors": [{"tag": "EQ1.T1"}]}
    call("PUT", f"{v1}/models/{model['id']}/alert-rules", 200, json=rules)
    deployed_version = detail["in_service"]["id"]
    call("POST", f"{v1}/versions/{deployed_version}/pause", 200)
    call("POST", f"{v1}/versions/{deployed_version}/pause", 409)
    call("POST", f"{v1}/versions/{deployed_version}/resume", 200)
    definition = {
        "asset": "EQ-1",
        "name": "second",
        "algorithm": "median",  # the API is under test, not the algorithm
        "sensors": [{"tag": "EQ1.T1", "required": True}, "EQ1.T2"],
        "training_periods": [{"start": "2026-06-01T00:00Z", "end": "2026-06-04T00:00Z"}],
        "validation_period": {"start": "2026-06-04T00:00Z", "end": "2026-06-05T00:00Z"},
        "alert_rules": {"di": {"warning": 15, "alert": 25}},
    }
    call("POST", f"{v1}/models/training-data", 200, json=definition, params={"px": 20})
    second = call("POST", f"{v1}/models", 201, json=definition).json()
    call("POST", f"{v1}/models/{second['id']}/versions", 202)

    # alerts
    alert_id = _raise_one(db)
    call("GET", f"{v1}/alerts", 200)
    call("GET", f"{v1}/alerts/{alert_id}", 200)
    model_id = seed_di_ramp(db)
    forecast = call(
        "POST",
        f"{v1}/forecasts",
        201,
        json={
            "model_id": model_id,
            "threshold_kind": "custom",
            "threshold": 30,
            "alert_id": alert_id,
        },
    ).json()
    assert forecast["urgency"] == "High"
    assert forecast["alert_id"] == alert_id
    call("POST", f"{v1}/forecasts", 400, json={"model_id": model_id, "target": "actual"})
    call("GET", f"{v1}/forecasts", 200, params={"model_id": model_id})
    call("GET", f"{v1}/forecasts/{forecast['id']}", 200)
    listed = call("GET", f"{v1}/alerts", 200).json()["items"]
    assert {a["id"]: a["forecast_urgency"] for a in listed}[alert_id] == "High"

    # cases (8.4)
    case = call("POST", f"{v1}/cases", 201, json={"alert_ids": [alert_id]}).json()
    case_url = f"{v1}/cases/{case['id']}"
    call("POST", f"{v1}/cases", 409, json={"alert_ids": [alert_id]})
    call("GET", f"{v1}/cases", 200, params={"open_only": "true"})
    (me,) = call("GET", f"{case_url}/people", 200).json()
    call("PATCH", case_url, 200, json={"assignee_id": me["id"], "due": "2026-12-01"})
    call("POST", f"{case_url}/alerts", 200, json={"alert_ids": [alert_id]})
    call("POST", f"{case_url}/activities", 201, json={"type": "comment", "body": "Oil sample"})
    acting = call(
        "POST", f"{case_url}/activities", 201, json={"type": "action", "body": "Reduce load"}
    ).json()
    assert acting["status"] == "Action required"
    attached = call(
        "POST",
        f"{case_url}/attachments",
        201,
        files=[("file", ("oil.txt", io.BytesIO(b"iron 40 ppm"), "text/plain"))],
        data={"comment": "lab report"},
    ).json()
    download = call("GET", f"{case_url}/attachments/{attached['attachments'][0]['id']}", 200)
    assert download.content == b"iron 40 ppm"
    call("POST", f"{case_url}/actions/{acting['actions'][0]['id']}/done", 200)
    call("POST", f"{case_url}/transition", 409, json={"status": "Investigating"})
    call("POST", f"{case_url}/transition", 200, json={"status": "Action required"})
    call("POST", f"{case_url}/close", 400, json={"outcome": "true_finding"})
    closed = call("POST", f"{case_url}/close", 200, json={"outcome": "false_alert"}).json()
    assert closed["status"] == "Closed"
    assert closed["review_requested"]
    assert call("GET", case_url, 200).json()["snapshot"] == case["snapshot"]
    assert call("GET", f"{v1}/fleet/kpis", 200).json()["open_cases"] == 0

    # notifications (8.5)
    call("GET", f"{v1}/notifications/events", 200)
    sub = call(
        "POST",
        f"{v1}/notifications/subscriptions",
        201,
        json={"min_priority": "P1", "events": ["alert_raised"]},
    ).json()
    call("GET", f"{v1}/notifications/subscriptions", 200)
    changed = {"min_priority": "P2", "events": ["alert_raised", "case_assigned"]}
    call("PUT", f"{v1}/notifications/subscriptions/{sub['id']}", 200, json=changed)
    call("POST", f"{v1}/notifications/subscriptions", 400, json={"events": []})
    call("GET", f"{v1}/notifications/log", 200)
    call("POST", f"{v1}/notifications/test", 409, json={"to": "root@plant.test"})  # no relay
    call("DELETE", f"{v1}/notifications/subscriptions/{sub['id']}", 204)
    call("POST", f"{v1}/alerts/{alert_id}/ack", 200, json={"comment": "seen"})
    call("POST", f"{v1}/alerts/{alert_id}/shelve", 200, json={"reason": "work", "minutes": 30})
    call("POST", f"{v1}/alerts/{alert_id}/unshelve", 200)
    call("POST", f"{v1}/alerts/ack", 200, json={"ids": [alert_id]})
    call("POST", f"{v1}/alerts/shelve", 200, json={"ids": [alert_id], "reason": "w", "minutes": 5})
    call("POST", f"{v1}/alerts/unshelve", 200, json={"ids": [alert_id]})
    call("POST", f"{v1}/alerts/ack", 200, json={"ids": [alert_id]})
    call("POST", f"{v1}/alerts/ack", 409, json={"ids": [alert_id]})  # already acknowledged
    call("GET", f"{v1}/priority-matrix", 200)
    cell = {"criticality": "C", "severity": "Warning", "priority": "P4"}
    call("PUT", f"{v1}/priority-matrix", 200, json=cell)
    call("GET", f"{v1}/fleet/kpis", 200)
    stream = call("GET", f"{v1}/events", 200, params={"timeout_s": 0.5})
    assert stream.headers["content-type"].startswith("text/event-stream")

    # data quality
    call("GET", f"{v1}/dq/rules", 200, params={"scope": "global"})
    change = {"scope": "global", "overrides": {"spike_pct": 30}, "days": 1, "confirm": True}
    call("POST", f"{v1}/dq/rules/preview", 200, json=change)
    call("PUT", f"{v1}/dq/rules", 200, json=change)

    # users and audit
    new = call(
        "POST",
        f"{v1}/users",
        201,
        json={"username": "vera", "password": PASSWORD, "roles": [{"role": "viewer"}]},
    ).json()
    call("PATCH", f"{v1}/users/{new['id']}", 200, json={"roles": [{"role": "analyst"}]})
    call("GET", f"{v1}/users", 200)
    call("GET", f"{v1}/audit", 200, params={"entity": "user"})
    call("GET", f"{v1}/audit.csv", 200)
    call("GET", f"{v1}/retention", 200)
    call("PUT", f"{v1}/retention", 200, json={"raw_months": 24, "aggregate_months": 60})
    call("PUT", f"{v1}/retention", 400, json={"raw_months": 24, "aggregate_months": 12})

    # every role the matrix refuses gets 403 for every call made above (AC-07)
    tokens = {}
    with db.session() as s:
        for role in Role:
            create_user(
                s,
                ACTOR,
                username=f"as-{role.value}",
                display_name=role.value,
                password=PASSWORD,
                assignments=[RoleAssignment(role)],
            )
    for role in Role:
        answer = call.client.post(
            f"{v1}/auth/token", json={"username": f"as-{role.value}", "password": PASSWORD}
        )
        tokens[role] = {"Authorization": f"Bearer {answer.json()['access_token']}"}
    refused = 0
    for made in call.made:
        needed = PERMISSIONS[(made.method, made.template)]
        if not isinstance(needed, Permission) or needed is Permission.VIEW:
            continue
        for role in Role:
            if role in MATRIX[needed]:
                continue
            response = call.client.request(
                made.method, made.url, headers=tokens[role], **made.kwargs
            )
            assert response.status_code == 403, (role, made.method, made.url, response.text)
            refused += 1
    assert refused > 50

    # own password, then sign out
    change_pw = {"current_password": PASSWORD, "new_password": "another long passphrase"}
    call("POST", f"{v1}/auth/password", 204, json=change_pw)
    call("POST", f"{v1}/auth/logout", 204)

    documented = {
        (method.upper(), path)
        for path, operations in call.schema["paths"].items()
        for method in operations
    }
    assert documented - call.called == set(), "documented but never called"
    assert documented == set(PERMISSIONS), "classify every operation by its permission"
    assert call.called - documented == set()
