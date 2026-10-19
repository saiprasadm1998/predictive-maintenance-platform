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


def test_registry_import_runs_and_exits_with_the_report_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from contextlib import contextmanager
    from pathlib import Path

    from pmp.registry import ImportReport

    calls: dict[str, Any] = {}

    class FakeDatabase:
        def __init__(self, url: str) -> None:
            calls["url"] = url

        @contextmanager
        def session(self) -> Any:
            yield "session"

        def dispose(self) -> None:
            calls["disposed"] = True

    def fake_import(session: Any, actor: Any, paths: Any, *, dry_run: bool) -> ImportReport:
        calls.update(session=session, paths=list(paths), dry_run=dry_run)
        return ImportReport()

    monkeypatch.setattr(cli, "Database", FakeDatabase)
    monkeypatch.setattr(cli, "import_files", fake_import)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["registry", "import", "plant.xlsx", "--dry-run"])

    assert exit_info.value.code == 0
    assert calls["paths"] == [Path("plant.xlsx")]
    assert calls["dry_run"] is True
    assert calls["disposed"] is True
    assert "valid (dry run)" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["demo", "replay", "--key", "k", "--from", "-2h"], "--from=-2h"),
        (["dq", "status", "--at", "-30m"], "--at=-30m"),
    ],
)
def test_relative_times_after_an_option_are_not_read_as_options(
    argv: list[str], expected: str
) -> None:
    fixed = cli._attach_relative_times(argv)
    assert expected in fixed
    args = cli.build_parser().parse_args(fixed)
    assert (args.start if argv[0] == "demo" else args.at) is not None


def test_dq_commands_parse() -> None:
    args = cli.build_parser().parse_args(
        ["dq", "set", "--tag", "K101.SI1001.PV", "flatline_used=on", "--comment", "why", "--yes"]
    )
    assert (args.dq_command, args.tag, args.params, args.yes) == (
        "set",
        "K101.SI1001.PV",
        ["flatline_used=on"],
        True,
    )
