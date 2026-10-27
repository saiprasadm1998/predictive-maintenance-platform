"""Retrospective evaluation against an event history (AC-04, PRD O-1 and O-2, ARC §11).

History is replayed through scoring with notifications off (`pmp demo score`, or the
worker on imported history); this module then compares the alerts that scoring raised
with the plant's event history (DP-04: asset, start, end, description):

- an event is detected when an alert on its asset was raised between the event's start and
  its end (the failure, trip or work order); its lead time is end minus the first such alert
- events marked not detectable (no measurable precursor in the monitored tags) are listed
  separately and do not count against detection (PRD note on AC-04)
- every other alert raised in the window is a false alert, per model-week of the models in
  service

An alert is counted each time it is raised. Under ISA-18.2 an unacknowledged alert that
returns to normal and is raised again keeps its record (RTN-Unacknowledged back to
Active), and nobody acknowledges during a replay, so the raises come from each alert's
history, not from its first raise time.

The report gives each alert so a reliability engineer can classify it (AC-04: "each alert
classified by a reliability engineer"); the proposed starting targets are at least 70 % of
detectable events alerted and no more than one false alert per model per two weeks.
"""

from __future__ import annotations

import csv
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from pmp.alerting import alert_history, list_alerts
from pmp.modelling import VersionStatus, list_models

TARGET_DETECTED = 0.70
TARGET_FALSE_PER_MODEL_WEEK = 0.5
WEEK = timedelta(days=7)


class EvaluationError(ValueError):
    """The event history cannot be read."""


_RELATIVE = re.compile(r"(-?\d+(?:\.\d+)?)([dh])")


def _when(text: str, anchor: datetime, label: str) -> datetime:
    """ISO 8601 with a time zone, or days or hours from the anchor: -21d, -10h, 0d."""
    value = (text or "").strip()
    match = _RELATIVE.fullmatch(value)
    if match:
        amount = float(match.group(1))
        return anchor + (
            timedelta(days=amount) if match.group(2) == "d" else timedelta(hours=amount)
        )
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        raise EvaluationError(
            f"{label}: {value!r} is not a time (ISO 8601, -21d or -10h)"
        ) from None
    if when.tzinfo is None:
        raise EvaluationError(f"{label}: {value!r} needs a time zone, e.g. Z")
    return when


@dataclass(frozen=True)
class Event:
    asset: str
    start: datetime
    end: datetime  # the failure, trip or work order: the moment an alert must precede
    description: str
    detectable: bool = True


@dataclass(frozen=True)
class AlertOutcome:
    alert_id: int
    asset: str
    model: str
    raised_at: datetime
    severity: str
    event: str | None  # the event it preceded; None: a false alert


@dataclass(frozen=True)
class EventOutcome:
    event: Event
    first_alert: datetime | None

    @property
    def lead_time(self) -> timedelta | None:
        return self.event.end - self.first_alert if self.first_alert else None


@dataclass(frozen=True)
class Evaluation:
    start: datetime
    end: datetime
    model_weeks: float
    events: list[EventOutcome]
    alerts: list[AlertOutcome]
    not_detectable: list[Event] = field(default_factory=list)

    @property
    def detected_share(self) -> float | None:
        if not self.events:
            return None
        return sum(e.first_alert is not None for e in self.events) / len(self.events)

    @property
    def median_lead_time(self) -> timedelta | None:
        leads = [e.lead_time for e in self.events if e.lead_time is not None]
        if not leads:
            return None
        return timedelta(seconds=statistics.median(t.total_seconds() for t in leads))

    @property
    def false_alerts(self) -> int:
        return sum(a.event is None for a in self.alerts)

    @property
    def false_per_model_week(self) -> float:
        return self.false_alerts / self.model_weeks if self.model_weeks else 0.0

    @property
    def meets_targets(self) -> bool:
        share = self.detected_share
        return (
            share is not None
            and share >= TARGET_DETECTED
            and self.false_per_model_week <= TARGET_FALSE_PER_MODEL_WEEK
        )


