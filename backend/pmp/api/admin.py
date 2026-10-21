"""Administration: API keys and the audit log (UC-17, UC-19, FR-SEC-02, FR-AUD-01).

Administrators only; the services check it (ARC §9.2), so these handlers just translate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from pmp.api.deps import SignedIn, database_of, settings_of, signed_in
from pmp.api.problems import ProblemError
from pmp.core import (
    ApiKeyError,
    ApiKeyScope,
    ApiKeyView,
    AuditFilter,
    AuditView,
    Permission,
    RetentionError,
    RetentionPolicy,
    audit_csv,
    authorize,
    get_retention,
    issue_api_key,
    list_api_keys,
    query_audit,
    revoke_api_key,
    rotate_api_key,
    set_retention,
)

router = APIRouter(prefix="/api/v1", tags=["administration"])
User = Annotated[SignedIn, Depends(signed_in)]


class ApiKeyOut(BaseModel):
    id: int
    prefix: str
    name: str
    scope: ApiKeyScope
    created_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None


class NewApiKey(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scope: ApiKeyScope


class IssuedKeyOut(BaseModel):
    id: int
    key: str = Field(description="Shown once: copy it now. Only its hash is stored.")
    prefix: str


def _key_out(view: ApiKeyView) -> ApiKeyOut:
    return ApiKeyOut(**{f: getattr(view, f) for f in ApiKeyOut.model_fields})


def _key_problem(error: ApiKeyError) -> ProblemError:
    return ProblemError(400, "api_key_refused", "API key request refused", str(error))


@router.get("/api-keys", response_model=list[ApiKeyOut], summary="List API keys")
def get_api_keys(request: Request, user: User) -> list[ApiKeyOut]:
    with database_of(request).session() as session:
        return [_key_out(k) for k in list_api_keys(session, user.actor)]


@router.post("/api-keys", status_code=201, response_model=IssuedKeyOut, summary="Issue a key")
def post_api_key(request: Request, body: NewApiKey, user: User) -> IssuedKeyOut:
    try:
        with database_of(request).session() as session:
            issued = issue_api_key(session, user.actor, name=body.name, scope=body.scope)
    except ApiKeyError as error:
        raise _key_problem(error) from None
    return IssuedKeyOut(id=issued.id, key=issued.key, prefix=issued.prefix)


@router.post("/api-keys/{key_id}/revoke", status_code=204, summary="Revoke a key at once")
def post_revoke(request: Request, key_id: int, user: User) -> None:
    try:
        with database_of(request).session() as session:
            revoke_api_key(session, user.actor, key_id)
    except ApiKeyError as error:
        raise _key_problem(error) from None


@router.post(
    "/api-keys/{key_id}/rotate",
    status_code=201,
    response_model=IssuedKeyOut,
    summary="Issue a replacement; revoke the old key once the system has switched",
)
def post_rotate(request: Request, key_id: int, user: User) -> IssuedKeyOut:
    try:
        with database_of(request).session() as session:
            issued = rotate_api_key(session, user.actor, key_id)
    except ApiKeyError as error:
        raise _key_problem(error) from None
    return IssuedKeyOut(id=issued.id, key=issued.key, prefix=issued.prefix)


class AuditOut(BaseModel):
    id: int
    ts: datetime
    user_id: int | None
    actor_type: str
    entity: str
    entity_id: str
    action: str
    before: dict[str, object] | None
    after: dict[str, object] | None
    ip: str | None


class AuditPage(BaseModel):
    items: list[AuditOut]
    next_cursor: int | None = Field(description="Pass as `cursor` for the next (older) page")


def _filters(
    since: datetime | None,
    until: datetime | None,
    user_id: int | None,
    entity: str | None,
    entity_id: str | None,
) -> AuditFilter:
    for value in (since, until):
        if value is not None and value.tzinfo is None:
            raise ProblemError(400, "invalid_time", "Times need a time zone", "Use ISO 8601 UTC.")
    return AuditFilter(since, until, user_id, entity, entity_id)


def _audit_out(v: AuditView) -> AuditOut:
    return AuditOut(
        id=v.id,
        ts=v.ts,
        user_id=v.user_id,
        actor_type=v.actor_type,
        entity=v.entity,
        entity_id=v.entity_id,
        action=v.action,
        before=dict(v.before) if v.before is not None else None,
        after=dict(v.after) if v.after is not None else None,
        ip=v.ip,
    )


@router.get("/audit", response_model=AuditPage, summary="Search the audit trail (UC-19)")
def get_audit(
    request: Request,
    user: User,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
    user_id: int | None = None,
    entity: str | None = None,
    entity_id: str | None = None,
    cursor: int | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> AuditPage:
    filters = _filters(since, until, user_id, entity, entity_id)
    with database_of(request).session() as session:
        rows = query_audit(session, user.actor, filters, before_id=cursor, limit=limit)
    return AuditPage(
        items=[_audit_out(r) for r in rows],
        next_cursor=rows[-1].id if len(rows) == limit else None,
    )


@router.get("/audit.csv", response_class=PlainTextResponse, summary="Export the audit trail")
def get_audit_csv(
    request: Request,
    user: User,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
    user_id: int | None = None,
    entity: str | None = None,
    entity_id: str | None = None,
) -> PlainTextResponse:
    filters = _filters(since, until, user_id, entity, entity_id)
    with database_of(request).session() as session:
        rows = query_audit(session, user.actor, filters, limit=10_000)
    return PlainTextResponse(
        audit_csv(rows),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit.csv"'},
    )


class RetentionOut(BaseModel):
    raw_months: int = Field(description="samples, scores and sensor outputs (NFR-DATA-01)")
    aggregate_months: int = Field(description="hourly aggregates (ARC §6.3)")
    last_run_at: datetime | None
    last_result: str | None


class RetentionIn(BaseModel):
    raw_months: int = Field(ge=1, le=600)
    aggregate_months: int = Field(ge=1, le=1200)


def _retention_out(policy: RetentionPolicy) -> RetentionOut:
    return RetentionOut(
        raw_months=policy.raw_months,
        aggregate_months=policy.aggregate_months,
        last_run_at=policy.last_run_at,
        last_result=policy.last_result,
    )


@router.get("/retention", response_model=RetentionOut, summary="How long data is kept")
def get_retention_policy(request: Request, user: User) -> RetentionOut:
    authorize(user.actor, Permission.ADMINISTRATION, what="retention")
    with database_of(request).session() as session:
        return _retention_out(get_retention(session, settings_of(request).retention_months))


@router.put(
    "/retention",
    response_model=RetentionOut,
    summary="Change how long data is kept (applied by the worker's daily run)",
)
def put_retention_policy(request: Request, user: User, body: RetentionIn) -> RetentionOut:
    try:
        with database_of(request).session() as session:
            return _retention_out(
                set_retention(
                    session,
                    user.actor,
                    raw_months=body.raw_months,
                    aggregate_months=body.aggregate_months,
                    default_raw_months=settings_of(request).retention_months,
                )
            )
    except RetentionError as error:
        raise ProblemError(400, "invalid_retention", "Retention refused", str(error)) from None
