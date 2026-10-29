"""Asset-type model templates (UC-07, FR-MOD-08).

A template is a model definition written with the asset type's roles: sensors as roles
(some required), the algorithm and its parameters, relative training and validation
periods, operating-mode filters with roles in braces ("{motor_current} > 90") and alert
rules with roles. Applied to assets of the type, each role resolves to the asset's tag
mapped to it. An asset missing a required role (or a role a mode filter uses) is skipped
and listed (UC-07 2a); a missing optional role is left out and reported as a gap. Each
eligible asset gets a draft model named after the template's model name, submitted for
training at once (UC-07 step 3).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Identity, Integer, String, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from pmp.core import Actor, Base, Permission, audit_change, authorize
from pmp.modelling.definitions import ModelError, definition_from_dict
from pmp.modelling.service import find_model, save_draft, start_training
from pmp.registry import RegistryError, get_asset_type, list_asset_types, list_subtree, list_tags

PLACEHOLDER = re.compile(r"\{([a-z0-9_]+)\}")


class TemplateRow(Base):
    __tablename__ = "model_template"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    asset_type_id: Mapped[int] = mapped_column(ForeignKey("asset_type.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[int | None] = mapped_column(Integer)


@dataclass(frozen=True)
class TemplateView:
    id: int
    asset_type: str
    name: str
    model_name: str
    description: str
    definition: dict[str, Any]  # sensors as roles; see the module docstring
    updated_at: datetime
    updated_by: int | None

    @property
    def required_roles(self) -> list[str]:
        roles = [s["role"] for s in self.definition["sensors"] if s.get("required")]
        for f in self.definition.get("mode_filters", []):
            roles += [r for r in PLACEHOLDER.findall(str(f)) if r not in roles]
        return roles

    @property
    def optional_roles(self) -> list[str]:
        required = set(self.required_roles)
        return [s["role"] for s in self.definition["sensors"] if s["role"] not in required]


class Outcome(StrEnum):
    READY = "ready"  # preview: would be created
    CREATED = "created"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class AssetResult:
    asset_code: str
    outcome: Outcome
    reason: str | None = None
    tags: dict[str, str] = field(default_factory=dict)  # role -> tag source name
    missing_required: tuple[str, ...] = ()
    missing_optional: tuple[str, ...] = ()  # gaps: left out of this asset's model
    model_id: int | None = None
    version_id: int | None = None
    job_id: int | None = None


def _view(session: Session, row: TemplateRow) -> TemplateView:
    types = {t.id: t.code for t in list_asset_types(session)}
    return TemplateView(
        row.id,
        types.get(row.asset_type_id, "?"),
        row.name,
        row.model_name,
        row.description,
        dict(row.definition),
        row.updated_at,
        row.updated_by,
    )


def _check(definition: Mapping[str, Any], roles: Iterable[str]) -> dict[str, Any]:
    """The template's definition, checked against the asset type's roles and the model
    definition rules (periods, algorithm parameters) with the roles standing in for tags."""
    known = set(roles)
    if not isinstance(definition, Mapping):
        raise ModelError("A template definition must be an object")
    sensors = definition.get("sensors")
    if not isinstance(sensors, list) or not sensors:
        raise ModelError("A template needs at least one sensor role")
    used: list[str] = []
    for s in sensors:
        if not isinstance(s, Mapping) or "role" not in s:
            raise ModelError('Each template sensor is {"role": ..., "required": true/false}')
        if s["role"] not in known:
            raise ModelError(f"The asset type has no role {s['role']!r}")
        if s["role"] in used:
            raise ModelError(f"Role {s['role']!r} is listed twice")
        used.append(str(s["role"]))
    for f in definition.get("mode_filters", []):
        for role in PLACEHOLDER.findall(str(f)):
            if role not in known:
                raise ModelError(f"Mode filter {f!r}: the asset type has no role {role!r}")
    rules = definition.get("alert_rules") or {}
    for r in rules.get("sensors", []) if isinstance(rules, Mapping) else []:
        if not isinstance(r, Mapping) or r.get("role") not in used:
            raise ModelError("Each sensor alert rule names one of the template's roles")
    sample = _resolved(definition, {r: r for r in used}, "TEMPLATE", "check")
    definition_from_dict(sample, datetime.now().astimezone())  # periods and parameters
    return {k: v for k, v in definition.items() if k not in ("asset", "name")}


def _resolved(
    definition: Mapping[str, Any], tags: Mapping[str, str], asset_code: str, model_name: str
) -> dict[str, Any]:
    """The model definition file content for one asset: roles replaced by its tags."""
    sensors = [
        {"tag": tags[s["role"]], "required": bool(s.get("required", False))}
        for s in definition["sensors"]
        if s["role"] in tags
    ]
    filters = [
        PLACEHOLDER.sub(lambda m: tags[m.group(1)], str(f))
        for f in definition.get("mode_filters", [])
    ]
    data = {
        **{k: v for k, v in definition.items() if k not in ("sensors", "mode_filters")},
        "asset": asset_code,
        "name": model_name,
        "sensors": sensors,
        "mode_filters": filters,
    }
    rules = definition.get("alert_rules")
    if isinstance(rules, Mapping):
        data["alert_rules"] = {
            **({"di": rules["di"]} if rules.get("di") is not None else {}),
            "sensors": [
                {**{k: v for k, v in r.items() if k != "role"}, "tag": tags[r["role"]]}
                for r in rules.get("sensors", [])
                if r.get("role") in tags
            ],
        }
    return data


def list_templates(session: Session, asset_type: str | None = None) -> list[TemplateView]:
    query = select(TemplateRow).order_by(TemplateRow.name)
    if asset_type is not None:
        try:
            query = query.where(TemplateRow.asset_type_id == get_asset_type(session, asset_type).id)
        except RegistryError:
            raise ModelError(f"Asset type {asset_type!r} does not exist") from None
    return [_view(session, r) for r in session.scalars(query).all()]


def get_template(session: Session, template_id: int) -> TemplateView:
    row = session.get(TemplateRow, template_id)
    if row is None:
        raise ModelError(f"Template {template_id} does not exist")
    return _view(session, row)


def save_template(
    session: Session,
    actor: Actor,
    asset_type: str,
    name: str,
    definition: Mapping[str, Any],
    *,
    model_name: str = "main",
    description: str = "",
    now: datetime | None = None,
) -> TemplateView:
    """Create or replace the asset type's template of this name (audited)."""
    authorize(actor, Permission.MODELS, None, what="model templates")
    try:
        type_view = get_asset_type(session, asset_type)
    except RegistryError:
        raise ModelError(f"Asset type {asset_type!r} does not exist") from None
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z0-9 _.-]{1,64}", name):
        raise ModelError("A template name has 1 to 64 letters, digits, spaces, '.', '_' or '-'")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", model_name):
        raise ModelError("The model name has 1 to 64 letters, digits, '.', '_' or '-'")
    content = _check(definition, [r.code for r in type_view.roles])
    row = session.scalars(
        select(TemplateRow).where(
            TemplateRow.asset_type_id == type_view.id, TemplateRow.name == name
        )
    ).one_or_none()
    before = None
    if row is None:
        row = TemplateRow(asset_type_id=type_view.id, name=name)
        session.add(row)
    else:
        before = {"model_name": row.model_name, "definition": row.definition}
    row.model_name = model_name
    row.description = description.strip()
    row.definition = content
    row.updated_by = actor.user_id
    if now is not None:
        row.updated_at = now
    session.flush()
    session.refresh(row)
    audit_change(
        session,
        actor,
        entity="model_template",
        entity_id=row.id,
        action="create" if before is None else "update",
        before=before,
        after={"asset_type": asset_type, "name": name, "model_name": model_name, **content},
    )
    return _view(session, row)


