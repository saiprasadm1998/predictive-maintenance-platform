"""Model definition services: create a model, edit its draft, show and list (UC-05).

Saving a definition creates the model with a Draft version 1, replaces the definition of
the latest version while it is still a Draft, or starts a new Draft version once the latest
has been trained. Every change is audited (FR-AUD-01).
"""

from __future__ import annotations

import hashlib
import json
import logging
import platform
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pmp.core import Actor, Database, audit_change, enqueue, report_progress
from pmp.dataquality import assess_series, cycle_grid
from pmp.modelling.algorithms.contract import DetectorError
from pmp.modelling.algorithms.registry import available_detectors, get_detector
from pmp.modelling.artefacts import artefact_dir, write_artefact
from pmp.modelling.definitions import (
    ModelDefinition,
    ModelError,
    Period,
    VersionStatus,
    check_definition,
)
from pmp.modelling.expressions import ExpressionError, parse_expression
from pmp.modelling.models import ModeFilter, Model, ModelSensor, ModelVersion, TrainingPeriod
from pmp.modelling.training import Assembled, SensorInfo, TrainingError, assemble, train
from pmp.registry import TagView, find_asset, get_asset_by_id, get_tags, list_tags

logger = logging.getLogger(__name__)

TRAINING, VALIDATION = "training", "validation"
TRAIN_JOB = "model.train"
DEFAULT_SEED = 42
DEFAULT_CYCLE_S = 60


@dataclass(frozen=True)
class ModelSensorView:
    tag_id: int
    source: str
    source_name: str
    description: str
    required: bool


@dataclass(frozen=True)
class VersionView:
    id: int
    version: int
    status: VersionStatus
    algorithm: str
    params: dict[str, Any]
    sensors: tuple[ModelSensorView, ...]
    training_periods: tuple[Period, ...]
    validation_period: Period | None
    mode_filters: tuple[str, ...]
    created_at: datetime
    error: str | None = None
    artefact_path: str | None = None
    artefact_sha256: str | None = None
    metrics: dict[str, Any] | None = None


@dataclass(frozen=True)
class ModelView:
    id: int
    asset_code: str
    name: str
    description: str
    versions: tuple[VersionView, ...]  # oldest first

    @property
    def latest(self) -> VersionView:
        return self.versions[-1]


# ------------------------------------------------------------------ helpers


def _resolve_tags(
    tags: list[TagView], definition: ModelDefinition
) -> tuple[dict[str, TagView], list[str]]:
    """Source name to tag for the asset's tags; problems for ambiguous sensor names."""
    by_name: dict[str, list[TagView]] = {}
    for tag in tags:
        by_name.setdefault(tag.source_name, []).append(tag)
    resolved: dict[str, TagView] = {}
    problems = []
    for name, candidates in by_name.items():
        resolved[name] = candidates[0]
    for choice in definition.sensors:
        candidates = by_name.get(choice.tag, [])
        if choice.source is not None:
            candidates = [t for t in candidates if t.source == choice.source]
            if candidates:
                resolved[choice.tag] = candidates[0]
        if len(candidates) > 1:
            problems.append(f"Tag {choice.tag!r} exists in several sources; give its source")
    return resolved, problems


def _snapshot(definition: ModelDefinition) -> dict[str, Any]:
    return {
        "description": definition.description,
        "algorithm": definition.algorithm,
        "params": dict(definition.params),
        "sensors": [{"tag": s.tag, "required": s.required} for s in definition.sensors],
        "training_periods": [
            [p.start.isoformat(), p.end.isoformat()] for p in definition.training_periods
        ],
        "validation_period": [
            definition.validation_period.start.isoformat(),
            definition.validation_period.end.isoformat(),
        ],
        "mode_filters": [str(parse_expression(f)) for f in definition.mode_filters],
    }


