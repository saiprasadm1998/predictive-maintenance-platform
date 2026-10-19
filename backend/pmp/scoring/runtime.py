"""One scoring cycle (FR-RUN-01 to -04, UCS §6.2 and Figure 5, ARC §5.1).

For every deployed model at cycle time T:

1. Read each sensor's latest sample at or before T (sample-and-hold) and run the
   data-quality rules with the model's training statistics (pmp.dataquality).
2. Coverage below 70 % or a required sensor unusable -> "Insufficient data", Unknown
   (checked first, as in UCS Figure 5: if the data stops, the status says so).
3. Not in the operating mode -> status "Not in operating mode", Health Unknown.
4. Otherwise scale, predict every sensor from the usable ones, and compute residual, q, z,
   DI, contributions, Health and band (pmp.scoring.outputs).
5. Write the score, the sensor outputs and the runtime status in one transaction, with a
   NOTIFY for the live stream (5.3); the alert engine joins this transaction in 4.2.

A cycle already written is never written again (the score table's key), so a cycle run
twice after a crash creates no duplicates, and late data never changes a past score.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from pmp.alerting import RuleKind, list_alert_rules
from pmp.core import Database, Event, EventBus
from pmp.dataquality import MIN_COVERAGE, Reference, SensorReading, read_sensors
from pmp.modelling import ActiveVersion, LoadedModel, ModelCache, ModelError, parse_expression
from pmp.scoring.models import RuntimeStatusRow, ScoreRow, SensorOutputRow
from pmp.scoring.outputs import (
    Band,
    Limits,
    ModelOutput,
    RuntimeStatus,
    ScoringError,
    SensorInput,
    SensorLimits,
    compute_outputs,
)

logger = logging.getLogger(__name__)
EVENT_CHANNEL = "pmp_events"


@dataclass(frozen=True, kw_only=True)
class ScoreComputed(Event):
    model_id: int
    version_id: int
    ts: datetime
    status: RuntimeStatus
    band: Band
    di: float | None
    health: float | None
    coverage: float


@dataclass(frozen=True)
class CycleResult:
    model_id: int
    version_id: int
    ts: datetime
    status: RuntimeStatus
    reason: str | None
    output: ModelOutput | None
    written: bool  # False when this cycle had already been scored

    @property
    def band(self) -> Band:
        return self.output.band if self.output else Band.UNKNOWN

    def event(self) -> ScoreComputed:
        output = self.output
        return ScoreComputed(
            model_id=self.model_id,
            version_id=self.version_id,
            ts=self.ts,
            status=self.status,
            band=self.band,
            di=output.di if output else None,
            health=output.health if output else None,
            coverage=output.coverage if output else 0.0,
        )


# ------------------------------------------------------------------ pure evaluation


def limits_for(session: Session, model: LoadedModel) -> Limits:
    """The model's active limits: its DI rule and sensor |z| rules (pmp.alerting)."""
    names = {tag_id: name for name, tag_id in model.tag_ids.items()}
    di = None
    sensors: dict[str, SensorLimits] = {}
    for rule in list_alert_rules(session, model.model_id):
        spec = rule.spec
        if not spec.enabled:
            continue
        if spec.kind is RuleKind.DI:
            di = (spec.warning, spec.alert)
        elif spec.tag_id in names:
            sensors[names[spec.tag_id]] = SensorLimits(spec.warning, spec.alert)
    if di is None:
        raise ScoringError("The model has no enabled DI alert rule")
    return Limits(di_warning=di[0], di_alert=di[1], sensors=sensors)


def references_for(models: Iterable[LoadedModel]) -> dict[int, Reference]:
    """Training statistics per tag for the data-quality rules. Pass models oldest
    deployment first: a tag in several models takes the latest one's statistics."""
    refs: dict[int, Reference] = {}
    for model in models:
        for name in model.sensors:
            refs[model.tag_ids[name]] = Reference(
                range=model.scales[name].range, std=model.training_std.get(name)
            )
    return refs


def _usable_value(reading: SensorReading | None) -> float | None:
    if reading is None or reading.value is None or not math.isfinite(reading.value):
        return None
    return reading.value if reading.state.usable else None


