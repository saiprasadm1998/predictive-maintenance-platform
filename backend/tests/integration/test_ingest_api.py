"""POST /api/v1/ingest/samples end to end (ARC §7.1.1, FR-ING-01, FR-SEC-02, NFR-PERF-04)."""

from __future__ import annotations

import gzip
import json
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pmp.api import create_app
from pmp.core import Actor, ApiKeyScope, Database, Settings, issue_api_key, revoke_api_key
from pmp.ingestion import count_samples, server_now
from pmp.registry import AssetLevel, AssetSpec, Criticality, TagSpec, upsert_asset, upsert_tag

pytestmark = pytest.mark.integration
ACTOR = Actor.system()
SOURCE = "gw-site-a-01"
URL = "/api/v1/ingest/samples"


@pytest.fixture
def setup(clean_ingestion: Database, database_url: str) -> dict[str, Any]:
    db = clean_ingestion
    with db.session() as s:
        upsert_asset(s, ACTOR, AssetSpec("SITE-A", "Site A", AssetLevel.SITE))
        upsert_asset(
            s, ACTOR, AssetSpec("K-101", "K-101", AssetLevel.EQUIPMENT, "SITE-A", Criticality.A)
        )
        for name in ("K101.TI1012.PV", "K101.ZI1015.PV"):
            upsert_tag(s, ACTOR, TagSpec(SOURCE, name, "K-101", "°C", 0, 150, 60))
        ingest_key = issue_api_key(s, ACTOR, name="Site A gateway", scope=ApiKeyScope.INGEST)
        read_key = issue_api_key(s, ACTOR, name="Reader", scope=ApiKeyScope.RESULTS_READ)
        now = server_now(s).replace(microsecond=0)
    return {"db": db, "url": database_url, "ingest": ingest_key, "read": read_key, "now": now}


def _client(setup: dict[str, Any], rate: float = 1000.0) -> TestClient:
    settings = Settings(
        database_url=setup["url"], secret_key="test", ingest_rate_limit=rate, _env_file=None
    )
    return TestClient(create_app(settings=settings, database=setup["db"]))


@pytest.fixture
def client(setup: dict[str, Any]) -> Iterator[TestClient]:
    with _client(setup) as c:
        yield c


def _auth(key: str) -> dict[str, str]:
    return {"Authorization": f"ApiKey {key}"}


def _arc_batch(now: datetime) -> dict[str, Any]:
    ts = now.isoformat()
    return {
        "source": SOURCE,
        "samples": [
            {"tag": "K101.TI1012.PV", "ts": ts, "v": 78.42, "q": 0},
            {"tag": "K101.ZI1015.PV", "ts": ts, "v": 412.0, "q": "Good"},
            {"tag": "K101.TI1018.PV", "ts": ts, "v": 69.0, "q": "Bad"},
        ],
    }


def _count(setup: dict[str, Any]) -> int:
    with setup["db"].session() as s:
        return count_samples(s)


def test_arc_example_over_http(setup: dict[str, Any], client: TestClient) -> None:
    response = client.post(URL, json=_arc_batch(setup["now"]), headers=_auth(setup["ingest"].key))
    assert response.status_code == 202
    assert response.json() == {
        "accepted": 2,
        "rejected": [{"index": 2, "reason": "unregistered_tag"}],
    }


def test_missing_key_is_401_problem_json(setup: dict[str, Any], client: TestClient) -> None:
    response = client.post(URL, json=_arc_batch(setup["now"]))
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "unauthorized"
    assert _count(setup) == 0


@pytest.mark.parametrize("key", ["pmp_000000000000_wrong", "not-a-key"])
def test_invalid_key_is_401(setup: dict[str, Any], client: TestClient, key: str) -> None:
    response = client.post(URL, json=_arc_batch(setup["now"]), headers=_auth(key))
    assert response.status_code == 401


def test_revoked_key_is_401(setup: dict[str, Any], client: TestClient) -> None:
    with setup["db"].session() as s:
        revoke_api_key(s, ACTOR, setup["ingest"].id)
    response = client.post(URL, json=_arc_batch(setup["now"]), headers=_auth(setup["ingest"].key))
    assert response.status_code == 401


def test_results_read_key_cannot_ingest(setup: dict[str, Any], client: TestClient) -> None:
    response = client.post(URL, json=_arc_batch(setup["now"]), headers=_auth(setup["read"].key))
    assert response.status_code == 403
    assert _count(setup) == 0


def test_schema_error_is_400_and_stores_nothing(setup: dict[str, Any], client: TestClient) -> None:
    batch = _arc_batch(setup["now"])
    batch["samples"][1]["ts"] = "2026-10-15T10:00:00"  # no offset
    response = client.post(URL, json=batch, headers=_auth(setup["ingest"].key))
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_payload"
    assert response.json()["errors"][0]["location"].startswith("samples.1")
    assert _count(setup) == 0


def test_invalid_json_is_400(setup: dict[str, Any], client: TestClient) -> None:
    response = client.post(
        URL,
        content=b"{not json",
        headers={**_auth(setup["ingest"].key), "Content-Type": "application/json"},
    )
    assert response.status_code == 400


def test_more_than_10000_samples_is_413(setup: dict[str, Any], client: TestClient) -> None:
    sample = {"tag": "K101.TI1012.PV", "ts": setup["now"].isoformat(), "v": 1.0}
    batch = {"source": SOURCE, "samples": [sample] * 10_001}
    response = client.post(URL, json=batch, headers=_auth(setup["ingest"].key))
    assert response.status_code == 413
    assert _count(setup) == 0


def test_body_over_5_mb_is_413(setup: dict[str, Any], client: TestClient) -> None:
    body = b'{"source": "' + b"x" * (5 * 1024 * 1024) + b'", "samples": []}'
    response = client.post(
        URL,
        content=body,
        headers={**_auth(setup["ingest"].key), "Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_gzip_bodies_are_accepted(setup: dict[str, Any], client: TestClient) -> None:
    body = gzip.compress(json.dumps(_arc_batch(setup["now"])).encode())
    response = client.post(
        URL,
        content=body,
        headers={
            **_auth(setup["ingest"].key),
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
        },
    )
    assert response.status_code == 202
    assert response.json()["accepted"] == 2


def test_rate_limit_is_429_with_retry_after(setup: dict[str, Any]) -> None:
    with _client(setup, rate=1.0) as client:
        headers = _auth(setup["ingest"].key)
        first = client.post(URL, json=_arc_batch(setup["now"]), headers=headers)
        second = client.post(URL, json=_arc_batch(setup["now"]), headers=headers)
    assert first.status_code == 202
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1


def test_10000_samples_accepted_and_queryable_within_5_s(
    setup: dict[str, Any], client: TestClient
) -> None:
    now: datetime = setup["now"]
    samples = [
        {"tag": "K101.TI1012.PV", "ts": (now - timedelta(seconds=i)).isoformat(), "v": float(i)}
        for i in range(10_000)
    ]
    started = time.monotonic()
    response = client.post(
        URL, json={"source": SOURCE, "samples": samples}, headers=_auth(setup["ingest"].key)
    )
    count = _count(setup)
    elapsed = time.monotonic() - started

    assert response.status_code == 202
    assert response.json() == {"accepted": 10_000, "rejected": []}
    assert count == 10_000
    assert elapsed < 5.0, f"took {elapsed:.2f} s"


def test_openapi_documents_the_ingest_endpoint(client: TestClient) -> None:
    spec = client.get("/api/v1/openapi.json").json()
    operation = spec["paths"][URL]["post"]
    assert "202" in operation["responses"]
    assert "requestBody" in operation
