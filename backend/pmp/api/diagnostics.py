"""Failure-mode library and diagnostics (plan 8.2, UC-09 step 4, UC-16, SCR-04, SCR-12)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from pmp.api.common import can_see, not_found, utc
from pmp.api.deps import SignedIn, database_of, signed_in
from pmp.api.problems import ProblemError
from pmp.diagnostics import (
    Direction,
    LibraryError,
    ModeSpec,
    ModeView,
    Symptom,
    diagnose,
    list_modes,
    mode_history,
    retire_mode,
    save_mode,
)
from pmp.modelling import ModelError, asset_path, get_model_by_id

router = APIRouter(prefix="/api/v1", tags=["diagnostics"])
User = Annotated[SignedIn, Depends(signed_in)]


class SymptomBody(BaseModel):
    role: str = Field(description="the asset type's role, e.g. thrust_pad_temp")
    direction: Literal["up", "down", "any"]
    weight: float = Field(gt=0)


class ModeIn(BaseModel):
    asset_type: str
    code: str = Field(description="lower-case letters, digits and underscores")
    name: str
    iso_code: str | None = Field(default=None, description="ISO 14224 failure mode code")
    description: str = ""
    symptoms: list[SymptomBody]
    tasks: list[str] = Field(default_factory=list, description="recommended tasks (FR-ADV-01)")
    comment: str = Field(default="", description="kept with the version")


class ModeOut(BaseModel):
    id: int
    asset_type: str
    code: str
    version: int
    name: str
    iso_code: str | None
    description: str
    symptoms: list[SymptomBody]
    tasks: list[str]
    comment: str
    updated_at: datetime
    updated_by: int | None
    retired_at: datetime | None


def _out(v: ModeView) -> ModeOut:
    return ModeOut(
        id=v.id,
        asset_type=v.asset_type,
        code=v.spec.code,
        version=v.version,
        name=v.spec.name,
        iso_code=v.spec.iso_code,
        description=v.spec.description,
        symptoms=[
            SymptomBody(role=s.role, direction=s.direction.value, weight=s.weight)
            for s in v.spec.symptoms
        ],
        tasks=list(v.spec.tasks),
        comment=v.comment,
        updated_at=v.updated_at,
        updated_by=v.updated_by,
        retired_at=v.retired_at,
    )


def _problem(error: LibraryError) -> ProblemError:
    message = str(error)
    if "does not exist" in message:
        return not_found("Failure mode, asset type or model")
    return ProblemError(400, "library_refused", message)


@router.get("/library", response_model=list[ModeOut], summary="Failure modes (SCR-12)")
def get_library(
    request: Request,
    user: User,
    asset_type: str | None = None,
    include_retired: bool = False,
) -> list[ModeOut]:
    try:
        with database_of(request).session() as session:
            modes = list_modes(session, asset_type, include_retired=include_retired)
    except LibraryError as error:
        raise _problem(error) from None
    return [_out(m) for m in modes]


@router.get(
    "/library/{mode_id}/versions",
    response_model=list[ModeOut],
    summary="Every version of a failure mode, newest first",
)
def get_mode_versions(request: Request, user: User, mode_id: int) -> list[ModeOut]:
    try:
        with database_of(request).session() as session:
            versions = mode_history(session, mode_id)
    except LibraryError as error:
        raise _problem(error) from None
    return [_out(m) for m in versions]


@router.put(
    "/library",
    response_model=ModeOut,
    summary="Create a failure mode or save a new version of it (UC-16; unchanged: no version)",
)
def put_mode(request: Request, user: User, body: ModeIn) -> ModeOut:
    spec = ModeSpec(
        code=body.code,
        name=body.name,
        symptoms=tuple(Symptom(s.role, Direction(s.direction), s.weight) for s in body.symptoms),
        tasks=tuple(body.tasks),
        iso_code=body.iso_code,
        description=body.description,
    )
    try:
        with database_of(request).session() as session:
            saved = save_mode(session, user.actor, body.asset_type, spec, body.comment)
    except LibraryError as error:
        raise _problem(error) from None
    return _out(saved)


@router.post(
    "/library/{mode_id}/retire",
    response_model=ModeOut,
    summary="Take a failure mode out of diagnostics (its versions stay)",
)
def post_retire(request: Request, user: User, mode_id: int) -> ModeOut:
    try:
        with database_of(request).session() as session:
            retired = retire_mode(session, user.actor, mode_id, datetime.now(UTC))
    except LibraryError as error:
        raise _problem(error) from None
    return _out(retired)


class SymptomOut(BaseModel):
    role: str
    direction: str
    weight: float
    tag_id: int | None
    source_name: str | None
    z: float | None
    z_ref: float | None
    g: float | None = Field(description="agreement 0 to 1 (UCS §6.7.2); null: not evaluated")
    result: str = Field(description="match, partial, no match or not evaluated")


class TrendPoint(BaseModel):
    ts: datetime
    score: float | None = Field(description="null: insufficient evidence then")


class ModeMatchOut(BaseModel):
    mode: ModeOut
    score: float | None = Field(description="0 to 100, a relative match, not a probability")
    insufficient_evidence: bool
    evaluated_weight: float
    total_weight: float
    symptoms: list[SymptomOut]
    trend: list[TrendPoint]


class DiagnosisOut(BaseModel):
    model_id: int
    asset_code: str
    asset_type: str | None
    version_id: int | None
    at: datetime | None = Field(description="the cycle matched; null: never scored")
    note: str = "Relative match, not probability: the score ranks failure modes."
    modes: list[ModeMatchOut]


@router.get(
    "/models/{model_id}/diagnostics",
    response_model=DiagnosisOut,
    summary="Failure-mode match scores at the latest cycle or a chosen time (SCR-04)",
)
def get_diagnostics(
    request: Request,
    user: User,
    model_id: int,
    at: Annotated[datetime | None, Query(description="the cycle at or before this time")] = None,
) -> DiagnosisOut:
    at = utc(at, "at")
    with database_of(request).session() as session:
        try:
            model = get_model_by_id(session, model_id)
        except ModelError:
            raise not_found("Model") from None
        if not can_see(user, asset_path(session, model.asset_code)):
            raise not_found("Model")
        try:
            result = diagnose(session, model_id, at)
        except LibraryError as error:
            raise _problem(error) from None
    return DiagnosisOut(
        model_id=result.model_id,
        asset_code=result.asset_code,
        asset_type=result.asset_type,
        version_id=result.version_id,
        at=result.at,
        modes=[
            ModeMatchOut(
                mode=_out(d.mode),
                score=None if d.match.score is None else round(d.match.score, 1),
                insufficient_evidence=d.match.insufficient,
                evaluated_weight=d.match.evaluated_weight,
                total_weight=d.match.total_weight,
                symptoms=[
                    SymptomOut(
                        role=s.symptom.role,
                        direction=s.symptom.direction.value,
                        weight=s.symptom.weight,
                        tag_id=s.reading.tag_id if s.reading else None,
                        source_name=s.reading.source_name if s.reading else None,
                        z=s.reading.z if s.reading else None,
                        z_ref=s.reading.z_ref if s.reading else None,
                        g=None if s.g is None else round(s.g, 3),
                        result=s.result.value,
                    )
                    for s in d.match.symptoms
                ],
                trend=[
                    TrendPoint(ts=ts, score=None if v is None else round(v, 1)) for ts, v in d.trend
                ],
            )
            for d in result.modes
        ],
    )
