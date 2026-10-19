"""Model definition services: create a model, edit its draft, show and list (UC-05).

Saving a definition creates the model with a Draft version 1, replaces the definition of
the latest version while it is still a Draft, or starts a new Draft version once the latest
has been trained. Every change is audited (FR-AUD-01).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pmp.core import Actor, audit_change
from pmp.modelling.algorithms.registry import available_detectors
from pmp.modelling.definitions import (
    ModelDefinition,
    ModelError,
    Period,
    VersionStatus,
    check_definition,
)
from pmp.modelling.expressions import parse_expression
from pmp.modelling.models import ModeFilter, Model, ModelSensor, ModelVersion, TrainingPeriod
from pmp.registry import TagView, find_asset, get_asset_by_id, get_tags, list_tags

TRAINING, VALIDATION = "training", "validation"


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
        if latest.status == VersionStatus.DRAFT.value:
            version, action = latest, "update_draft"
            before = _view_snapshot(_version_view(session, latest), previous_description)
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