def _write_definition(
    session: Session, version: ModelVersion, definition: ModelDefinition, tags: dict[str, TagView]
) -> None:
    for table in (ModelSensor, TrainingPeriod, ModeFilter):
        session.execute(delete(table).where(table.version_id == version.id))
    version.algorithm = definition.algorithm
    version.params = dict(definition.params)
    for position, choice in enumerate(definition.sensors):
        session.add(
            ModelSensor(
                version_id=version.id,
                tag_id=tags[choice.tag].id,
                position=position,
                required=choice.required,
            )
        )
    for period in definition.training_periods:
        session.add(
            TrainingPeriod(
                version_id=version.id, kind=TRAINING, starts_at=period.start, ends_at=period.end
            )
        )
    validation = definition.validation_period
    session.add(
        TrainingPeriod(
            version_id=version.id,
            kind=VALIDATION,
            starts_at=validation.start,
            ends_at=validation.end,
        )
    )
    for position, text in enumerate(definition.mode_filters):
        session.add(
            ModeFilter(
                version_id=version.id, position=position, expression=str(parse_expression(text))
            )
        )
    session.flush()


def _version_view(session: Session, version: ModelVersion) -> VersionView:
    sensor_rows = session.scalars(
        select(ModelSensor)
        .where(ModelSensor.version_id == version.id)
        .order_by(ModelSensor.position)
    ).all()
    tags = {t.id: t for t in get_tags(session, [r.tag_id for r in sensor_rows])}
    periods = session.scalars(
        select(TrainingPeriod)
        .where(TrainingPeriod.version_id == version.id)
        .order_by(TrainingPeriod.starts_at)
    ).all()
    filters = session.scalars(
        select(ModeFilter.expression)
        .where(ModeFilter.version_id == version.id)
        .order_by(ModeFilter.position)
    ).all()
    validation = [Period(p.starts_at, p.ends_at) for p in periods if p.kind == VALIDATION]
    return VersionView(
        id=version.id,
        version=version.version,
        status=VersionStatus(version.status),
        algorithm=version.algorithm,
        params=dict(version.params or {}),
        sensors=tuple(
            ModelSensorView(
                r.tag_id,
                tags[r.tag_id].source,
                tags[r.tag_id].source_name,
                tags[r.tag_id].description,
                r.required,
            )
            for r in sensor_rows
        ),
        training_periods=tuple(
            Period(p.starts_at, p.ends_at) for p in periods if p.kind == TRAINING
        ),
        validation_period=validation[0] if validation else None,
        mode_filters=tuple(filters),
        created_at=version.created_at,
        error=version.error,
        artefact_path=version.artefact_path,
        artefact_sha256=version.artefact_sha256,
        metrics=dict(version.metrics) if version.metrics else None,
    )


def _model_view(session: Session, model: Model, asset_code: str) -> ModelView:
    versions = session.scalars(
        select(ModelVersion).where(ModelVersion.model_id == model.id).order_by(ModelVersion.version)
    ).all()
    return ModelView(
        id=model.id,
        asset_code=asset_code,
        name=model.name,
        description=model.description,
        versions=tuple(_version_view(session, v) for v in versions),
    )


# ------------------------------------------------------------------ services