def read_events(path: Path, anchor: datetime) -> list[Event]:
    """CSV with columns asset, start, end, description and optionally detectable (yes/no).
    Times are ISO 8601 with a time zone, or relative to `anchor` such as -21d, -10h or 0d."""
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as error:
        raise EvaluationError(f"Cannot read {path}: {error}") from None
    events = []
    for line, row in enumerate(rows, start=2):
        try:
            start = _when(row["start"], anchor, f"Line {line} start")
            end = _when(row["end"], anchor, f"Line {line} end")
        except KeyError as missing:
            raise EvaluationError(f"{path} needs a {missing} column") from None
        if not start < end:
            raise EvaluationError(f"Line {line}: the start must be before the end")
        detectable = (row.get("detectable") or "yes").strip().lower() not in ("no", "false", "0")
        events.append(
            Event(
                row["asset"].strip(), start, end, (row.get("description") or "").strip(), detectable
            )
        )
    return events


def evaluate(
    session: Session, events: Sequence[Event], start: datetime, end: datetime
) -> Evaluation:
    """Compare the alerts raised in [start, end) with the events (see the module notes)."""
    in_service = [
        m
        for m in list_models(session)
        if any(v.status in (VersionStatus.DEPLOYED, VersionStatus.PAUSED) for v in m.versions)
    ]
    by_id = {m.id: m for m in list_models(session)}
    raised = sorted(
        (
            (alert, event.ts, event.severity)
            for alert in list_alerts(session, open_only=False)
            for event in alert_history(session, alert.id)
            if event.action == "raise" and start <= event.ts < end
        ),
        key=lambda found: found[1],
    )
    countable = [e for e in events if e.detectable and e.end > start and e.start < end]
    outcomes: list[AlertOutcome] = []
    first: dict[int, datetime] = {}
    for alert, at, severity in raised:
        model = by_id.get(alert.model_id)
        asset = model.asset_code if model else "?"
        match = next(
            (i for i, e in enumerate(countable) if e.asset == asset and e.start <= at <= e.end),
            None,
        )
        if match is not None:
            first.setdefault(match, at)
        outcomes.append(
            AlertOutcome(
                alert.id,
                asset,
                f"{asset} / {model.name}" if model else "?",
                at,
                str(severity),
                countable[match].description if match is not None else None,
            )
        )
    return Evaluation(
        start=start,
        end=end,
        model_weeks=len(in_service) * (end - start) / WEEK,
        events=[EventOutcome(e, first.get(i)) for i, e in enumerate(countable)],
        alerts=outcomes,
        not_detectable=[e for e in events if not e.detectable],
    )


def format_report(result: Evaluation) -> list[str]:
    """The event-based evaluation report (AC-04) as plain text lines."""

    def days(delta: timedelta | None) -> str:
        return "—" if delta is None else f"{delta.total_seconds() / 86_400:.1f} d"

    share = result.detected_share
    lines = [
        f"Evaluation {result.start:%Y-%m-%d %H:%M} to {result.end:%Y-%m-%d %H:%M} UTC, "
        f"{result.model_weeks:.1f} model-weeks",
        "",
        "Events (detectable)",
    ]
    for outcome in result.events:
        e = outcome.event
        found = (
            f"alerted {outcome.first_alert:%Y-%m-%d %H:%M}, lead {days(outcome.lead_time)}"
            if outcome.first_alert
            else "MISSED"
        )
        lines.append(f"  {e.asset:<8} {e.description:<45} {found}")
    for e in result.not_detectable:
        lines.append(f"  {e.asset:<8} {e.description:<45} not detectable (reported apart)")
    lines += ["", "Alerts (for classification by a reliability engineer)"]
    for a in result.alerts:
        what = f"preceded: {a.event}" if a.event else "FALSE (no event)"
        lines.append(
            f"  #{a.alert_id:<5} {a.raised_at:%Y-%m-%d %H:%M} {a.model:<16} {a.severity:<8} {what}"
        )
    lines += [
        "",
        "Summary",
        f"  Detectable events alerted: "
        f"{'—' if share is None else f'{share:.0%}'} (target at least {TARGET_DETECTED:.0%})",
        f"  Median lead time: {days(result.median_lead_time)}",
        f"  False alerts: {result.false_alerts}, {result.false_per_model_week:.2f} per model-week "
        f"(target at most {TARGET_FALSE_PER_MODEL_WEEK:g})",
        f"  Targets met: {'yes' if result.meets_targets else 'no'}",
    ]
    return lines
