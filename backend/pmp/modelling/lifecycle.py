"""Model version lifecycle (ARC Figure 7, FR-MOD-07, UC-06).

    Draft -> Training -> Validated | Failed        (training, 3.2)
    Failed -> Draft                                 (fix configuration: save the definition)
    Validated -> Draft                              reject
    Validated -> Deployed                           deploy; the previous active version is
                                                    Superseded
    Deployed <-> Paused                             pause / resume
    Deployed | Paused -> Retired                    retire

Exactly one version per model is in service (Deployed or Paused); the database enforces it
(migration 0006). Every transition is audited and published as ModelStatusChanged
(ModelDeployed as well on deploy, ARC §4).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from pmp.core import Actor, Event, EventBus, audit_change
from pmp.modelling.definitions import ModelError, VersionStatus
from pmp.modelling.models import Model, ModelVersion
from pmp.modelling.service import ModelView, _set_status, get_model, get_model_by_id
from pmp.registry import get_asset_by_id


class Action(StrEnum):
    DEPLOY = "deploy"
    PAUSE = "pause"
    RESUME = "resume"
    RETIRE = "retire"
    REJECT = "reject"


_D, _V, _P = VersionStatus.DEPLOYED, VersionStatus.VALIDATED, VersionStatus.PAUSED
TRANSITIONS: dict[Action, tuple[frozenset[VersionStatus], VersionStatus]] = {
    Action.DEPLOY: (frozenset({_V}), _D),
    Action.PAUSE: (frozenset({_D}), _P),
    Action.RESUME: (frozenset({_P}), _D),
    Action.RETIRE: (frozenset({_D, _P}), VersionStatus.RETIRED),
    Action.REJECT: (frozenset({_V}), VersionStatus.DRAFT),
}
ACTIVE = (VersionStatus.DEPLOYED.value, VersionStatus.PAUSED.value)


@dataclass(frozen=True, kw_only=True)
class ModelStatusChanged(Event):
    model_id: int
    version_id: int
    version: int
    previous: VersionStatus
    status: VersionStatus
    action: str  # an Action, or "supersede" for the version a deploy replaced


@dataclass(frozen=True, kw_only=True)
class ModelDeployed(Event):
    model_id: int
    version_id: int
    version: int
    superseded_version_id: int | None


DeployCheck = Callable[[Session, int], None]  # raises ModelError if the model may not deploy


_DONE = {
    Action.DEPLOY: "deployed",
    Action.PAUSE: "paused",
    Action.RESUME: "resumed",
    Action.RETIRE: "retired",
    Action.REJECT: "rejected",
}


def next_status(current: VersionStatus, action: Action, version: int) -> VersionStatus:
    """The status after `action`, or ModelError naming what is allowed."""
    allowed, target = TRANSITIONS[action]
    if current not in allowed:
        need = " or ".join(sorted(s.value for s in allowed))
        raise ModelError(
            f"Cannot {action.value} version {version}: it is {current.value}; "
            f"only a {need} version can be {_DONE[action]}"
        )
    return target


def _target_version(
    session: Session, model: ModelView, action: Action, version: int | None
) -> ModelVersion:
    if version is not None:
        row = session.scalars(
            select(ModelVersion).where(
                ModelVersion.model_id == model.id, ModelVersion.version == version
            )
        ).one_or_none()
        if row is None:
            raise ModelError(f"Model {model.asset_code} / {model.name} has no version {version}")
        return row
    if action in (Action.PAUSE, Action.RESUME, Action.RETIRE):
        active = session.scalars(
            select(ModelVersion).where(
                ModelVersion.model_id == model.id, ModelVersion.status.in_(ACTIVE)
            )
        ).one_or_none()
        if active is None:
            raise ModelError(f"Model {model.asset_code} / {model.name} has no version in service")
        return active
    return session.get_one(ModelVersion, model.latest.id)


def _audit(
    session: Session, actor: Actor, row: ModelVersion, action: str, before: VersionStatus
) -> None:
    audit_change(
        session,
        actor,
        entity="model_version",
        entity_id=row.id,
        action=action,
        before={"status": before.value},
        after={"status": row.status, "version": row.version},
    )


def change_status(
    session: Session,
    actor: Actor,
    asset_code: str,
    name: str,
    action: Action,
    *,
    version: int | None = None,
    bus: EventBus | None = None,
    deploy_checks: tuple[DeployCheck, ...] = (),
) -> ModelView:
    """Apply a lifecycle action to a version (default: the latest version for deploy and
    reject, the version in service for pause, resume and retire)."""
    model = get_model(session, asset_code, name)
    row = _target_version(session, model, action, version)
    current = VersionStatus(row.status)
    target = next_status(current, action, row.version)
    events: list[Event] = []

    superseded: ModelVersion | None = None
    if action is Action.DEPLOY:
        for check in deploy_checks:
            check(session, model.id)
        superseded = session.scalars(
            select(ModelVersion).where(
                ModelVersion.model_id == model.id,
                ModelVersion.status.in_(ACTIVE),
                ModelVersion.id != row.id,
            )
        ).one_or_none()
        if superseded is not None:
            previous = VersionStatus(superseded.status)
            _set_status(superseded, VersionStatus.SUPERSEDED)
            session.flush()  # free the one-active-version slot first
            _audit(session, actor, superseded, "supersede", previous)
            events.append(
                ModelStatusChanged(
                    model_id=model.id,
                    version_id=superseded.id,
                    version=superseded.version,
                    previous=previous,
                    status=VersionStatus.SUPERSEDED,
                    action="supersede",
                )
            )

    if action is Action.REJECT:
        folder = row.artefact_path
        row.artefact_path = row.artefact_sha256 = None
        row.metrics = row.training_def = None
        if folder:
            shutil.rmtree(Path(folder), ignore_errors=True)

    _set_status(row, target)
    session.flush()
    _audit(session, actor, row, action.value, current)
    events.append(
        ModelStatusChanged(
            model_id=model.id,
            version_id=row.id,
            version=row.version,
            previous=current,
            status=target,
            action=action.value,
        )
    )
    if action is Action.DEPLOY:
        events.append(
            ModelDeployed(
                model_id=model.id,
                version_id=row.id,
                version=row.version,
                superseded_version_id=superseded.id if superseded else None,
            )
        )
    if bus is not None:
        for event in events:
            bus.publish(event)
    return get_model_by_id(session, model.id)


@dataclass(frozen=True)
class ActiveVersion:
    """A model's version in service (Deployed or Paused)."""

    model_id: int
    asset_code: str
    name: str
    version_id: int
    version: int
    status: VersionStatus
    cycle_s: int
    asset_id: int


def list_active_versions(session: Session) -> list[ActiveVersion]:
    """Every model's version in service, for the scoring scheduler."""
    rows = session.execute(
        select(ModelVersion, Model)
        .join(Model, Model.id == ModelVersion.model_id)
        .where(ModelVersion.status.in_(ACTIVE))
        .order_by(Model.id)
    ).all()
    return [
        ActiveVersion(
            model_id=model.id,
            asset_code=get_asset_by_id(session, model.asset_id).code,
            name=model.name,
            version_id=version.id,
            version=version.version,
            status=VersionStatus(version.status),
            cycle_s=int((version.params or {}).get("cycle_s", 60)),
            asset_id=model.asset_id,
        )
        for version, model in rows
    ]
