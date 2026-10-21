"""The web role serves the built front end (plan 6.1): deep links open the app, hashed
assets are cached for good, and the API keeps its problem+json 404."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pmp.api import create_app
from pmp.core import Settings


def settings(frontend: Path | None) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://x:y@localhost:1/z",  # never connected here
        secret_key="k",
        frontend_dir=frontend,
    )


@pytest.fixture
def build(tmp_path: Path) -> Path:
    (tmp_path / "static").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>PMP</title>")
    (tmp_path / "static" / "index-abc123.js").write_text("console.log(1)")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    return tmp_path


def test_deep_links_get_the_app_and_assets_are_immutable(build: Path) -> None:
    client = TestClient(create_app(settings=settings(build)))
    page = client.get("/assets/6/diagnostics?range=24h")
    assert page.status_code == 200
    assert "<title>PMP</title>" in page.text
    assert page.headers["cache-control"] == "no-cache"
    assert client.get("/").text == page.text

    script = client.get("/static/index-abc123.js")
    assert script.status_code == 200
    assert "immutable" in script.headers["cache-control"]
    assert client.get("/favicon.svg").text == "<svg/>"
    assert client.get("/static/missing.js").status_code == 404


def test_api_and_operations_are_not_swallowed(build: Path) -> None:
    client = TestClient(create_app(settings=settings(build)))
    missing = client.get("/api/v1/nothing-here")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/../backend/pyproject.toml").text.startswith("<!doctype html>")
    assert "/{path}" not in client.get("/api/v1/openapi.json").json()["paths"]


def test_without_a_build_only_the_api_is_served(tmp_path: Path) -> None:
    client = TestClient(create_app(settings=settings(tmp_path)))
    assert client.get("/fleet").status_code == 404
    client = TestClient(create_app(settings=settings(None)))
    assert client.get("/fleet").status_code == 404