def template_from_dict(raw: Any) -> dict[str, Any]:
    """One entry of a templates file: {"asset_type", "name", "model_name"?, "description"?,
    "sensors", ...}."""
    if not isinstance(raw, Mapping) or "asset_type" not in raw or "name" not in raw:
        raise ModelError('A template needs "asset_type" and "name"')
    return dict(raw)


OnCreated = Callable[[Session, int, Mapping[str, Any], Mapping[str, int]], None]


def apply_template(
    session: Session,
    actor: Actor,
    template_id: int,
    asset_codes: Iterable[str] | None = None,
    *,
    now: datetime,
    preview: bool = False,
    on_created: OnCreated | None = None,
) -> list[AssetResult]:
    """UC-07: resolve the roles on each asset (all assets of the type when none are
    given), report the gaps and, unless previewing, create a draft model per eligible
    asset and submit it for training. `on_created(session, model_id, alert_rules,
    tag_ids)` sets the alert rules (the alerting module sits above this one)."""
    authorize(actor, Permission.MODELS, None, what="model templates")
    template = get_template(session, template_id)
    of_type = {a.code: a for a in list_subtree(session) if a.asset_type_code == template.asset_type}
    codes = list(dict.fromkeys(asset_codes)) if asset_codes is not None else sorted(of_type)
    results: list[AssetResult] = []
    for code in codes:
        asset = of_type.get(code)
        if asset is None:
            results.append(
                AssetResult(code, Outcome.SKIPPED, f"{code} is not a {template.asset_type}")
            )
            continue
        by_role: dict[str, str] = {}
        tag_ids: dict[str, int] = {}
        for tag in list_tags(session, code):
            if tag.role_code and tag.role_code not in by_role:
                by_role[tag.role_code] = tag.source_name
                tag_ids[tag.source_name] = tag.id
        wanted = [s["role"] for s in template.definition["sensors"]]
        tags = {r: by_role[r] for r in wanted if r in by_role}
        missing_required = tuple(r for r in template.required_roles if r not in by_role)
        missing_optional = tuple(r for r in template.optional_roles if r not in by_role)
        gaps = (tags, missing_required, missing_optional)
        if missing_required:
            reason = "required roles not mapped: " + ", ".join(missing_required)
            results.append(AssetResult(code, Outcome.SKIPPED, reason, *gaps))
            continue
        if find_model(session, code, template.model_name) is not None:
            reason = f"already has a model named {template.model_name!r}"
            results.append(AssetResult(code, Outcome.SKIPPED, reason, *gaps))
            continue
        if preview:
            results.append(AssetResult(code, Outcome.READY, None, *gaps))
            continue
        data = _resolved(template.definition, tags, code, template.model_name)
        data["description"] = data.get("description") or f"From template {template.name}"
        savepoint = session.begin_nested()  # one asset's failure leaves the others
        try:
            model = save_draft(session, actor, definition_from_dict(data, now))
            if on_created is not None:
                on_created(session, model.id, data.get("alert_rules") or {}, tag_ids)
            view, job = start_training(session, actor, code, template.model_name)
        except ModelError as error:
            savepoint.rollback()
            problems = getattr(error, "problems", None) or [str(error)]
            results.append(AssetResult(code, Outcome.SKIPPED, "; ".join(problems), *gaps))
            continue
        savepoint.commit()
        results.append(AssetResult(code, Outcome.CREATED, None, *gaps, model.id, view.id, job))
    if not preview:
        audit_change(
            session,
            actor,
            entity="model_template",
            entity_id=template.id,
            action="apply",
            after={
                "created": [r.asset_code for r in results if r.outcome is Outcome.CREATED],
                "skipped": {
                    r.asset_code: r.reason for r in results if r.outcome is Outcome.SKIPPED
                },
            },
        )
    return results
