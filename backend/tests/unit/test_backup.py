"""Backup retention and scheduling (plan 9.1, ARC §10.1: 14 daily and 8 weekly copies)."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from pmp.core import seconds_until, to_keep
from pmp.core.backup import STAMP_FORMAT, libpq_env, prune, stamp_of

NOW = datetime(2026, 10, 30, 2, 30, tzinfo=UTC)  # a Friday


def test_keeps_14_daily_and_8_weekly_copies() -> None:
    nightly = [NOW - timedelta(days=d) for d in range(120)]
    kept = to_keep(nightly, NOW, daily=14, weekly=8)
    days = sorted(NOW - s for s in kept)
    assert days[:14] == [timedelta(days=d) for d in range(14)]  # the last 14 nights
    older = days[14:]  # the newest of each earlier week (Sundays), back to 8 weeks
    assert [d.days for d in older] == [19, 26, 33, 40, 47]
    assert all((NOW - d).isoweekday() == 7 for d in older)
    assert len(kept) == 19


def test_only_the_newest_copy_of_a_day_counts() -> None:
    twice = [NOW, NOW - timedelta(hours=1), NOW - timedelta(days=1)]
    assert to_keep(twice, NOW, daily=14, weekly=0) == {NOW, NOW - timedelta(days=1)}


def test_prune_deletes_both_files_of_an_old_copy_and_nothing_else(tmp_path: Path) -> None:
    for days in (0, 1, 60):
        name = f"pmp-{(NOW - timedelta(days=days)).strftime(STAMP_FORMAT)}"
        (tmp_path / f"{name}.dump").write_bytes(b"x")
        (tmp_path / f"{name}-artefacts.tar.gz").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("kept")
    removed = prune(tmp_path, NOW, daily=14, weekly=8)
    assert sorted(removed) == [
        "pmp-20260831T023000Z-artefacts.tar.gz",
        "pmp-20260831T023000Z.dump",
    ]
    assert len(list(tmp_path.iterdir())) == 5
    assert stamp_of("pmp-20261030T023000Z.dump") == NOW
    assert stamp_of("pmp-20261030T023000Z.dump.partial") is None  # unfinished copies


def test_the_next_nightly_run() -> None:
    assert seconds_until(time(2, 30), NOW - timedelta(minutes=5)) == 300
    assert seconds_until(time(2, 30), NOW) == 24 * 3600  # just done: tomorrow


def test_the_password_goes_in_the_environment_not_the_command_line() -> None:
    env = libpq_env("postgresql+psycopg://pmp:s3cret@db:5432/pmp?sslmode=require")
    assert env == {
        "PGHOST": "db",
        "PGPORT": "5432",
        "PGUSER": "pmp",
        "PGDATABASE": "pmp",
        "PGPASSWORD": "s3cret",
        "PGSSLMODE": "require",
    }
