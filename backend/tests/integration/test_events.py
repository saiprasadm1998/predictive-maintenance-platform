"""The live event stream over a real HTTP server (plan 5.3; FR-VIS-03, NFR-PERF-02,
ARC §7.4)."""

from __future__ import annotations

import contextlib
import json
import socket
import threading
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx2
import pytest
import uvicorn
from sqlalchemy import text

from pmp.api import create_app, events
from pmp.core import (
    Database,
    Role,
    RoleAssignment,
    Settings,
    claim,
    complete,
    create_user,
    enqueue,
    set_active,
)
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


class Stream:
    """Reads one SSE stream in the background, keeping each event with its arrival time."""

    def __init__(self, base: str, token: str, timeout_s: float = 8) -> None:
        self.events: list[tuple[float, dict[str, Any]]] = []
        self.connected = threading.Event()
        self._thread = threading.Thread(
            target=self._read, args=(base, token, timeout_s), daemon=True
        )
        self._thread.start()
        assert self.connected.wait(10), "stream did not open"

    def _read(self, base: str, token: str, timeout_s: float) -> None:
        with contextlib.suppress(httpx2.HTTPError):  # the server stopped mid-stream
            self._consume(base, token, timeout_s)

    def _consume(self, base: str, token: str, timeout_s: float) -> None:
        headers = {"Authorization": f"Bearer {token}"}
        with (
            httpx2.Client(timeout=timeout_s + 5) as client,
            client.stream(
                "GET", f"{base}/api/v1/events", params={"timeout_s": timeout_s}, headers=headers
            ) as response,
        ):
            assert response.headers["content-type"].startswith("text/event-stream")
            for line in response.iter_lines():
                if line.startswith(": connected"):
                    self.connected.set()
                if line.startswith("data: "):
                    self.events.append((time.monotonic(), json.loads(line[6:])))

    def wait_for(self, kind: str, seconds: float = 10) -> tuple[float, dict[str, Any]] | None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for arrived, event in self.events:
                if event.get("type") == kind:
                    return arrived, event
            time.sleep(0.05)
        return None

    def types(self) -> list[str]:
        return [e["type"] for _, e in self.events]


@pytest.fixture
def server(
    request: pytest.FixtureRequest, database_url: str, tmp_path: Path
) -> Iterator[dict[str, Any]]:
    db: Database = request.getfixturevalue("deployed")
    with db.session() as s:
        s.execute(text("TRUNCATE app_user RESTART IDENTITY CASCADE"))
        upsert_asset(s, ACTOR, AssetSpec("SITE-Z", "Elsewhere", AssetLevel.SITE))
        site_z = find_asset(s, "SITE-Z")
        assert site_z is not None
        for name, scope in (("vera", None), ("zed", site_z.id)):
            create_user(
                s,
                ACTOR,
                username=name,
                display_name=name,
                password=PASSWORD,
                assignments=[RoleAssignment(Role.VIEWER, scope)],
            )
    settings = Settings(
        database_url=database_url, secret_key="t", artefact_dir=tmp_path, _env_file=None
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = uvicorn.Config(
        create_app(settings=settings, database=db),
        host="127.0.0.1",
        port=port,
        log_level="warning",
        timeout_graceful_shutdown=1,
    )
    web = uvicorn.Server(config)
    thread = threading.Thread(target=web.run, daemon=True)
    thread.start()
    while not web.started:
        time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    tokens = {
        name: httpx2.post(
            f"{base}/api/v1/auth/token", json={"username": name, "password": PASSWORD}
        ).json()["access_token"]
        for name in ("vera", "zed")
    }
    yield {"base": base, "tokens": tokens, "db": db}
    web.should_exit = True
    thread.join(10)


def test_scores_arrive_within_seconds_and_only_in_scope(
    server: dict[str, Any],
) -> None:
    """NFR-PERF-02: a new score reaches the browser within one cycle plus 5 s of the
    sample; the cycle and its grace are the scheduler's, so the stream itself must deliver
    within seconds of the commit."""
    vera = Stream(server["base"], server["tokens"]["vera"])
    zed = Stream(server["base"], server["tokens"]["zed"])
    time.sleep(0.5)  # both listening
    scheduler = Scheduler(server["db"], clock=Clock(LIVE + timedelta(minutes=1, seconds=30)))
    committed = time.monotonic()
    scheduler.tick()
    got = vera.wait_for("score.updated")
    assert got is not None, vera.types()
    arrived, event = got
    assert arrived - committed < 5.0
    assert event["status"] == "Running"
    assert event["model_id"] == 1
    time.sleep(0.5)
    assert "score.updated" not in zed.types()  # SITE-Z only: not this model


def test_job_progress_is_announced(server: dict[str, Any]) -> None:
    vera = Stream(server["base"], server["tokens"]["vera"])
    time.sleep(0.3)
    db = server["db"]
    with db.session() as s:
        s.execute(text("TRUNCATE job RESTART IDENTITY"))
        job_id = enqueue(s, "model.train")
    with db.session() as s:
        claim(s, "w")
    with db.session() as s:
        complete(s, job_id, {"ok": True})
    got = vera.wait_for("job.progress")
    assert got is not None
    assert got[1]["status"] == "succeeded"
    assert got[1]["percent"] == 100.0


def test_the_stream_ends_with_the_session(
    server: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(events, "RECHECK_S", 0.3)
    vera = Stream(server["base"], server["tokens"]["vera"])
    with server["db"].session() as s:
        set_active(s, ACTOR, "vera", False)
    assert vera.wait_for("session.ended", 5) is not None
