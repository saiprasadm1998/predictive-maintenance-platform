"""Monitoring (plan 9.1, ARC §10.3, NFR-REL-03).

GET /metrics               Prometheus text format. Not authenticated: the reverse proxy
                           does not pass it on, so only the internal network (a Prometheus
                           next to the stack) reaches it at web:8000/metrics.
GET /api/v1/ops/alerts     the built-in operational alerts, for administrators: a source
                           stale, a scoring cycle over half its length, the scheduler
                           silent, a job waiting over 10 minutes, a failed or overdue backup.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from pmp.api.deps import SignedIn, database_of, signed_in
from pmp.core import SCORING_STATE, Permission, authorize, last_backup, read_state
from pmp.ingestion import server_now, source_health
from pmp.modelling import list_active_versions
from pmp.scoring import OVERRUN_SHARE, get_runtime_statuses

router = APIRouter(tags=["operations"])
User = Annotated[SignedIn, Depends(signed_in)]

JOB_WAIT = timedelta(minutes=10)  # ARC §10.3
BACKUP_DUE = timedelta(hours=26)  # nightly, with two hours' slack
SCHEDULER_SILENT = timedelta(minutes=10)

Kind = Literal["source_stale", "cycle_overrun", "scheduler_silent", "job_queue", "backup_failed"]


class OpsAlert(BaseModel):
    kind: Kind
    severity: Literal["warning", "critical"]
    text: str
    since: datetime | None
    link: str | None


def _minutes(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes} min" if minutes < 120 else f"{minutes // 60} h"


def _queue(session: Session, now: datetime) -> tuple[int, datetime | None]:
    count, oldest = session.execute(
        text(
            "SELECT count(*), min(created_at) FROM job "
            "WHERE status = 'queued' AND run_after <= :now"
        ),
        {"now": now},
    ).one()
    return int(count), oldest


def operational_alerts(session: Session, now: datetime) -> list[OpsAlert]:
    alerts: list[OpsAlert] = []
    for source in source_health(session, now):
        if source.stale and source.last_received_at is not None:
            alerts.append(
                OpsAlert(
                    kind="source_stale",
                    severity="critical",
                    text=f"Source {source.source} has sent nothing for "
                    f"{_minutes(now - source.last_received_at)}.",
                    since=source.last_received_at,
                    link="/admin?tab=ingestion",
                )
            )
    scoring = read_state(session, SCORING_STATE)
    deployed = [v for v in list_active_versions(session) if v.status.value == "Deployed"]
    if scoring is not None:
        duration = float(scoring.data.get("duration_s", 0))
        cycle_s = int(scoring.data.get("cycle_s", 60))
        silent = now - scoring.updated_at
        if deployed and silent > max(SCHEDULER_SILENT, timedelta(seconds=3 * cycle_s)):
            alerts.append(
                OpsAlert(
                    kind="scheduler_silent",
                    severity="critical",
                    text=f"No scoring cycle for {_minutes(silent)}: is the worker running?",
                    since=scoring.updated_at,
                    link=None,
                )
            )
        elif duration > OVERRUN_SHARE * cycle_s:
            alerts.append(
                OpsAlert(
                    kind="cycle_overrun",
                    severity="warning",
                    text=f"The last scoring cycle took {duration:.0f} s, over half of the "
                    f"{cycle_s} s cycle.",
                    since=scoring.updated_at,
                    link=None,
                )
            )
    waiting, oldest = _queue(session, now)
    if oldest is not None and now - oldest > JOB_WAIT:
        alerts.append(
            OpsAlert(
                kind="job_queue",
                severity="warning",
                text=f"{waiting} job{'s' if waiting != 1 else ''} waiting, the oldest for "
                f"{_minutes(now - oldest)}: is the worker running?",
                since=oldest,
                link=None,
            )
        )
    backup = last_backup(session)
    if backup is not None and backup.status == "failed":
        alerts.append(
            OpsAlert(
                kind="backup_failed",
                severity="critical",
                text=f"The backup at {backup.started_at:%Y-%m-%d %H:%M} UTC failed: "
                f"{backup.error or 'no reason recorded'}",
                since=backup.started_at,
                link=None,
            )
        )
    elif backup is not None:
        succeeded = session.execute(
            text("SELECT max(finished_at) FROM backup_run WHERE status = 'succeeded'")
        ).scalar_one()
        if succeeded is not None and now - succeeded > BACKUP_DUE:
            alerts.append(
                OpsAlert(
                    kind="backup_failed",
                    severity="critical",
                    text=f"No successful backup for {_minutes(now - succeeded)}: "
                    "is the backup service running?",
                    since=succeeded,
                    link=None,
                )
            )
    return alerts


@router.get(
    "/api/v1/ops/alerts",
    response_model=list[OpsAlert],
    summary="Operational alerts (administrators, ARC §10.3)",
)
def get_ops_alerts(request: Request, user: User) -> list[OpsAlert]:
    authorize(user.actor, Permission.ADMINISTRATION, what="operational alerts")
    with database_of(request).session() as session:
        return operational_alerts(session, server_now(session))


# ------------------------------------------------------------------ Prometheus


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _metric(
    lines: list[str],
    name: str,
    kind: str,
    help_text: str,
    samples: Iterable[tuple[dict[str, str], float]],
) -> None:
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} {kind}")
    for labels, value in samples:
        label = ",".join(f'{k}="{_escape(v)}"' for k, v in labels.items())
        lines.append(f"{name}{{{label}}} {value:g}" if label else f"{name} {value:g}")


def metrics_text(session: Session, now: datetime, sse_clients: int) -> str:
    lines: list[str] = []
    sources = source_health(session, now)
    _metric(
        lines,
        "pmp_ingest_samples_accepted_total",
        "counter",
        "Samples accepted per gateway source.",
        (({"source": s.source}, s.accepted_total) for s in sources),
    )
    _metric(
        lines,
        "pmp_ingest_samples_rejected_total",
        "counter",
        "Samples rejected per gateway source.",
        (({"source": s.source}, s.rejected_total) for s in sources),
    )
    _metric(
        lines,
        "pmp_ingest_source_stale",
        "gauge",
        "1 while a source has sent nothing for over 2 scan intervals.",
        (({"source": s.source}, float(s.stale)) for s in sources),
    )
    scoring = read_state(session, SCORING_STATE)
    if scoring is not None:
        _metric(
            lines,
            "pmp_scoring_cycle_duration_seconds",
            "gauge",
            "How long the scheduler's last scoring pass took.",
            [({}, float(scoring.data.get("duration_s", 0)))],
        )
        _metric(
            lines,
            "pmp_scoring_last_cycle_timestamp_seconds",
            "gauge",
            "When the scheduler last scored (Unix time).",
            [({}, scoring.updated_at.timestamp())],
        )
    statuses = Counter(s.status.value for s in get_runtime_statuses(session))
    _metric(
        lines,
        "pmp_models",
        "gauge",
        "Models by runtime status.",
        (({"status": status}, count) for status, count in sorted(statuses.items())),
    )
    waiting, oldest = _queue(session, now)
    _metric(lines, "pmp_jobs_queued", "gauge", "Jobs waiting to run.", [({}, waiting)])
    _metric(
        lines,
        "pmp_job_queue_oldest_seconds",
        "gauge",
        "Age of the oldest waiting job (0 when none).",
        [({}, (now - oldest).total_seconds() if oldest else 0.0)],
    )
    _metric(
        lines,
        "pmp_sse_clients",
        "gauge",
        "Open live-event streams in this web process.",
        [({}, sse_clients)],
    )
    failed = session.execute(
        text("SELECT count(*) FROM notification_log WHERE status = 'failed'")
    ).scalar_one()
    _metric(
        lines,
        "pmp_notifications_failed_total",
        "counter",
        "E-mails given up after their retries.",
        [({}, failed)],
    )
    backup = last_backup(session)
    succeeded = session.execute(
        text("SELECT max(finished_at) FROM backup_run WHERE status = 'succeeded'")
    ).scalar_one()
    _metric(
        lines,
        "pmp_backup_last_success_timestamp_seconds",
        "gauge",
        "When the last backup succeeded (Unix time; 0 if never).",
        [({}, succeeded.timestamp() if succeeded else 0.0)],
    )
    _metric(
        lines,
        "pmp_backup_last_failed",
        "gauge",
        "1 if the latest backup failed.",
        [({}, float(backup is not None and backup.status == "failed"))],
    )
    return "\n".join(lines) + "\n"


@router.get(
    "/metrics",
    response_class=PlainTextResponse,
    summary="Prometheus metrics (internal network only: the proxy does not pass it on)",
)
def get_metrics(request: Request) -> PlainTextResponse:
    hub = getattr(request.app.state, "event_hub", None)
    with database_of(request).session() as session:
        body = metrics_text(session, server_now(session), hub.clients() if hub else 0)
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")