def evaluate(
    model: LoadedModel, readings: Mapping[int, SensorReading], limits: Limits
) -> tuple[RuntimeStatus, str | None, ModelOutput]:
    """Steps 2 to 4 for one model. Pure: no database."""
    by_name = {name: readings.get(tag_id) for name, tag_id in model.tag_ids.items()}
    usable = {name: _usable_value(r) for name, r in by_name.items()}

    filter_values = {n: _usable_value(readings.get(t)) for n, t in model.filter_tag_ids.items()}
    in_mode = all(parse_expression(f).evaluate(filter_values) for f in model.mode_filters)

    share = sum(usable[n] is not None for n in model.sensors) / len(model.sensors)
    missing = sorted(n for n in model.required if usable[n] is None)

    def plain(status: RuntimeStatus) -> ModelOutput:
        inputs = [
            SensorInput(n, _value(by_name[n]), None, usable[n] is not None) for n in model.sensors
        ]
        return compute_outputs(inputs, model.scales, limits, status)

    if missing or share < MIN_COVERAGE:
        reason = (
            f"Required sensor not usable: {', '.join(missing)}"
            if missing
            else f"Coverage {share:.0%} (needs {MIN_COVERAGE:.0%})"
        )
        return RuntimeStatus.INSUFFICIENT_DATA, reason, plain(RuntimeStatus.INSUFFICIENT_DATA)

    if not in_mode:
        return (
            RuntimeStatus.NOT_IN_OPERATING_MODE,
            "Outside the operating-mode filter",
            plain(RuntimeStatus.NOT_IN_OPERATING_MODE),
        )

    def scaled_value(name: str) -> float:
        value = usable[name]
        if value is None:
            return float("nan")
        return (value - model.medians[name]) / model.scales[name].range

    scaled = pd.DataFrame([[scaled_value(n) for n in model.sensors]], columns=list(model.sensors))
    predicted = model.detector.predict(scaled)
    inputs = [
        SensorInput(
            n,
            _value(by_name[n]),
            float(predicted[n].iloc[0]) * model.scales[n].range + model.medians[n],
            usable[n] is not None,
        )
        for n in model.sensors
    ]
    return RuntimeStatus.RUNNING, None, compute_outputs(inputs, model.scales, limits)


def _value(reading: SensorReading | None) -> float | None:
    if reading is None or reading.value is None or not math.isfinite(reading.value):
        return None
    return reading.value


# ------------------------------------------------------------------ persistence


def _set_runtime_status(
    session: Session,
    model_id: int,
    version_id: int | None,
    status: RuntimeStatus,
    reason: str | None,
    cycle: datetime | None,
) -> None:
    row = session.get(RuntimeStatusRow, model_id)
    if row is None:
        session.add(
            RuntimeStatusRow(
                model_id=model_id,
                version_id=version_id,
                status=status.value,
                reason=reason,
                last_cycle=cycle,
                since=cycle or func.now(),
            )
        )
        return
    if row.status != status.value or row.version_id != version_id:
        row.since = cycle or func.now()
    row.status, row.reason, row.version_id = status.value, reason, version_id
    if cycle is not None:
        row.last_cycle = cycle


def _notify(session: Session, result: CycleResult) -> None:
    output = result.output
    payload = {
        "type": "score.updated",
        "model_id": result.model_id,
        "ts": result.ts.isoformat(),
        "status": result.status.value,
        "band": result.band.value,
        "health": output.health if output else None,
        "di": output.di if output else None,
    }
    session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": EVENT_CHANNEL, "payload": json.dumps(payload)},
    )


def write_result(session: Session, model: LoadedModel | None, result: CycleResult) -> bool:
    """Write one model's cycle in the caller's transaction. False if already written."""
    output = result.output
    inserted = session.execute(
        insert(ScoreRow)
        .values(
            version_id=result.version_id,
            ts=result.ts,
            model_id=result.model_id,
            status=result.status.value,
            band=result.band.value,
            di=output.di if output else None,
            health=output.health if output else None,
            coverage=output.coverage if output else 0.0,
            reason=result.reason,
        )
        .on_conflict_do_nothing()
        .returning(ScoreRow.ts)
    ).first()
    if inserted is None:
        return False
    if output is not None and model is not None and result.status is RuntimeStatus.RUNNING:
        rows = [
            {
                "version_id": result.version_id,
                "tag_id": model.tag_ids[s.tag],
                "ts": result.ts,
                "actual": s.actual,
                "predicted": s.predicted,
                "residual": s.residual,
                "q": s.q,
                "z": s.z,
                "contribution": s.contribution,
                "dq_status": "usable" if s.usable else "excluded",
            }
            for s in output.sensors
        ]
        session.execute(insert(SensorOutputRow).values(rows).on_conflict_do_nothing())
    _set_runtime_status(
        session, result.model_id, result.version_id, result.status, result.reason, result.ts
    )
    _notify(session, result)
    return True


# ------------------------------------------------------------------ one cycle


