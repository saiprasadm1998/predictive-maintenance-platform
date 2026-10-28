"""The failure-mode library and diagnostics (UC-09 step 4, UC-16, FR-DIA-02, -03, FR-ADV-01).

The library holds failure modes per asset type. Each save of a changed mode is a new
version, audited; diagnostics use the current version from the next evaluation. A mode
is retired rather than deleted, so its history stays.

Diagnostics match every current mode of the model's asset type against the model's
latest scored cycle (or a chosen time), resolving each symptom's role to the asset's tag
with that role, and give each mode's match trend from the stored outputs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pmp.alerting import RuleKind, list_alert_rules
from pmp.core import Actor, Permission, audit_change, authorize
from pmp.diagnostics.domain import (
    DEFAULT_Z_REF,
    Direction,
    LibraryError,
    ModeMatch,
    ModeSpec,
    Reading,
    Symptom,
    check_mode,
    match_mode,
    rank,
)
from pmp.diagnostics.models import FailureMode, FailureModeVersion
from pmp.modelling import ModelError, VersionStatus, get_model_by_id
from pmp.registry import RegistryError, find_asset, get_asset_type, list_asset_types, list_tags
from pmp.scoring import cycle_outputs, latest_cycle, z_history

TREND_HOURS = 168  # the sparkline: 7 days, hourly


@dataclass(frozen=True)
class ModeView:
    id: int
    asset_type: str
    version: int
    spec: ModeSpec
    comment: str
    updated_at: datetime
    updated_by: int | None
    retired_at: datetime | None


def _spec(code: str, row: FailureModeVersion) -> ModeSpec:
    return ModeSpec(
        code=code,
        name=row.name,
        symptoms=tuple(
            Symptom(s["role"], Direction(s["direction"]), float(s["weight"])) for s in row.symptoms
        ),
        tasks=tuple(row.tasks),
        iso_code=row.iso_code,
        description=row.description,
    )


def _content(spec: ModeSpec) -> dict[str, Any]:
    return {
        "name": spec.name.strip(),
        "iso_code": (spec.iso_code or "").strip() or None,
        "description": spec.description.strip(),
        "symptoms": [
            {"role": s.role, "direction": s.direction.value, "weight": s.weight}
            for s in spec.symptoms
        ],
        "tasks": [t.strip() for t in spec.tasks],
    }


def _views(session: Session, modes: Sequence[FailureMode]) -> list[ModeView]:
    if not modes:
        return []
    types = {t.id: t.code for t in list_asset_types(session)}
    rows = {
        (r.failure_mode_id, r.version): r
        for r in session.scalars(
            select(FailureModeVersion).where(
                FailureModeVersion.failure_mode_id.in_([m.id for m in modes])
            )
        ).all()
    }
    views = []
    for m in modes:
        row = rows[(m.id, m.current_version)]
        views.append(
            ModeView(
                m.id,
                types.get(m.asset_type_id, "?"),
                m.current_version,
                _spec(m.code, row),
                row.comment,
                row.created_at,
                row.created_by,
                m.retired_at,
            )
        )
    return views


def list_modes(
    session: Session, asset_type: str | None = None, *, include_retired: bool = False
) -> list[ModeView]:
    query = select(FailureMode)
    if asset_type is not None:
        try:
            query = query.where(FailureMode.asset_type_id == get_asset_type(session, asset_type).id)
        except RegistryError:
            raise LibraryError(f"Asset type {asset_type!r} does not exist") from None
    if not include_retired:
        query = query.where(FailureMode.retired_at.is_(None))
    views = _views(session, session.scalars(query).all())
    return sorted(views, key=lambda v: (v.asset_type, v.spec.name))


def mode_history(session: Session, mode_id: int) -> list[ModeView]:
    """Every version of a mode, newest first (SCR-12 version history)."""
    mode = session.get(FailureMode, mode_id)
    if mode is None:
        raise LibraryError(f"Failure mode {mode_id} does not exist")
    types = {t.id: t.code for t in list_asset_types(session)}
    rows = session.scalars(
        select(FailureModeVersion)
        .where(FailureModeVersion.failure_mode_id == mode_id)
        .order_by(FailureModeVersion.version.desc())
    ).all()
    return [
        ModeView(
            mode.id,
            types.get(mode.asset_type_id, "?"),
            r.version,
            _spec(mode.code, r),
            r.comment,
            r.created_at,
            r.created_by,
            mode.retired_at,
        )
        for r in rows
    ]


def save_mode(
    session: Session, actor: Actor, asset_type: str, spec: ModeSpec, comment: str = ""
) -> ModeView:
    """Create a failure mode, or save a new version of it when its content changed."""
    authorize(actor, Permission.FAILURE_MODES, None, what="the failure-mode library")
    try:
        type_view = get_asset_type(session, asset_type)
    except RegistryError:
        raise LibraryError(f"Asset type {asset_type!r} does not exist") from None
    check_mode(spec, [r.code for r in type_view.roles])
    content = _content(spec)
    mode = session.scalars(
        select(FailureMode).where(
            FailureMode.asset_type_id == type_view.id, FailureMode.code == spec.code
        )
    ).one_or_none()
    before: dict[str, Any] | None = None
    if mode is None:
        mode = FailureMode(asset_type_id=type_view.id, code=spec.code, current_version=1)
        session.add(mode)
        session.flush()
        version = 1
    else:
        current = session.scalars(
            select(FailureModeVersion).where(
                FailureModeVersion.failure_mode_id == mode.id,
                FailureModeVersion.version == mode.current_version,
            )
        ).one()
        before = {
            "version": current.version,
            "name": current.name,
            "iso_code": current.iso_code,
            "description": current.description,
            "symptoms": current.symptoms,
            "tasks": current.tasks,
        }
        unchanged = {k: v for k, v in before.items() if k != "version"} == content
        if unchanged and mode.retired_at is None:
            return _views(session, [mode])[0]
        version = mode.current_version + 1
        mode.current_version = version
        mode.retired_at = None  # saving a retired mode brings it back
    session.add(
        FailureModeVersion(
            failure_mode_id=mode.id,
            version=version,
            comment=comment.strip(),
            created_by=actor.user_id,
            **content,
        )
    )
    session.flush()
    audit_change(
        session,
        actor,
        entity="failure_mode",
        entity_id=mode.id,
        action="create" if before is None else "new_version",
        before=before,
        after={"version": version, **content},
    )
    return _views(session, [mode])[0]


def retire_mode(session: Session, actor: Actor, mode_id: int, now: datetime) -> ModeView:
    """Take a mode out of diagnostics; its versions stay (saving it again brings it back)."""
    authorize(actor, Permission.FAILURE_MODES, None, what="the failure-mode library")
    mode = session.get(FailureMode, mode_id)
    if mode is None:
        raise LibraryError(f"Failure mode {mode_id} does not exist")
    if mode.retired_at is None:
        mode.retired_at = now
        session.flush()
        audit_change(
            session,
            actor,
            entity="failure_mode",
            entity_id=mode.id,
            action="retire",
            after={"retired_at": now.isoformat()},
        )
    return _views(session, [mode])[0]


# ------------------------------------------------------------------ diagnostics


@dataclass(frozen=True)
class ModeDiagnosis:
    mode: ModeView
    match: ModeMatch
    trend: list[tuple[datetime, float | None]]  # hourly score; None: insufficient evidence


@dataclass(frozen=True)
class Diagnosis:
    model_id: int
    asset_code: str
    asset_type: str | None
    version_id: int | None
    at: datetime | None  # the cycle matched; None: never scored
    modes: list[ModeDiagnosis]  # ranked, best match first


def diagnose(
    session: Session,
    model_id: int,
    at: datetime | None = None,
    trend_hours: int = TREND_HOURS,
) -> Diagnosis:
    """Match the asset type's failure modes against the model's cycle at or before `at`."""
    try:
        model = get_model_by_id(session, model_id)
    except ModelError:
        raise LibraryError(f"Model {model_id} does not exist") from None
    asset = find_asset(session, model.asset_code)
    asset_type = asset.asset_type_code if asset else None
    in_service = [
        v for v in model.versions if v.status in (VersionStatus.DEPLOYED, VersionStatus.PAUSED)
    ]
    candidates = in_service or list(reversed(model.versions))
    version_id, cycle = None, None
    for v in candidates:  # the version that scored the newest cycle
        found = latest_cycle(session, v.id, at)
        if found is not None and (cycle is None or found > cycle):
            version_id, cycle = v.id, found
    modes = list_modes(session, asset_type) if asset_type else []
    if not modes or version_id is None or cycle is None:
        return Diagnosis(model_id, model.asset_code, asset_type, version_id, cycle, [])

    tags = {t.id: t for t in list_tags(session, model.asset_code)}
    sensors = next(v for v in model.versions if v.id == version_id).sensors
    role_of = {s.tag_id: tags[s.tag_id].role_code for s in sensors if s.tag_id in tags}
    z_ref = {
        r.spec.tag_id: r.spec.warning
        for r in list_alert_rules(session, model_id)
        if r.spec.kind is RuleKind.SENSOR and r.spec.tag_id is not None
    }
    names = {s.tag_id: s.source_name for s in sensors}

    def readings(z_by_tag: dict[int, tuple[float | None, bool]]) -> dict[str, Reading]:
        out = {}
        for tag_id, role in role_of.items():
            if role is None:
                continue
            z, used = z_by_tag.get(tag_id, (None, False))
            out[role] = Reading(
                z, used, z_ref.get(tag_id, DEFAULT_Z_REF), tag_id, names.get(tag_id)
            )
        return out

    now = readings(
        {r.tag_id: (r.z, bool(r.used)) for r in cycle_outputs(session, version_id, cycle)}
    )
    history = z_history(session, version_id, cycle - timedelta(hours=trend_hours), cycle)
    hourly = [(ts, readings(z)) for ts, z in sorted(history.items())]
    matched = rank([match_mode(m.spec, now) for m in modes])
    by_code = {m.spec.code: m for m in modes}
    result = []
    for match in matched:
        trend = []
        for ts, r in hourly:
            point = match_mode(match.spec, r)
            trend.append((ts, None if point.insufficient else point.score))
        result.append(ModeDiagnosis(by_code[match.spec.code], match, trend))
    return Diagnosis(model_id, model.asset_code, asset_type, version_id, cycle, result)


def mode_from_dict(raw: Any) -> tuple[str, ModeSpec]:
    """One entry of a library file or API body: (asset type, mode)."""
    if not isinstance(raw, dict):
        raise LibraryError("A failure mode must be an object")
    try:
        symptoms = tuple(
            Symptom(str(s["role"]), Direction(str(s.get("direction", "any"))), float(s["weight"]))
            for s in raw["symptoms"]
        )
        spec = ModeSpec(
            code=str(raw["code"]),
            name=str(raw["name"]),
            symptoms=symptoms,
            tasks=tuple(str(t) for t in raw.get("tasks", [])),
            iso_code=str(raw["iso_code"]) if raw.get("iso_code") else None,
            description=str(raw.get("description", "")),
        )
        return str(raw["asset_type"]), spec
    except KeyError as missing:
        raise LibraryError(f"A failure mode is missing {missing}") from None
    except (TypeError, ValueError) as error:
        raise LibraryError(f"A failure mode is malformed: {error}") from None


def import_library(
    session: Session, actor: Actor, data: Any, comment: str = "imported"
) -> list[ModeView]:
    """Save every mode of a library file ({"modes": [...]}); unchanged modes are skipped."""
    if not isinstance(data, dict) or not isinstance(data.get("modes"), list):
        raise LibraryError('A library file holds {"modes": [...]}')
    return [save_mode(session, actor, *mode_from_dict(raw), comment) for raw in data["modes"]]
