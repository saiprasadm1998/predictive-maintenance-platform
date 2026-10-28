"""Time-to-threshold forecasts (plan 8.3, UC-11, FR-PRG-01, -02, ARC §7 POST /forecasts)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from pmp.api.common import can_see, not_found
from pmp.api.deps import SignedIn, database_of, settings_of, signed_in
from pmp.api.problems import ProblemError
from pmp.core import Settings
from pmp.modelling import ModelError, asset_path, get_model_by_id
from pmp.prognostics import (
    DEFAULT_WINDOW_DAYS,
    MAX_WINDOW_DAYS,
    ForecastError,
    ForecastRequest,
    ForecastView,
    Target,
    ThresholdKind,
    UrgencyBands,
    describe,
    get_forecast,
    list_forecasts,
    run_forecast,
)

router = APIRouter(prefix="/api/v1", tags=["prognostics"])
User = Annotated[SignedIn, Depends(signed_in)]


def bands_of(settings: Settings) -> UrgencyBands:
    return UrgencyBands(
        settings.forecast_immediate_h, settings.forecast_high_h, settings.forecast_medium_h
    )


class ForecastIn(BaseModel):
    model_id: int
    target: Literal["di", "actual", "residual"] = "di"
    tag_id: int | None = Field(default=None, description="the sensor, for actual and residual")
    threshold_kind: Literal["warning", "alert", "custom"] = Field(
        default="alert", description="the model's DI warning or alert limit, or a custom value"
    )
    threshold: float | None = Field(default=None, description="custom: in the target's units")
    direction: Literal["up", "down"] | None = Field(
        default=None, description="custom: an upper or lower limit (default: from the level)"
    )
    window_days: float = Field(default=DEFAULT_WINDOW_DAYS, ge=1, le=MAX_WINDOW_DAYS)
    alert_id: int | None = Field(
        default=None, description="store with this alert (default: the open alert on the target)"
    )


class FitOut(BaseModel):
    method: str | None = Field(description="linear or exponential; null without data")
    params: dict[str, float] = Field(
        description="linear y = a + b·t; exponential y = c + a·e^(b·t); t in days from `at`"
    )
    r2: float | None


class PointOut(BaseModel):
    ts: datetime
    value: float


class ForecastOut(BaseModel):
    id: int
    model_id: int
    version_id: int
    alert_id: int | None
    target: str
    tag_id: int | None
    tag: str | None
    threshold_kind: str
    threshold: float
    direction: Literal["up", "down"]
    window_days: float
    at: datetime = Field(description="the forecast time: crossing times count from here")
    fit: FitOut
    points: int = Field(description="15-minute means fitted")
    valid: bool
    reason: str | None = Field(description='why there is "No trend to threshold"')
    median_h: float | None = Field(description="median hours to threshold")
    lower_h: float | None = Field(description="10th percentile (80 % interval)")
    upper_h: float | None = Field(description="90th percentile; null: beyond reach")
    crossing_at: datetime | None
    urgency: str = Field(description="Immediate, High, Medium, Low or None")
    summary: str
    series: list[PointOut]
    created_at: datetime
    created_by: int | None


def forecast_out(v: ForecastView) -> ForecastOut:
    return ForecastOut(
        id=v.id,
        model_id=v.model_id,
        version_id=v.version_id,
        alert_id=v.alert_id,
        target=v.target.value,
        tag_id=v.tag_id,
        tag=v.source_name,
        threshold_kind=v.threshold_kind.value,
        threshold=v.threshold,
        direction="up" if v.direction > 0 else "down",
        window_days=v.window_days,
        at=v.at,
        fit=FitOut(method=v.method, params=v.params, r2=v.r2),
        points=v.points,
        valid=v.valid,
        reason=v.reason,
        median_h=v.median_h,
        lower_h=v.lower_h,
        upper_h=v.upper_h,
        crossing_at=v.crossing_at,
        urgency=v.urgency,
        summary=describe(v),
        series=[PointOut(ts=ts, value=y) for ts, y in v.series],
        created_at=v.created_at,
        created_by=v.created_by,
    )


def _problem(error: ForecastError) -> ProblemError:
    message = str(error)
    if "does not exist" in message:
        return not_found("Model or alert")
    return ProblemError(400, "forecast_refused", message)


def _visible_model(session: Session, user: SignedIn, model_id: int) -> None:
    try:
        model = get_model_by_id(session, model_id)
    except ModelError:
        raise not_found("Model") from None
    if not can_see(user, asset_path(session, model.asset_code)):
        raise not_found("Model")


@router.post(
    "/forecasts",
    response_model=ForecastOut,
    status_code=201,
    summary="Run a time-to-threshold forecast and store it with its alert (UC-11)",
)
def post_forecast(request: Request, user: User, body: ForecastIn) -> ForecastOut:
    run = ForecastRequest(
        model_id=body.model_id,
        target=Target(body.target),
        tag_id=body.tag_id,
        threshold_kind=ThresholdKind(body.threshold_kind),
        threshold=body.threshold,
        direction=None if body.direction is None else (1 if body.direction == "up" else -1),
        window_days=body.window_days,
        alert_id=body.alert_id,
    )
    try:
        with database_of(request).session() as session:
            view = run_forecast(session, user.actor, run, bands_of(settings_of(request)))
            return forecast_out(view)
    except ForecastError as error:
        raise _problem(error) from None


@router.get(
    "/forecasts",
    response_model=list[ForecastOut],
    summary="A model's or an alert's forecasts, newest first",
)
def get_forecasts(
    request: Request,
    user: User,
    model_id: int,
    alert_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[ForecastOut]:
    with database_of(request).session() as session:
        _visible_model(session, user, model_id)
        views = list_forecasts(session, model_id=model_id, alert_id=alert_id, limit=limit)
        return [forecast_out(v) for v in views]


@router.get("/forecasts/{forecast_id}", response_model=ForecastOut, summary="One forecast")
def get_one_forecast(request: Request, user: User, forecast_id: int) -> ForecastOut:
    with database_of(request).session() as session:
        try:
            view = get_forecast(session, forecast_id)
        except ForecastError:
            raise not_found("Forecast") from None
        _visible_model(session, user, view.model_id)
        return forecast_out(view)
