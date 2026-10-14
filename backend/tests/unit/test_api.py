"""Web role basics: liveness and request IDs."""

from __future__ import annotations

from fastapi.testclient import TestClient

from pmp.api import create_app


def test_healthz_returns_ok() -> None:
    response = TestClient(create_app()).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_every_response_carries_a_request_id() -> None:
    response = TestClient(create_app()).get("/healthz")
    assert len(response.headers["X-Request-ID"]) == 32


def test_a_valid_supplied_request_id_is_kept() -> None:
    response = TestClient(create_app()).get("/healthz", headers={"X-Request-ID": "gw-abc.123"})
    assert response.headers["X-Request-ID"] == "gw-abc.123"


def test_an_unsafe_supplied_request_id_is_replaced() -> None:
    response = TestClient(create_app()).get(
        "/healthz", headers={"X-Request-ID": "bad id\nwith newline"}
    )
    assert response.headers["X-Request-ID"] != "bad id\nwith newline"


def test_openapi_document_is_published_under_api_v1() -> None:
    response = TestClient(create_app()).get("/api/v1/openapi.json")
    assert response.status_code == 200
    assert response.json()["openapi"].startswith("3.1")