def save_draft(session: Session, actor: Actor, definition: ModelDefinition) -> ModelView:
    """Create the model, or update its Draft, or start a new Draft version."""
    asset = find_asset(session, definition.asset_code)
    if asset is None:
        raise ModelError(f"Asset {definition.asset_code!r} does not exist")
    tags = list_tags(session, definition.asset_code)
    resolved, problems = _resolve_tags(tags, definition)
    enabled = [d.name for d in available_detectors() if d.enabled]
    try:
        check_definition(definition, resolved.keys(), enabled)
    except ModelError as error:
        problems = error.problems + problems
    if problems:
        raise ModelError(problems)

    name = definition.name.strip()
    model = session.scalars(
        select(Model).where(Model.asset_id == asset.id, Model.name == name)
    ).one_or_none()
    after = _snapshot(definition)
    if model is None:
        model = Model(
            asset_id=asset.id,
            name=name,
            description=definition.description,
            created_by=actor.user_id,
        )
        session.add(model)
        session.flush()
        version = ModelVersion(
            model_id=model.id,
            version=1,
            algorithm=definition.algorithm,
            status=VersionStatus.DRAFT.value,
            created_by=actor.user_id,
        )
        session.add(version)
        session.flush()
        action, before = "create", None
    else:
        previous_description = model.description
        model.description = definition.description
        latest = session.scalars(
            select(ModelVersion)
            .where(ModelVersion.model_id == model.id)
            .order_by(ModelVersion.version.desc())
            .limit(1)
        ).one()
        if latest.status in (VersionStatus.DRAFT.value, VersionStatus.FAILED.value):
            # Failed -> Draft: "fix configuration" (ARC Figure 7)
            action = "update_draft" if latest.status == VersionStatus.DRAFT.value else "fix_failed"
            before = _view_snapshot(_version_view(session, latest), previous_description)
            version = latest
            if latest.status == VersionStatus.FAILED.value:
                _set_status(latest, VersionStatus.DRAFT)
                latest.error = None
        else:
            version = ModelVersion(
                model_id=model.id,
                version=latest.version + 1,
                algorithm=definition.algorithm,
                status=VersionStatus.DRAFT.value,
                created_by=actor.user_id,
            )
            session.add(version)
            session.flush()
            action, before = "new_version", None
    _write_definition(session, version, definition, resolved)
    audit_change(
        session,
        actor,
        entity="model",
        entity_id=model.id,
        action=action,
        before=before,
        after={"version": version.version, **after},
    )
    return _model_view(session, model, definition.asset_code)


def _view_snapshot(view: VersionView, description: str) -> dict[str, Any]:
    return {
        "version": view.version,
        "description": description,
        "algorithm": view.algorithm,
        "params": view.params,
        "sensors": [{"tag": s.source_name, "required": s.required} for s in view.sensors],
        "training_periods": [
            [p.start.isoformat(), p.end.isoformat()] for p in view.training_periods
        ],
        "validation_period": (
            [view.validation_period.start.isoformat(), view.validation_period.end.isoformat()]
            if view.validation_period
            else None
        ),
        "mode_filters": list(view.mode_filters),
    }


def find_model(session: Session, asset_code: str, name: str) -> ModelView | None:
    asset = find_asset(session, asset_code)
    if asset is None:
        return None
    model = session.scalars(
        select(Model).where(Model.asset_id == asset.id, Model.name == name.strip())
    ).one_or_none()
    return _model_view(session, model, asset.code) if model else None


def get_model(session: Session, asset_code: str, name: str) -> ModelView:
    view = find_model(session, asset_code, name)
    if view is None:
        raise ModelError(f"No model {name!r} on asset {asset_code!r}")
    return view


def get_model_by_id(session: Session, model_id: int) -> ModelView:
    model = session.get(Model, model_id)
    if model is None:
        raise ModelError(f"Model {model_id} does not exist")
    return _model_view(session, model, get_asset_by_id(session, model.asset_id).code)


def list_models(session: Session, asset_code: str | None = None) -> list[ModelView]:
    query = select(Model).order_by(Model.id)
    if asset_code is not None:
        asset = find_asset(session, asset_code)
        if asset is None:
            raise ModelError(f"Asset {asset_code!r} does not exist")
        query = query.where(Model.asset_id == asset.id)
    models = session.scalars(query).all()
    return [_model_view(session, m, get_asset_by_id(session, m.asset_id).code) for m in models]


# ------------------------------------------------------------------ training (3.2)


def _set_status(version: ModelVersion, status: VersionStatus) -> None:
    version.status = status.value
    version.status_changed_at = datetime.now(UTC)


