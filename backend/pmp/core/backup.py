"""Backup and restore (plan 9.1, ARC §10.1, NFR-REL-03: RPO 24 h, RTO 4 h).

`pmp backup` writes, under one time stamp, a pg_dump of the database in custom format and
a gzip tar of the model artefacts, then keeps the newest copy of each of the last 14 days
and of each of the last 8 ISO weeks and deletes the rest. Files are written under a
temporary name and renamed when complete, so a half-written copy never counts. Every run
is recorded in `backup_run` (its failure is an operational alert, ARC §10.3).

`pmp restore` loads a dump into an empty database (TimescaleDB's pre- and post-restore
steps when the extension is available) and unpacks the artefacts. It refuses a database
that already has tables, so a live system is never overwritten by mistake.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tarfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Mapped, Session, mapped_column

from pmp.core.db import Base, Database

logger = logging.getLogger(__name__)

STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_NAME = re.compile(r"^pmp-(\d{8}T\d{6}Z)(\.dump|-artefacts\.tar\.gz)$")


class BackupError(Exception):
    """A backup or restore that could not be done (the message says why)."""


class BackupRunRow(Base):
    __tablename__ = "backup_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(100))
    dump_bytes: Mapped[int | None] = mapped_column(BigInteger)
    artefact_bytes: Mapped[int | None] = mapped_column(BigInteger)
    removed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


@dataclass(frozen=True)
class BackupResult:
    name: str  # "pmp-20261030T023000Z"
    dump: Path
    artefacts: Path
    removed: list[str]


# ------------------------------------------------------------------ retention (pure)


def stamp_of(name: str) -> datetime | None:
    match = _NAME.match(name)
    if match is None:
        return None
    return datetime.strptime(match.group(1), STAMP_FORMAT).replace(tzinfo=UTC)


def _week(at: datetime) -> tuple[int, int]:
    iso = at.isocalendar()
    return iso.year, iso.week


def to_keep(stamps: Iterable[datetime], now: datetime, daily: int, weekly: int) -> set[datetime]:
    """The newest copy of each of the last `daily` days and of each of the last `weekly`
    ISO weeks (counting today and this week)."""
    newest_day: dict[date, datetime] = {}
    newest_week: dict[tuple[int, int], datetime] = {}
    for stamp in stamps:
        day = stamp.date()
        week = _week(stamp)
        newest_day[day] = max(newest_day.get(day, stamp), stamp)
        newest_week[week] = max(newest_week.get(week, stamp), stamp)
    first_day = now.date() - timedelta(days=daily - 1)
    keep = {s for d, s in newest_day.items() if d >= first_day}
    weeks = {_week(now - timedelta(weeks=i)) for i in range(weekly)}
    keep |= {s for w, s in newest_week.items() if w in weeks}
    return keep


def seconds_until(at: time, now: datetime) -> float:
    """Seconds from `now` to the next `at` (UTC), for the nightly schedule."""
    target = datetime.combine(now.date(), at, tzinfo=UTC)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


# ------------------------------------------------------------------ PostgreSQL tools


def libpq_env(database_url: str) -> dict[str, str]:
    """PG* variables for pg_dump and pg_restore, so the password is never on a command
    line (where `ps` would show it)."""
    url = make_url(database_url)
    env = {
        "PGHOST": url.host or "localhost",
        "PGPORT": str(url.port or 5432),
        "PGUSER": url.username or "",
        "PGDATABASE": url.database or "",
    }
    if url.password:
        env["PGPASSWORD"] = str(url.password)
    for key, value in url.query.items():  # e.g. sslmode=require
        if key in {"sslmode", "host"} and isinstance(value, str):
            env["PGSSLMODE" if key == "sslmode" else "PGHOST"] = value
    return env


def _run(command: list[str], database_url: str) -> None:
    if shutil.which(command[0]) is None:
        raise BackupError(f"{command[0]} is not installed (PostgreSQL 16 client tools)")
    done = subprocess.run(
        command,
        env={**os.environ, **libpq_env(database_url)},
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise BackupError(f"{command[0]} failed: {done.stderr.strip()[-2000:]}")


# ------------------------------------------------------------------ backup


def run_backup(
    database: Database,
    database_url: str,
    artefact_dir: Path,
    target_dir: Path,
    *,
    keep_daily: int = 14,
    keep_weekly: int = 8,
    now: datetime | None = None,
) -> BackupResult:
    """One backup (see the module docstring). Raises BackupError on failure, after
    recording it."""
    now = now or datetime.now(UTC)
    name = f"pmp-{now.strftime(STAMP_FORMAT)}"
    with database.session() as session:
        row = BackupRunRow(started_at=now, status="running", name=name, removed=0)
        session.add(row)
        session.flush()
        run_id = row.id
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        dump = target_dir / f"{name}.dump"
        archive = target_dir / f"{name}-artefacts.tar.gz"
        partial_dump = dump.with_suffix(".dump.partial")
        _run(["pg_dump", "--format=custom", "--file", str(partial_dump)], database_url)
        partial_dump.rename(dump)
        partial_archive = target_dir / f"{name}-artefacts.tar.gz.partial"
        with tarfile.open(partial_archive, "w:gz") as tar:
            if artefact_dir.exists():
                tar.add(artefact_dir, arcname="artefacts")
        partial_archive.rename(archive)
        removed = prune(target_dir, now, keep_daily, keep_weekly)
    except Exception as error:
        for leftover in target_dir.glob(f"{name}*.partial"):
            leftover.unlink()
        message = f"{type(error).__name__}: {error}"
        with database.session() as session:
            failed = session.get(BackupRunRow, run_id)
            if failed is not None:
                failed.status, failed.error = "failed", message
                failed.finished_at = datetime.now(UTC)
        logger.error("Backup %s failed: %s", name, message)
        if isinstance(error, BackupError):
            raise
        raise BackupError(message) from error
    with database.session() as session:
        done = session.get(BackupRunRow, run_id)
        if done is not None:
            done.status, done.finished_at = "succeeded", datetime.now(UTC)
            done.dump_bytes, done.artefact_bytes = dump.stat().st_size, archive.stat().st_size
            done.removed = len(removed)
    logger.info("Backup %s written to %s; %d old files removed", name, target_dir, len(removed))
    return BackupResult(name, dump, archive, removed)


def prune(target_dir: Path, now: datetime, daily: int, weekly: int) -> list[str]:
    """Delete the copies `to_keep` does not keep (both files of a copy go together)."""
    files: dict[datetime, list[Path]] = {}
    for path in target_dir.iterdir():
        stamp = stamp_of(path.name)
        if stamp is not None:
            files.setdefault(stamp, []).append(path)
    keep = to_keep(files, now, daily, weekly)
    removed = []
    for stamp, paths in sorted(files.items()):
        if stamp in keep:
            continue
        for path in paths:
            path.unlink()
            removed.append(path.name)
    return removed


@dataclass(frozen=True)
class BackupRunView:
    started_at: datetime
    finished_at: datetime | None
    status: str
    name: str
    error: str | None


def last_backup(session: Session) -> BackupRunView | None:
    row = session.scalars(select(BackupRunRow).order_by(BackupRunRow.id.desc()).limit(1)).first()
    if row is None:
        return None
    return BackupRunView(row.started_at, row.finished_at, row.status, row.name, row.error)


# ------------------------------------------------------------------ restore


def _table_count(database_url: str) -> int:
    probe = Database(database_url)
    try:
        with probe.session() as session:
            return int(
                session.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                ).scalar_one()
            )
    finally:
        probe.dispose()


def _timescale(database_url: str, statement: str) -> bool:
    """Run a TimescaleDB restore step if the extension is installed on the server."""
    probe = Database(database_url)
    try:
        with probe.session() as session:
            available = session.execute(
                text("SELECT count(*) FROM pg_available_extensions WHERE name = 'timescaledb'")
            ).scalar_one()
            if not available:
                return False
            session.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
            function = statement.removeprefix("SELECT ").removesuffix("()")
            found = session.execute(
                text("SELECT count(*) FROM pg_proc WHERE proname = :f"), {"f": function}
            ).scalar_one()
            if not found:  # a build without the restore functions
                return False
            session.execute(text(statement))
            return True
    finally:
        probe.dispose()


def restore(
    database_url: str, dump: Path, artefacts: Path | None, artefact_dir: Path
) -> Mapping[str, object]:
    """Load `dump` into the (empty) database and unpack `artefacts` into `artefact_dir`."""
    if not dump.is_file():
        raise BackupError(f"No such dump: {dump}")
    if artefacts is not None and not artefacts.is_file():
        raise BackupError(f"No such artefact archive: {artefacts}")
    if _table_count(database_url):
        raise BackupError(
            "The database is not empty: restore only into a new, empty database "
            "(create one, point PMP_DATABASE_URL at it, then restore)"
        )
    timescale = _timescale(database_url, "SELECT timescaledb_pre_restore()")
    try:
        _run(
            [
                "pg_restore",
                "--no-owner",
                "--no-privileges",
                "--dbname",
                libpq_env(database_url)["PGDATABASE"],
                str(dump),
            ],
            database_url,
        )
    finally:
        if timescale:
            _timescale(database_url, "SELECT timescaledb_post_restore()")
    unpacked = 0
    if artefacts is not None:
        artefact_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(artefacts, "r:gz") as tar:
            members = [m for m in tar.getmembers() if m.name.startswith("artefacts")]
            for member in members:
                member.name = member.name.removeprefix("artefacts").lstrip("/")
                if not member.name:
                    continue
                tar.extract(member, artefact_dir, filter="data")
                unpacked += 1
    return {"tables": _table_count(database_url), "artefact_files": unpacked}
