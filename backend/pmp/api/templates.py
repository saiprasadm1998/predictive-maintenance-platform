"""Asset-type model templates (plan 8.6, UC-07, FR-MOD-08)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from pmp.alerting import template_rules_setter
from pmp.api.common import not_found
from pmp.api.deps import SignedIn, database_of, signed_in
from pmp.api.problems import ProblemError
from pmp.modelling import (
    AssetResult,
    ModelError,
    TemplateView,
    apply_template,
    get_template,
    list_templates,
    save_template,
)

router = APIRouter(prefix="/api/v1", tags=["models"])
User = Annotated[SignedIn, Depends(signed_in)]


class TemplateIn(BaseModel):
    asset_type: str
    name: str = Field(description="unique within the asset type")
    model_name: str = Field(default="main", description="the name of each model it creates")
    description: str = ""
    definition: dict[str, Any] = Field(
        description="a model definition with roles: sensors [{role, required}], algorithm, "
        "params, training_periods, validation_period, mode_filters ('{role} > 90'), "
        "alert_rules {di, sensors [{role, warning, alert}]}"
    )


class TemplateOut(BaseModel):
    id: int
    asset_type: str
    name: str
    model_name: str
    description: str
    definition: dict[str, Any]
    required_roles: list[str]
    optional_roles: list[str]
    updated_at: datetime
    updated_by: int | None


class ApplyIn(BaseModel):
    assets: list[str] | None = Field(
        default=None, description="asset codes; null: every asset of the type"
    )
    preview: bool = Field(default=False, description="resolve and report only")


class AssetResultOut(BaseModel):
    asset: str
    outcome: str = Field(description="ready (preview), created or skipped")
    reason: str | None
    tags: dict[str, str] = Field(description="role -> tag")
    missing_required: list[str]
    missing_optional: list[str] = Field(description="gaps: left out of the model")
    model_id: int | None
    version_id: int | None
    job_id: int | None


def _out(v: TemplateView) -> TemplateOut:
    return TemplateOut(
        id=v.id,
        asset_type=v.asset_type,
        name=v.name,
        model_name=v.model_name,
        description=v.description,
        definition=v.definition,
        required_roles=v.required_roles,
        optional_roles=v.optional_roles,
        updated_at=v.updated_at,
        updated_by=v.updated_by,
    )


def _result(r: AssetResult) -> AssetResultOut:
    return AssetResultOut(
        asset=r.asset_code,
        outcome=r.outcome.value,
        reason=r.reason,
        tags=r.tags,
        missing_required=list(r.missing_required),
        missing_optional=list(r.missing_optional),
        model_id=r.model_id,
        version_id=r.version_id,
        job_id=r.job_id,
    )


def _problem(error: ModelError) -> ProblemError:
    if "does not exist" in str(error):
        return not_found("Template or asset type")
    return ProblemError(400, "template_refused", str(error))


@router.get("/model-templates", response_model=list[TemplateOut], summary="Model templates")
def get_templates(request: Request, user: User, asset_type: str | None = None) -> list[TemplateOut]:
    try:
        with database_of(request).session() as session:
            return [_out(t) for t in list_templates(session, asset_type)]
    except ModelError as error:
        raise _problem(error) from None


@router.get(
    "/model-templates/{template_id}", response_model=TemplateOut, summary="One model template"
)
def get_one_template(request: Request, user: User, template_id: int) -> TemplateOut:
    try:
        with database_of(request).session() as session:
            return _out(get_template(session, template_id))
    except ModelError as error:
        raise _problem(error) from None


@router.put(
    "/model-templates",
    response_model=TemplateOut,
    summary="Create or replace an asset type's template (model engineers)",
)
def put_template(request: Request, user: User, body: TemplateIn) -> TemplateOut:
    try:
        with database_of(request).session() as session:
            saved = save_template(
                session,
                user.actor,
                body.asset_type,
                body.name,
                body.definition,
                model_name=body.model_name,
                description=body.description,
            )
            return _out(saved)
    except ModelError as error:
        raise _problem(error) from None


@router.post(
    "/model-templates/{template_id}/apply",
    response_model=list[AssetResultOut],
    summary="Resolve roles per asset, report gaps, and create and train the models (UC-07)",
)
def post_apply(
    request: Request, user: User, template_id: int, body: ApplyIn
) -> list[AssetResultOut]:
    try:
        with database_of(request).session() as session:
            results = apply_template(
                session,
                user.actor,
                template_id,
                body.assets,
                now=datetime.now(UTC),
                preview=body.preview,
                on_created=template_rules_setter(user.actor),
            )
            return [_result(r) for r in results]
    except ModelError as error:
        raise _problem(error) from None
