"""Data-quality rules: read, preview and change (UC-04, FR-DQ-01, -02, UCS §6.1). Changing
rules is for Model Engineers (ARC §9.2); the service checks it."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from pmp.api.common import can_see, not_found
from pmp.api.deps import SignedIn, database_of, signed_in
from pmp.api.problems import ProblemError
from pmp.dataquality import (
    DEFAULTS,
    DataQualityError,
    PreviewReport,
    RuleScope,
    authorize_rule_change,
    get_rule_set,
    preview_rules,
    save_rule_set,
)
from pmp.modelling import ModelCache
from pmp.registry import get_asset_by_id, get_tags, list_subtree
from pmp.scoring import deployed_references

router = APIRouter(prefix="/api/v1/dq", tags=["data quality"])
User = Annotated[SignedIn, Depends(signed_in)]
SCOPE_HELP = "global, role:<asset type>/<role> or tag:<tag ID>"


def _scope(text: str) -> RuleScope:
    kind, _, key = text.partition(":")
    if kind == "global" and not key:
        return RuleScope.everywhere()
    if kind == "role" and "/" in key:
        asset_type, _, role = key.partition("/")
        return RuleScope.role(asset_type, role)
    if kind == "tag" and key.isdigit():
        return RuleScope.tag(int(key))
    raise ProblemError(400, "invalid_scope", "Invalid scope", f"Use {SCOPE_HELP}.")


class RuleSetOut(BaseModel):
    scope: str
    version: int = Field(description="0: nothing saved for this scope")
    overrides: dict[str, Any]
    comment: str
    created_at: datetime | None
    defaults: dict[str, Any]


class RulesIn(BaseModel):
    scope: str = Field(description=SCOPE_HELP)
    overrides: dict[str, Any] = Field(description="parameter -> value; {} removes all")
    comment: str = ""
    confirm: bool = Field(
        default=False, description="save even if a tag would be excluded > 20 % (UC-04 3a)"
    )
    days: int = Field(default=30, ge=1, le=365)


class TagPreviewOut(BaseModel):
    tag_id: int
    source_name: str
    asset_code: str
    cycles: int
    excluded: int
    excluded_share: float
    by_rule: dict[str, int]


class PreviewOut(BaseModel):
    scope: str
    start: datetime
    end: datetime
    excluded_share: float
    warning: bool = Field(description="some tag would be excluded more than 20 % of the time")
    tags: list[TagPreviewOut]


class SavedOut(BaseModel):
    rules: RuleSetOut
    preview: PreviewOut


def _visible_scope(session: Session, user: SignedIn, scope: RuleScope) -> None:
    """A tag's rules are read only by users who may see the tag's asset (ARC §9.2)."""
    if scope.kind.value == "tag":
        tags = get_tags(session, [int(scope.key)])
        if tags and not can_see(user, get_asset_by_id(session, tags[0].asset_id).path):
            raise not_found("Tag")


def _visible_tags(session: Session, user: SignedIn, report: PreviewOut) -> PreviewOut:
    """Only the tags the user may see are listed (the overall share covers the scope)."""
    paths = {a.code: a.path for a in list_subtree(session)}
    tags = [t for t in report.tags if can_see(user, paths.get(t.asset_code))]
    return report.model_copy(update={"tags": tags})


def _rules_out(session: Session, scope: RuleScope) -> RuleSetOut:
    view = get_rule_set(session, scope)
    return RuleSetOut(
        scope=str(scope),
        version=view.version,
        overrides=view.overrides,
        comment=view.comment,
        created_at=view.created_at,
        defaults=DEFAULTS.as_dict(),
    )


def _preview_out(report: PreviewReport) -> PreviewOut:
    return PreviewOut(
        scope=str(report.scope),
        start=report.start,
        end=report.end,
        excluded_share=report.excluded_share,
        warning=report.warning,
        tags=[
            TagPreviewOut(
                tag_id=t.tag_id,
                source_name=t.source_name,
                asset_code=t.asset_code,
                cycles=t.cycles,
                excluded=t.excluded,
                excluded_share=t.excluded_share,
                by_rule={r.value: n for r, n in t.by_rule.items()},
            )
            for t in report.tags
        ],
    )


def _preview(session: Session, body: RulesIn) -> PreviewReport:
    """Judged with the deployed models' training statistics, as scoring does (4.4)."""
    return preview_rules(
        session,
        _scope(body.scope),
        body.overrides,
        days=body.days,
        references=deployed_references(session, ModelCache()),
    )


@router.get("/rules", response_model=RuleSetOut, summary="Current overrides for a scope")
def get_rules(
    request: Request, user: User, scope: Annotated[str, Query(description=SCOPE_HELP)] = "global"
) -> RuleSetOut:
    try:
        with database_of(request).session() as session:
            rule_scope = _scope(scope)
            _visible_scope(session, user, rule_scope)
            return _rules_out(session, rule_scope)
    except DataQualityError as error:
        raise ProblemError(400, "dq_refused", "Data-quality request refused", str(error)) from None


@router.post("/rules/preview", response_model=PreviewOut, summary="Effect on recent data")
def post_preview(request: Request, user: User, body: RulesIn) -> PreviewOut:
    try:
        with database_of(request).session() as session:
            _visible_scope(session, user, _scope(body.scope))
            return _visible_tags(session, user, _preview_out(_preview(session, body)))
    except DataQualityError as error:
        raise ProblemError(400, "dq_refused", "Data-quality request refused", str(error)) from None


@router.put(
    "/rules",
    response_model=SavedOut,
    summary="Save new overrides (previewed first; a new audited version, from the next cycle)",
)
def put_rules(request: Request, user: User, body: RulesIn) -> SavedOut:
    try:
        with database_of(request).session() as session:
            scope = _scope(body.scope)
            authorize_rule_change(session, user.actor, scope)  # before showing any preview
            report = _preview(session, body)
            if report.warning and not body.confirm:
                raise ProblemError(
                    409,
                    "preview_warning",
                    "More than 20 % of some tag's data would be excluded",
                    "Check the preview and send confirm=true to save anyway (UC-04 3a).",
                    preview=_visible_tags(session, user, _preview_out(report)).model_dump(
                        mode="json"
                    ),
                )
            save_rule_set(session, user.actor, scope, body.overrides, body.comment)
            return SavedOut(
                rules=_rules_out(session, scope),
                preview=_visible_tags(session, user, _preview_out(report)),
            )
    except DataQualityError as error:
        raise ProblemError(400, "dq_refused", "Data-quality change refused", str(error)) from None