def _training_definition(view: VersionView, params: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "algorithm": view.algorithm,
        "params": dict(params),
        "sensors": [
            {"tag_id": s.tag_id, "tag": s.source_name, "required": s.required} for s in view.sensors
        ],
        "training_periods": [
            [p.start.isoformat(), p.end.isoformat()] for p in view.training_periods
        ],
        "validation_period": (
            [view.validation_period.start.isoformat(), view.validation_period.end.isoformat()]
            if view.validation_period
            else None
        ),
        "mode_filters": list(view.mode_filters),
    }


def start_training(
    session: Session, actor: Actor, asset_code: str, name: str, *, queue: bool = True
) -> tuple[VersionView, int | None]:
    """Submit the model's Draft version for training: Draft -> Training, job queued.

    The seed and cycle time are fixed in the version's parameters now (ARC §8.3), and the
    definition is snapshotted. Returns the version and the job ID (None with queue=False,
    when the caller runs the training itself, as `pmp model train --now` does).
    """
    model = get_model(session, asset_code, name)
    version = session.get_one(ModelVersion, model.latest.id)
    if version.status != VersionStatus.DRAFT.value:
        raise ModelError(
            f"Version {version.version} is {version.status}; only a Draft can be trained"
        )
    params = {"seed": DEFAULT_SEED, "cycle_s": DEFAULT_CYCLE_S, **dict(version.params or {})}
    version.params = params
    version.training_def = _training_definition(model.latest, params)
    _set_status(version, VersionStatus.TRAINING)
    job_id = enqueue(session, TRAIN_JOB, {"version_id": version.id}) if queue else None
    audit_change(
        session,
        actor,
        entity="model_version",
        entity_id=version.id,
        action="train_start",
        before={"status": VersionStatus.DRAFT.value},
        after={"status": VersionStatus.TRAINING.value, "job_id": job_id, "params": params},
    )
    session.flush()
    return _version_view(session, version), job_id


def _versions() -> dict[str, str]:
    found = {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__}
    try:
        found["pmp"] = package_version("pmp")
    except PackageNotFoundError:  # pragma: no cover - running from a source tree
        found["pmp"] = "unknown"
    return found


def _mark_failed(database: Database, version_id: int, message: str) -> None:
    with database.session() as session:
        version = session.get(ModelVersion, version_id)
        if version is None or version.status != VersionStatus.TRAINING.value:
            return
        _set_status(version, VersionStatus.FAILED)
        version.error = message
        audit_change(
            session,
            Actor.system(),
            entity="model_version",
            entity_id=version_id,
            action="train_failed",
            before={"status": VersionStatus.TRAINING.value},
            after={"status": VersionStatus.FAILED.value, "error": message},
        )


def _gather(
    session: Session,
    periods: Sequence[Period],
    cycle_s: int,
    sensors: Sequence[SensorInfo],
    tag_ids: Mapping[str, int],
    filters: Sequence[Any],
) -> Assembled:
    grids = [cycle_grid(p.start, p.end, cycle_s) for p in periods]
    cycle_ns = np.concatenate(grids) if grids else np.empty(0, dtype=np.int64)
    assessed = assess_series(session, tag_ids.values(), cycle_ns)
    values = {name: assessed[tag_id].values for name, tag_id in tag_ids.items()}
    usable = {name: assessed[tag_id].usable for name, tag_id in tag_ids.items()}
    return assemble(cycle_ns, sensors, values, usable, filters)


