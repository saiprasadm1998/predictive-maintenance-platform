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
from collections.abc import Callable, Iterable, Mapping, Sequence
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

from pmp.core import (
    Actor,
    Database,
    Permission,
    audit_change,
    authorize,
    enqueue,
    log_context,
    report_progress,
)
from pmp.dataquality import assess_series, cycle_grid
from pmp.modelling.algorithms.contract import DetectorError
from pmp.modelling.algorithms.registry import available_detectors, get_detector
from pmp.modelling.artefacts import artefact_dir, write_artefact
from pmp.modelling.cleansing import Cluster, cleanse
from pmp.modelling.definitions import (
    ModelDefinition,
    ModelError,
    Period,
    VersionStatus,
    check_definition,
)
from pmp.modelling.expressions import ExpressionError, parse_expression
from pmp.modelling.models import ModeFilter, Model, ModelSensor, ModelVersion, TrainingPeriod
from pmp.modelling.training import (
    Assembled,
    SensorInfo,
    TrainingError,
    assemble,
    check_minimum_data,
    train,
)
from pmp.registry import (
    AssetView,
    TagView,
    asset_codes,
    find_asset,
    get_asset_by_id,
    get_tags,
    list_tags,
)

logger = logging.getLogger(__name__)

TRAINING, VALIDATION, EXCLUSION = "training", "validation", "exclusion"
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
    exclusion_periods: tuple[Period, ...] = ()
    error: str | None = None
    artefact_path: str | None = None
    artefact_sha256: str | None = None
    metrics: dict[str, Any] | None = None
    status_changed_at: datetime | None = None


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
        "exclusion_periods": [
            [p.start.isoformat(), p.end.isoformat()] for p in definition.exclusion_periods
        ],
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
    for period in definition.exclusion_periods:
        session.add(
            TrainingPeriod(
                version_id=version.id, kind=EXCLUSION, starts_at=period.start, ends_at=period.end
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


def _version_views(session: Session, versions: Sequence[ModelVersion]) -> list[VersionView]:
    """Views of several versions in a fixed number of queries (lists of models)."""
    ids = [v.id for v in versions]
    if not ids:
        return []
    sensor_rows = session.scalars(
        select(ModelSensor)
        .where(ModelSensor.version_id.in_(ids))
        .order_by(ModelSensor.version_id, ModelSensor.position)
    ).all()
    tags = {t.id: t for t in get_tags(session, {r.tag_id for r in sensor_rows})}
    periods = session.scalars(
        select(TrainingPeriod)
        .where(TrainingPeriod.version_id.in_(ids))
        .order_by(TrainingPeriod.version_id, TrainingPeriod.starts_at)
    ).all()
    filters = session.execute(
        select(ModeFilter.version_id, ModeFilter.expression)
        .where(ModeFilter.version_id.in_(ids))
        .order_by(ModeFilter.version_id, ModeFilter.position)
    ).all()
    sensors_of: dict[int, list[ModelSensor]] = {}
    for row in sensor_rows:
        sensors_of.setdefault(row.version_id, []).append(row)
    periods_of: dict[int, list[TrainingPeriod]] = {}
    for period in periods:
        periods_of.setdefault(period.version_id, []).append(period)
    filters_of: dict[int, list[str]] = {}
    for version_id, expression in filters:
        filters_of.setdefault(version_id, []).append(expression)

    views = []
    for version in versions:
        own_periods = periods_of.get(version.id, [])
        validation = [Period(p.starts_at, p.ends_at) for p in own_periods if p.kind == VALIDATION]
        views.append(
            VersionView(
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
                    for r in sensors_of.get(version.id, [])
                ),
                training_periods=tuple(
                    Period(p.starts_at, p.ends_at) for p in own_periods if p.kind == TRAINING
                ),
                validation_period=validation[0] if validation else None,
                mode_filters=tuple(filters_of.get(version.id, [])),
                exclusion_periods=tuple(
                    Period(p.starts_at, p.ends_at) for p in own_periods if p.kind == EXCLUSION
                ),
                created_at=version.created_at,
                error=version.error,
                artefact_path=version.artefact_path,
                artefact_sha256=version.artefact_sha256,
                metrics=dict(version.metrics) if version.metrics else None,
                status_changed_at=version.status_changed_at,
            )
        )
    return views


def _version_view(session: Session, version: ModelVersion) -> VersionView:
    (view,) = _version_views(session, [version])
    return view


def _model_views(
    session: Session, models: Sequence[Model], asset_codes_by_id: dict[int, str]
) -> list[ModelView]:
    """Views of several models, with all their versions, in a fixed number of queries."""
    if not models:
        return []
    versions = session.scalars(
        select(ModelVersion)
        .where(ModelVersion.model_id.in_([m.id for m in models]))
        .order_by(ModelVersion.model_id, ModelVersion.version)
    ).all()
    views_of: dict[int, list[VersionView]] = {}
    for version, view in zip(versions, _version_views(session, versions), strict=True):
        views_of.setdefault(version.model_id, []).append(view)
    return [
        ModelView(
            id=model.id,
            asset_code=asset_codes_by_id[model.asset_id],
            name=model.name,
            description=model.description,
            versions=tuple(views_of.get(model.id, [])),
        )
        for model in models
    ]


def _model_view(session: Session, model: Model, asset_code: str) -> ModelView:
    (view,) = _model_views(session, [model], {model.asset_id: asset_code})
    return view


# ------------------------------------------------------------------ services


def _checked(
    session: Session, actor: Actor, definition: ModelDefinition
) -> tuple[AssetView, dict[str, TagView]]:
    """The asset and its tags by source name, once the definition passes every check."""
    asset = find_asset(session, definition.asset_code)
    if asset is None:
        raise ModelError(f"Asset {definition.asset_code!r} does not exist")
    authorize(actor, Permission.MODELS, asset.path, what=f"models on {asset.code}")
    tags = list_tags(session, definition.asset_code)
    resolved, problems = _resolve_tags(tags, definition)
    enabled = [d.name for d in available_detectors() if d.enabled]
    try:
        check_definition(definition, resolved.keys(), enabled)
    except ModelError as error:
        problems = error.problems + problems
    if problems:
        raise ModelError(problems)
    return asset, resolved


def save_draft(session: Session, actor: Actor, definition: ModelDefinition) -> ModelView:
    """Create the model, or update its Draft, or start a new Draft version."""
    asset, resolved = _checked(session, actor, definition)

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
        "exclusion_periods": [
            [p.start.isoformat(), p.end.isoformat()] for p in view.exclusion_periods
        ],
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
    return _model_views(session, models, asset_codes(session, {m.asset_id for m in models}))


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
        "exclusion_periods": [
            [p.start.isoformat(), p.end.isoformat()] for p in view.exclusion_periods
        ],
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
    authorize(actor, Permission.MODELS, asset_path(session, asset_code), what=f"{asset_code}")
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


FLAGGED_BELOW = 0.9  # a sensor usable in less than 90 % of in-mode cycles is flagged


@dataclass(frozen=True)
class SensorUse:
    source_name: str
    description: str
    required: bool
    usable_share: float  # of the in-mode training cycles
    flagged: bool


@dataclass(frozen=True)
class TrainingDataPreview:
    """What the cleansing rules leave of the training periods (SCR-06 step 3, UC-05 3-6).

    Each rule counts only the cycles it removes after the rules before it (operating mode
    first, then data quality and coverage). The trend has about `points` time buckets:
    the share of cycles excluded in each, and each sensor's mean usable value."""

    cycle_s: int
    cycles: int
    retained: int
    mode_removed: int
    quality_removed: int
    excluded_removed: int  # inside the periods excluded on the trend
    outlier_removed: int  # a sensor with |robust z| > 4
    multivariate_removed: int  # far from every operating cluster
    clusters: tuple[Cluster, ...]  # retained cycles per operating cluster, largest first
    blocked: str | None  # the minimum-data rule's reason, if training would be blocked
    sensors: tuple[SensorUse, ...]
    bucket_s: int
    buckets: tuple[datetime, ...]
    excluded: tuple[float, ...]
    values: dict[str, tuple[float | None, ...]]


def preview_training_data(
    session: Session,
    actor: Actor,
    definition: ModelDefinition,
    *,
    points: int = 600,
) -> TrainingDataPreview:
    """Apply the data-quality rules, operating-mode filters and coverage rule to the
    training periods exactly as training will, without saving anything."""
    _, resolved = _checked(session, actor, definition)
    filters = [parse_expression(f) for f in definition.mode_filters]
    sensors = [
        SensorInfo(c.tag, c.required, resolved[c.tag].range_hi - resolved[c.tag].range_lo)
        for c in definition.sensors
    ]
    names = {s.name for s in sensors}.union(*(f.names for f in filters))
    tag_ids = {n: resolved[n].id for n in sorted(names)}
    cycle_s = int(definition.params.get("cycle_s", DEFAULT_CYCLE_S))
    data = _gather(session, definition.training_periods, cycle_s, sensors, tag_ids, filters)

    cleansing = cleanse(
        data.frame,
        data.in_mode,
        data.covered,
        definition.exclusion_periods,
        seed=int(definition.params.get("seed", DEFAULT_SEED)),
    )
    blocked = None
    if data.cycles == 0:
        blocked = "Training blocked: the training periods hold no scoring cycles."
    else:
        try:
            check_minimum_data(cleansing)
        except TrainingError as error:
            blocked = str(error)
    in_mode = data.in_mode
    present = data.frame.notna().to_numpy()
    modal = max(int(in_mode.sum()), 1)
    uses = []
    for i, choice in enumerate(definition.sensors):
        usable = float(present[in_mode, i].sum()) / modal if in_mode.any() else 0.0
        uses.append(
            SensorUse(
                choice.tag,
                resolved[choice.tag].description,
                choice.required,
                usable,
                usable < FLAGGED_BELOW,
            )
        )

    width_s = cycle_s
    buckets: tuple[datetime, ...] = ()
    excluded: tuple[float, ...] = ()
    values: dict[str, tuple[float | None, ...]] = {s.name: () for s in sensors}
    if data.cycles:
        ns = data.frame.index.to_numpy(dtype="datetime64[ns]").astype(np.int64)
        start_ns, end_ns = int(ns[0]), int(ns[-1]) + cycle_s * 10**9
        span_s = (end_ns - start_ns) // 10**9
        per_point = -(-span_s // max(points, 1))  # rounded up, then to whole cycles
        width_s = max(cycle_s, -(-per_point // cycle_s) * cycle_s)
        frame = data.frame.copy()
        frame["_excluded"] = ~cleansing.retained
        grouped = frame.groupby((ns - start_ns) // (width_s * 10**9)).mean()
        buckets = tuple(
            datetime.fromtimestamp(start_ns / 1e9 + int(b) * width_s, UTC)
            for b in grouped.index.to_numpy(dtype=np.int64)
        )
        excluded = tuple(float(x) for x in grouped["_excluded"].to_numpy(dtype=np.float64))
        values = {
            s.name: tuple(
                None if np.isnan(v) else round(float(v), 6)
                for v in grouped[s.name].to_numpy(dtype=np.float64)
            )
            for s in sensors
        }

    return TrainingDataPreview(
        cycle_s=cycle_s,
        cycles=data.cycles,
        retained=cleansing.kept,
        mode_removed=cleansing.removed["mode"],
        quality_removed=cleansing.removed["quality"],
        excluded_removed=cleansing.removed["excluded"],
        outlier_removed=cleansing.removed["outlier"],
        multivariate_removed=cleansing.removed["multivariate"],
        clusters=cleansing.clusters,
        blocked=blocked,
        sensors=tuple(uses),
        bucket_s=width_s,
        buckets=buckets,
        excluded=excluded,
        values=values,
    )


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
            result = train(
                detector_cls,
                params,
                sensors,
                training_data,
                validation_data,
                view.exclusion_periods,
            )
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
            if result.cleansing is not None:  # what each rule removed (SCR-06 step 3)
                metrics["cleansing"] = {
                    "removed": result.cleansing.removed,
                    "clusters": [c.cycles for c in result.cleansing.clusters],
                }
            if result.report is not None:  # plan 7.3: shown in the wizard and on SCR-11
                metrics["validation"] = result.report.as_dict()
            learnt = getattr(result.detector, "summary", None)  # e.g. AAKR's memory size
            if isinstance(learnt, dict):
                metrics["detector"] = learnt
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
        version_id = int(payload["version_id"])
        with database.session() as session:
            row = session.get(ModelVersion, version_id)
            model_id = str(row.model_id) if row is not None else None
        with log_context(model_id=model_id):  # ARC §10.3
            return run_training(database, version_id, artefact_base)

    return handle


def make_training_failure_handler(database: Database) -> Callable[[Mapping[str, Any], str], None]:
    """When a training job fails for good without finishing (e.g. the worker kept being
    lost), its version leaves Training for Failed, as ARC Figure 7 requires."""

    def on_failed(payload: Mapping[str, Any], error: str) -> None:
        _mark_failed(database, int(payload["version_id"]), f"Training job failed: {error}")

    return on_failed


def asset_path(session: Session, asset_code: str) -> str | None:
    """The asset's hierarchy path, for permission checks (None if it does not exist)."""
    asset = find_asset(session, asset_code)
    return asset.path if asset else None


def model_asset_code(session: Session, model_id: int) -> str:
    """The code of the asset a model monitors (cheap: for per-cycle use)."""
    model = session.get(Model, model_id)
    if model is None:
        raise ModelError(f"Model {model_id} does not exist")
    return get_asset_by_id(session, model.asset_id).code


def model_assets(session: Session) -> dict[int, tuple[int, str]]:
    """Every model's asset ID and name, by model ID (one query; for the health roll-up)."""
    rows = session.execute(select(Model.id, Model.asset_id, Model.name)).all()
    return {model_id: (asset_id, name) for model_id, asset_id, name in rows}


def version_numbers(session: Session, version_ids: Iterable[int]) -> dict[int, int]:
    """Version numbers by version ID, in one query (for lists of alerts)."""
    ids = set(version_ids)
    if not ids:
        return {}
    rows = session.execute(
        select(ModelVersion.id, ModelVersion.version).where(ModelVersion.id.in_(ids))
    ).all()
    return {row.id: row.version for row in rows}


def model_of_version(session: Session, version_id: int) -> ModelView:
    """The model a version belongs to (ModelError if there is no such version)."""
    version = session.get(ModelVersion, version_id)
    if version is None:
        raise ModelError(f"Model version {version_id} does not exist")
    return get_model_by_id(session, version.model_id)
