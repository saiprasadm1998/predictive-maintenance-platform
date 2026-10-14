"""Command line: pmp web | worker | migrate."""

from __future__ import annotations

from typing import Any

import pytest

from pmp import cli
from pmp.core import get_settings


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PMP_DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    monkeypatch.setenv("PMP_SECRET_KEY", "k")
    monkeypatch.setenv("PMP_LOG_FORMAT", "text")
    get_settings.cache_clear()


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main([])
    assert exit_info.value.code == 2


def test_unknown_command_is_rejected() -> None:
    with pytest.raises(SystemExit):
        cli.main(["backup"])


def test_migrate_runs_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli, "run_migrations", calls.append)

    cli.main(["migrate"])

    assert calls == ["postgresql+psycopg://u:p@localhost/db"]


def test_web_migrates_then_serves(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    served: dict[str, Any] = {}
    monkeypatch.setattr(cli, "run_migrations", lambda url: order.append("migrate"))

    def fake_run(app: object, **kwargs: Any) -> None:
        order.append("serve")
        served.update(kwargs)

    monkeypatch.setattr("pmp.cli.uvicorn.run", fake_run)

    cli.main(["web", "--port", "9000"])

    assert order == ["migrate", "serve"]
    assert served["port"] == 9000
    assert served["host"] == "127.0.0.1"


def test_web_can_skip_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    monkeypatch.setattr(cli, "run_migrations", lambda url: order.append("migrate"))
    monkeypatch.setattr("pmp.cli.uvicorn.run", lambda app, **kwargs: order.append("serve"))

    cli.main(["web", "--no-migrate"])

    assert order == ["serve"]