def run_training(database: Database, version_id: int, artefact_base: Path) -> dict[str, Any]:
    """Train a version that is in Training; ends Validated or Failed with the reason.

    Safe to run again after a crash: a version that is no longer Training is skipped, and
    the artefact folder is replaced as a whole.
    """
    try:
        with database.session() as session:
            version = session.get(ModelVersion, version_id)
            if version is None:
                return {"skipped": f"version {version_id} does not exist"}
            if version.status != VersionStatus.TRAINING.value:
                return {"skipped": f"version is {version.status}"}
            model = session.get_one(Model, version.model_id)
            asset_code = get_asset_by_id(session, model.asset_id).code
            view = _version_view(session, version)
            if view.validation_period is None:
                raise TrainingError("The version has no validation period")
            asset_tags = {t.source_name: t for t in list_tags(session, asset_code)}
            filters = [parse_expression(f) for f in view.mode_filters]
            sensors = [
                SensorInfo(
                    s.source_name,
                    s.required,
                    asset_tags[s.source_name].range_hi - asset_tags[s.source_name].range_lo,
                )
                for s in view.sensors
            ]
            names = {s.name for s in sensors}.union(*(f.names for f in filters))
            tag_ids = {n: asset_tags[n].id for n in sorted(names)}
            params = dict(version.params or {})
            cycle_s = int(params.get("cycle_s", DEFAULT_CYCLE_S))

            training_data = _gather(
                session, view.training_periods, cycle_s, sensors, tag_ids, filters
            )
            report_progress(40)
            validation_data = _gather(
                session, [view.validation_period], cycle_s, sensors, tag_ids, filters
            )
            report_progress(60)
            detector_cls = get_detector(version.algorithm)
            result = train(detector_cls, params, sensors, training_data, validation_data)
            report_progress(85)

            definition = version.training_def or _training_definition(view, params)
            definition_hash = hashlib.sha256(
                json.dumps(definition, sort_keys=True).encode()
            ).hexdigest()
            target = artefact_dir(artefact_base, model.id, version.version)
            manifest = {
                "model_id": model.id,
                "model": model.name,
                "asset": asset_code,
                "version": version.version,
                "algorithm": version.algorithm,
                "algorithm_version": detector_cls.version,
                "seed": params.get("seed"),
                "cycle_s": cycle_s,
                "sensor_order": [s.name for s in sensors],
                "definition_sha256": definition_hash,
                "versions": _versions(),
            }
            sha = write_artefact(
                target,
                result.detector,
                scaling=result.scaling(),
                manifest=manifest,
                validation=result.validation(),
            )
            metrics = {
                "training_cycles": result.training_cycles,
                "training_retained": result.training_retained,
                "validation_cycles": result.validation_cycles,
                "validation_retained": result.validation_retained,
                "floored_sensors": sorted(
                    n
                    for n, st in result.sensors.items()
                    if st.scale.range_floored or st.scale.sigma_floored
                ),
            }
            version.artefact_path = str(target)
            version.artefact_sha256 = sha
            version.metrics = metrics
            version.error = None
            _set_status(version, VersionStatus.VALIDATED)
            audit_change(
                session,
                Actor.system(),
                entity="model_version",
                entity_id=version.id,
                action="train_validated",
                before={"status": VersionStatus.TRAINING.value},
                after={"status": VersionStatus.VALIDATED.value, "artefact_sha256": sha, **metrics},
            )
            return {"status": VersionStatus.VALIDATED.value, "artefact": str(target), **metrics}
    except (TrainingError, DetectorError, ExpressionError, ModelError) as error:
        _mark_failed(database, version_id, str(error))
        return {"status": VersionStatus.FAILED.value, "error": str(error)}
    except Exception as error:
        logger.exception("Training of model version %s failed", version_id)
        message = f"Training failed unexpectedly: {type(error).__name__}: {error}"
        _mark_failed(database, version_id, message)
        return {"status": VersionStatus.FAILED.value, "error": message}


def make_training_handler(
    database: Database, artefact_base: Path
) -> Callable[[Mapping[str, Any]], Mapping[str, Any]]:
    """The worker's handler for `model.train` jobs. Payload: {"version_id": int}."""

    def handle(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return run_training(database, int(payload["version_id"]), artefact_base)

    return handle


def model_asset_code(session: Session, model_id: int) -> str:
    """The code of the asset a model monitors (cheap: for per-cycle use)."""
    model = session.get(Model, model_id)
    if model is None:
        raise ModelError(f"Model {model_id} does not exist")
    return get_asset_by_id(session, model.asset_id).code
