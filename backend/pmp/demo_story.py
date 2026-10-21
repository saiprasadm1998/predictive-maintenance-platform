"""Putting the demo story in front of the screens (plan sub-phase 6.0).

`pmp demo history` writes six months of SYNTHETIC history, but history alone shows no
health: past data is never scored (only live cycles are), and alerts only come from
scored cycles. These two steps fill the gap so every screen has something to show:

- `setup_models`: create, train and deploy each demo model definition
  (data/demo/models/*.json). A model already in service is left alone, so it is safe to
  run again.
- `back_score`: score the cycles of the last few hours of data, oldest first, exactly as
  the worker would have scored them live. Alerts, their history and the health roll-up
  then exist as they would on a running plant.

This module sits above the feature modules (like the CLI), because it drives several of
them; it is for development and demonstrations only.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from pmp.alerting import AlertRuleError, require_di_rule, rules_from_dict, set_alert_rules
from pmp.core import Actor, Database
from pmp.modelling import (
    Action,
    ModelCache,
    ModelError,
    VersionStatus,
    change_status,
    definition_from_dict,
    find_model,
    list_active_versions,
    run_training,
    save_draft,
    start_training,
)
from pmp.scoring import latest_due_cycle, score_models

Say = Callable[[str], None]


@dataclass(frozen=True)
class SetupResult:
    label: str  # "K-101 / main"
    outcome: str  # "deployed", "already in service", "failed: ..."
    ok: bool


def setup_models(
    database: Database,
    files: Sequence[Path],
    artefact_dir: Path,
    *,
    now: datetime | None = None,
    say: Say = print,
) -> list[SetupResult]:
    """Create, train and deploy each definition file; skip models already in service."""
    actor = Actor.system()
    now = now or datetime.now(UTC)
    results: list[SetupResult] = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            label = f"{data.get('asset')} / {data.get('name')}"
        except (OSError, ValueError) as error:
            results.append(SetupResult(path.name, f"failed: cannot read ({error})", False))
            continue
        try:
            results.append(_setup_one(database, actor, data, label, artefact_dir, now, say))
        except (ModelError, AlertRuleError) as error:
            problems = getattr(error, "problems", None) or [str(error)]
            results.append(SetupResult(label, "failed: " + "; ".join(problems), False))
        say(f"  {results[-1].label:<20} {results[-1].outcome}")
    return results


def _setup_one(
    database: Database,
    actor: Actor,
    data: dict[str, object],
    label: str,
    artefact_dir: Path,
    now: datetime,
    say: Say,
) -> SetupResult:
    asset, name = str(data.get("asset")), str(data.get("name"))
    with database.session() as session:
        existing = find_model(session, asset, name)
        if existing is not None and any(
            v.status in (VersionStatus.DEPLOYED, VersionStatus.PAUSED) for v in existing.versions
        ):
            return SetupResult(label, "already in service (left as it is)", True)
        status = existing.latest.status if existing is not None else None
        if status not in (VersionStatus.VALIDATED, VersionStatus.TRAINING):
            definition = definition_from_dict(data, now)
            model = save_draft(session, actor, definition)
            set_alert_rules(
                session,
                actor,
                model.id,
                rules_from_dict(
                    data.get("alert_rules"),
                    {x.source_name: x.tag_id for x in model.latest.sensors},
                ),
            )
            status = VersionStatus.DRAFT
        if status is VersionStatus.TRAINING:
            raise ModelError(f"{label} is being trained by the worker; run this again later")
        version_id = None
        if status is VersionStatus.DRAFT:
            view, _ = start_training(session, actor, asset, name, queue=False)
            version_id = view.id
    if version_id is not None:
        say(f"  {label:<20} training ...")
        result = run_training(database, version_id, artefact_dir)
        if result.get("status") != VersionStatus.VALIDATED.value:
            return SetupResult(label, f"failed: training ended {result}", False)
    with database.session() as session:
        change_status(session, actor, asset, name, Action.DEPLOY, deploy_checks=(require_di_rule,))
    return SetupResult(label, "trained and deployed", True)


@dataclass(frozen=True)
class BackScoreResult:
    start: datetime | None
    end: datetime | None
    cycles: int  # cycle times scored (each scores every model in service)
    scored: int  # model cycles written
    alert_changes: int


def latest_sample_time(database: Database) -> datetime | None:
    with database.session() as session:
        found: datetime | None = session.execute(text("SELECT max(ts) FROM sample")).scalar()
    return found


def back_score(
    database: Database,
    hours: float,
    *,
    end: datetime | None = None,
    say: Say = print,
) -> BackScoreResult:
    """Score every cycle from `hours` before `end` (default: the newest sample) up to it,
    oldest first. Cycles already scored are skipped by the runtime, so running it again,
    or alongside the worker, never counts a cycle twice."""
    with database.session() as session:
        active = list_active_versions(session)
    end = end or latest_sample_time(database)
    if not active or end is None:
        return BackScoreResult(None, None, 0, 0, 0)
    step = min(v.cycle_s for v in active)
    last = latest_due_cycle(end, step, 0)
    first = latest_due_cycle(last - timedelta(hours=hours), step, 0)
    total = int((last - first).total_seconds() // step) + 1
    cache = ModelCache()
    cycles = scored = changes = 0
    at = first
    while at <= last:
        due = [v for v in active if int(at.timestamp()) % max(v.cycle_s, 1) == 0]
        if due:
            for result in score_models(database, at, due, cache):
                scored += int(result.written)
                changes += len(result.alerts)
        cycles += 1
        if cycles % max(1, total // 10) == 0 or at == last:
            say(f"  {at:%Y-%m-%d %H:%M} UTC  {100 * cycles / total:5.1f} %")
        at += timedelta(seconds=step)
    return BackScoreResult(first, last, cycles, scored, changes)