def score_models(
    database: Database,
    cycle: datetime,
    active: Sequence[ActiveVersion],
    cache: ModelCache,
    *,
    bus: EventBus | None = None,
) -> list[CycleResult]:
    """Score every Deployed version in `active` at `cycle`; record Paused ones."""
    results: list[CycleResult] = []
    loaded: list[LoadedModel] = []
    for version in sorted(active, key=lambda v: v.version_id):
        if version.status.value == "Paused":
            with database.session() as session:
                _set_runtime_status(
                    session, version.model_id, version.version_id, RuntimeStatus.PAUSED, None, None
                )
            continue
        try:
            with database.session() as session:
                loaded.append(cache.get(session, version.version_id))
        except ModelError as error:
            results.append(_record_error(database, version, cycle, f"Cannot load model: {error}"))

    if loaded:
        tag_ids = {t for m in loaded for t in (*m.tag_ids.values(), *m.filter_tag_ids.values())}
        with database.session() as session:
            readings = read_sensors(
                session, cycle, tag_ids, references=references_for(loaded), bus=bus
            )
    for model in loaded:
        results.append(_score_one(database, model, readings, cycle))

    if bus is not None:
        for result in results:
            if result.written:
                bus.publish(result.event())
    return results


def _score_one(
    database: Database,
    model: LoadedModel,
    readings: Mapping[int, SensorReading],
    cycle: datetime,
) -> CycleResult:
    try:
        with database.session() as session:
            limits = limits_for(session, model)
            status, reason, output = evaluate(model, readings, limits)
            result = CycleResult(
                model.model_id, model.version_id, cycle, status, reason, output, False
            )
            written = write_result(session, model, result)
        return CycleResult(model.model_id, model.version_id, cycle, status, reason, output, written)
    except Exception as error:  # one model failing never stops the others
        logger.exception("Scoring model %s at %s failed", model.model_id, cycle)
        return _record_error_ids(
            database, model.model_id, model.version_id, cycle, f"{type(error).__name__}: {error}"
        )


def _record_error(
    database: Database, version: ActiveVersion, cycle: datetime, reason: str
) -> CycleResult:
    return _record_error_ids(database, version.model_id, version.version_id, cycle, reason)


def _record_error_ids(
    database: Database, model_id: int, version_id: int, cycle: datetime, reason: str
) -> CycleResult:
    result = CycleResult(model_id, version_id, cycle, RuntimeStatus.ERROR, reason, None, False)
    with database.session() as session:
        written = write_result(session, None, result)
    return CycleResult(model_id, version_id, cycle, RuntimeStatus.ERROR, reason, None, written)


def mark_out_of_service(database: Database, active_model_ids: Iterable[int]) -> list[int]:
    """Models that have a runtime status but no version in service any more (retired)."""
    active = set(active_model_ids)
    changed = []
    with database.session() as session:
        for row in session.scalars(select(RuntimeStatusRow)).all():
            if row.model_id not in active and row.status != RuntimeStatus.OUT_OF_SERVICE.value:
                _set_runtime_status(
                    session, row.model_id, row.version_id, RuntimeStatus.OUT_OF_SERVICE, None, None
                )
                changed.append(row.model_id)
    return changed


def last_cycles(session: Session) -> dict[int, datetime]:
    """The latest scored cycle per version (so a restarted scheduler does not repeat it)."""
    rows = session.execute(
        select(ScoreRow.version_id, func.max(ScoreRow.ts)).group_by(ScoreRow.version_id)
    ).all()
    return {int(v): ts for v, ts in rows}


@dataclass(frozen=True)
class RuntimeStatusView:
    model_id: int
    version_id: int | None
    status: RuntimeStatus
    reason: str | None
    last_cycle: datetime | None
    since: datetime
    band: Band
    di: float | None
    health: float | None


def get_runtime_statuses(session: Session) -> list[RuntimeStatusView]:
    """Each model's current runtime status with its latest score (FR-RUN-04)."""
    views = []
    for row in session.scalars(select(RuntimeStatusRow).order_by(RuntimeStatusRow.model_id)):
        score = None
        if row.version_id is not None and row.last_cycle is not None:
            score = session.get(ScoreRow, (row.version_id, row.last_cycle))
        views.append(
            RuntimeStatusView(
                model_id=row.model_id,
                version_id=row.version_id,
                status=RuntimeStatus(row.status),
                reason=row.reason,
                last_cycle=row.last_cycle,
                since=row.since,
                band=Band(score.band) if score else Band.UNKNOWN,
                di=score.di if score else None,
                health=score.health if score else None,
            )
        )
    return views
