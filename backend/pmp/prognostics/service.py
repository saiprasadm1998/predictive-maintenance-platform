"""Running, storing and reading forecasts (UC-11, FR-PRG-01, -02).

A forecast is fitted to 15-minute means of a model's valid values over the fit window that
ends at the model's newest scored cycle: its DI, or a sensor's actual or residual. The
threshold is the model's DI warning or alert limit, or a custom value in the target's units
(tags carry no alarm or trip limits: decision 8.3). The result is stored with the alert it
was run for, or else with the model's open alert on the same target, so the alert list can
show its urgency.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pmp.alerting import AlertError, RuleKind, get_alert, list_alert_rules, list_alerts
from pmp.core import Actor, Permission, authorize
from pmp.modelling import ModelError, ModelView, VersionStatus, asset_path, get_model_by_id
from pmp.prognostics.domain import Forecast, ForecastError, UrgencyBands, forecast
from pmp.prognostics.models import ForecastRow
from pmp.scoring import latest_cycle, quarter_hour_means

DEFAULT_WINDOW_DAYS = 7.0
MAX_WINDOW_DAYS = 90.0
BIN = timedelta(minutes=15)


class Target(StrEnum):
    DI = "di"
    ACTUAL = "actual"
    RESIDUAL = "residual"


class ThresholdKind(StrEnum):
    WARNING = "warning"  # the model's DI warning limit
    ALERT = "alert"  # the model's DI alert limit
    CUSTOM = "custom"


@dataclass(frozen=True)
class ForecastRequest:
    model_id: int
    target: Target = Target.DI
    tag_id: int | None = None  # for actual and residual
    threshold_kind: ThresholdKind = ThresholdKind.ALERT
    threshold: float | None = None  # for custom
    direction: int | None = None  # custom: +1 upper, -1 lower; None: from the trend's level
    window_days: float = DEFAULT_WINDOW_DAYS
    alert_id: int | None = None


@dataclass(frozen=True)
class ForecastView:
    id: int
    model_id: int
    version_id: int
    alert_id: int | None
    target: Target
    tag_id: int | None
    source_name: str | None
    threshold_kind: ThresholdKind
    threshold: float
    direction: int
    window_days: float
    at: datetime  # the forecast time: crossing times count from here
    method: str | None
    params: dict[str, float]
    r2: float | None
    points: int
    valid: bool
    reason: str | None
    median_h: float | None
    lower_h: float | None
    upper_h: float | None
    urgency: str
    series: list[tuple[datetime, float]]
    created_at: datetime
    created_by: int | None

    @property
    def crossing_at(self) -> datetime | None:
        return None if self.median_h is None else self.at + timedelta(hours=self.median_h)


def _view(row: ForecastRow) -> ForecastView:
    return ForecastView(
        id=row.id,
        model_id=row.model_id,
        version_id=row.version_id,
        alert_id=row.alert_id,
        target=Target(row.target),
        tag_id=row.tag_id,
        source_name=row.series.get("source_name"),
        threshold_kind=ThresholdKind(row.threshold_kind),
        threshold=row.threshold,
        direction=row.direction,
        window_days=row.window_days,
        at=row.at,
        method=row.method,
        params={k: float(v) for k, v in row.params.items()},
        r2=row.r2,
        points=row.points,
        valid=row.valid,
        reason=row.reason,
        median_h=row.median_h,
        lower_h=row.lower_h,
        upper_h=row.upper_h,
        urgency=row.urgency,
        series=[
            (datetime.fromisoformat(ts), float(y))
            for ts, y in zip(row.series["ts"], row.series["y"], strict=True)
        ],
        created_at=row.created_at,
        created_by=row.created_by,
    )


def _scored_version(session: Session, model: ModelView) -> tuple[int, datetime]:
    """The version that scored the model's newest cycle, preferring the one in service."""
    in_service = [
        v for v in model.versions if v.status in (VersionStatus.DEPLOYED, VersionStatus.PAUSED)
    ]
    best: tuple[int, datetime] | None = None
    for v in in_service or list(reversed(model.versions)):
        found = latest_cycle(session, v.id)
        if found is not None and (best is None or found > best[1]):
            best = (v.id, found)
    if best is None:
        raise ForecastError("The model has not been scored yet")
    return best


def _threshold(session: Session, request: ForecastRequest) -> tuple[float, int | None]:
    if request.threshold_kind is ThresholdKind.CUSTOM:
        if request.threshold is None or not np.isfinite(request.threshold):
            raise ForecastError("Give the custom threshold")
        return float(request.threshold), request.direction
    if request.target is not Target.DI:
        raise ForecastError(
            "Sensor targets take a custom threshold in the sensor's units "
            "(the registry holds no alarm or trip limits)"
        )
    rules = [r for r in list_alert_rules(session, request.model_id) if r.spec.kind is RuleKind.DI]
    if not rules:
        raise ForecastError("The model has no DI alert rule")
    spec = rules[0].spec
    limit = spec.warning if request.threshold_kind is ThresholdKind.WARNING else spec.alert
    return float(limit), 1  # DI limits are upper limits


def _alert_for(session: Session, request: ForecastRequest) -> int | None:
    if request.alert_id is not None:
        try:
            alert = get_alert(session, request.alert_id)
        except AlertError:
            raise ForecastError(f"Alert {request.alert_id} does not exist") from None
        if alert.model_id != request.model_id:
            raise ForecastError(f"Alert {request.alert_id} belongs to another model")
        return alert.id
    kind = RuleKind.DI if request.target is Target.DI else RuleKind.SENSOR
    tag = None if request.target is Target.DI else request.tag_id
    matching = [
        a
        for a in list_alerts(session, model_id=request.model_id)
        if a.kind is kind and a.tag_id == tag
    ]
    return max(matching, key=lambda a: a.raised_at).id if matching else None


def run_forecast(
    session: Session,
    actor: Actor,
    request: ForecastRequest,
    bands: UrgencyBands | None = None,
) -> ForecastView:
    """UC-11: fit the target over the window, store the forecast with its alert."""
    try:
        model = get_model_by_id(session, request.model_id)
    except ModelError:  # authorised first, so a refused user learns nothing (decision 6.7)
        authorize(actor, Permission.RUN_FORECASTS, None, what="forecasts")
        raise ForecastError(f"Model {request.model_id} does not exist") from None
    authorize(
        actor,
        Permission.RUN_FORECASTS,
        asset_path(session, model.asset_code),
        what=f"forecasts on {model.asset_code}",
    )
    if not 1 <= request.window_days <= MAX_WINDOW_DAYS:
        raise ForecastError(f"The fit window is 1 to {MAX_WINDOW_DAYS:g} days")
    version_id, at = _scored_version(session, model)
    source_name = None
    if request.target is not Target.DI:
        version = next(v for v in model.versions if v.id == version_id)
        sensor = next((s for s in version.sensors if s.tag_id == request.tag_id), None)
        if sensor is None:
            raise ForecastError("Choose a sensor of the model for a sensor target")
        source_name = sensor.source_name
    threshold, direction = _threshold(session, request)
    alert_id = _alert_for(session, request)

    start = at - timedelta(days=request.window_days)
    means = quarter_hour_means(session, version_id, request.target.value, start, at, request.tag_id)
    times = [ts + BIN / 2 for ts, _ in means]  # a mean stands for its quarter hour's middle
    t_days = np.array([(ts - at).total_seconds() / 86_400 for ts in times])
    values = np.array([v for _, v in means])
    result: Forecast = forecast(t_days, values, threshold, direction=direction, bands=bands)

    row = ForecastRow(
        model_id=model.id,
        version_id=version_id,
        alert_id=alert_id,
        target=request.target.value,
        tag_id=request.tag_id if request.target is not Target.DI else None,
        threshold_kind=request.threshold_kind.value,
        threshold=threshold,
        direction=result.direction,
        window_days=request.window_days,
        at=at,
        method=result.fit.method.value if result.fit else None,
        params=dict(result.fit.params) if result.fit else {},
        r2=round(result.fit.r2, 4) if result.fit else None,
        points=result.points,
        valid=result.valid,
        reason=result.reason,
        median_h=result.median_h,
        lower_h=result.lower_h,
        upper_h=result.upper_h,
        urgency=result.urgency.value,
        series={
            "ts": [ts.isoformat() for ts in times],
            "y": [round(float(v), 6) for v in values],
            "source_name": source_name,
        },
        created_by=actor.user_id,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return _view(row)


def get_forecast(session: Session, forecast_id: int) -> ForecastView:
    row = session.get(ForecastRow, forecast_id)
    if row is None:
        raise ForecastError(f"Forecast {forecast_id} does not exist")
    return _view(row)


def list_forecasts(
    session: Session,
    *,
    model_id: int | None = None,
    alert_id: int | None = None,
    limit: int = 20,
) -> list[ForecastView]:
    """Newest first."""
    query = select(ForecastRow).order_by(ForecastRow.id.desc()).limit(limit)
    if model_id is not None:
        query = query.where(ForecastRow.model_id == model_id)
    if alert_id is not None:
        query = query.where(ForecastRow.alert_id == alert_id)
    return [_view(r) for r in session.scalars(query).all()]


def latest_for_alerts(session: Session, alert_ids: Iterable[int]) -> dict[int, ForecastView]:
    """The newest forecast stored with each alert (the alert list's urgency, FR-PRG-02)."""
    ids = sorted(set(alert_ids))
    if not ids:
        return {}
    newest = (
        select(func.max(ForecastRow.id))
        .where(ForecastRow.alert_id.in_(ids))
        .group_by(ForecastRow.alert_id)
    )
    rows = session.scalars(select(ForecastRow).where(ForecastRow.id.in_(newest))).all()
    return {r.alert_id: _view(r) for r in rows if r.alert_id is not None}


def describe(view: ForecastView, unit: str = "") -> str:
    """PDS §6 wording: "Reaches 90 °C in 4-9 days (median 6.5 d) at the current trend"."""
    if not view.valid or view.median_h is None or view.lower_h is None:
        return view.reason or "No trend to threshold"
    level = f"{view.threshold:g}{(' ' + unit) if unit else ''}"
    return (
        f"Reaches {level} in {interval_text(view.lower_h, view.upper_h)} "
        f"(median {median_text(view.median_h)}) at the current trend"
    )


def median_text(hours: float) -> str:
    """ "18 h", "6.5 d", "13 d" (the SCR-04 panel words it the same way)."""
    if hours < 1:
        return "now"
    if hours < 48:
        return f"{round(hours)} h"
    days = hours / 24
    return f"{days:.1f} d" if days < 10 else f"{round(days)} d"


def interval_text(lower: float, upper: float | None) -> str:
    """ "4-9 days", "6-30 h", "more than 40 d" (wireframes 02 and 04)."""
    dash = "\u2013"  # the PDS uses an en dash for ranges
    if upper is None:
        return f"more than {median_text(lower)}"
    if upper < 48:
        return f"{round(lower)}{dash}{round(upper)} h"
    return f"{math.floor(lower / 24)}{dash}{math.ceil(upper / 24)} days"
