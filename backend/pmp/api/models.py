"""Models with their versions, runtime status and alert rules; score and sensor-output
trends (ARC §7.3; FR-MOD-06, -07, FR-RUN-04, FR-VIS-02, NFR-PERF-03)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from pmp.alerting import (
    AlertRuleError,
    AlertState,
    list_alert_rules,
    require_di_rule,
    rule_states,
    rules_from_dict,
    set_alert_rules,
)
from pmp.api.common import can_see, not_found, utc
from pmp.api.deps import SignedIn, database_of, signed_in
from pmp.api.problems import ProblemError
from pmp.modelling import (
    Action,
    ModelError,
    ModelView,
    VersionView,
    asset_path,
    change_status,
    definition_from_dict,
    get_model_by_id,
    list_models,
    model_of_version,
    save_draft,
    start_training,
)
from pmp.scoring import (
    MAX_PX,
    RuntimeStatusView,
    Trend,
    TrendError,
    get_runtime_statuses,
    output_trends,
    score_trend,
)

router = APIRouter(prefix="/api/v1/models", tags=["models"])
User = Annotated[SignedIn, Depends(signed_in)]


class RuntimeOut(BaseModel):
    status: str
    reason: str | None
    since: datetime
    last_cycle: datetime | None
    version_id: int | None
    band: str
    di: float | None
    health: float | None


class VersionSummary(BaseModel):
    id: int
    version: int
    status: str
    algorithm: str
    created_at: datetime


class ModelOut(BaseModel):
    id: int
    asset_code: str
    name: str
    description: str
    latest: VersionSummary
    in_service: VersionSummary | None
    runtime: RuntimeOut | None


class SensorOut(BaseModel):
    tag_id: int
    source_name: str
    description: str
    required: bool


class PeriodOut(BaseModel):
    start: datetime
    end: datetime


class VersionOut(VersionSummary):
    sensors: list[SensorOut]
    training_periods: list[PeriodOut]
    validation_period: PeriodOut | None
    mode_filters: list[str]
    params: dict[str, Any]
    metrics: dict[str, Any] | None
    error: str | None
    artefact_sha256: str | None


class AlertRuleOut(BaseModel):
    id: int
    kind: str
    tag_id: int | None
    warning: float
    alert: float
    persistence_n: int
    persistence_m: int
    on_delay_s: int
    deadband: float
    clear_cycles: int
    enabled: bool
    state: str = Field(description="Normal, an open alert's state, or Out of service")


class ModelDetailOut(ModelOut):
    versions: list[VersionOut]
    alert_rules: list[AlertRuleOut]


def _summary(v: VersionView) -> VersionSummary:
    return VersionSummary(
        id=v.id,
        version=v.version,
        status=v.status.value,
        algorithm=v.algorithm,
        created_at=v.created_at,
    )


def _runtime(r: RuntimeStatusView | None) -> RuntimeOut | None:
    if r is None:
        return None
    return RuntimeOut(
        status=r.status.value,
        reason=r.reason,
        since=r.since,
        last_cycle=r.last_cycle,
        version_id=r.version_id,
        band=r.band.value,
        di=r.di,
        health=r.health,
    )


def _in_service(m: ModelView) -> VersionView | None:
    return next((v for v in m.versions if v.status.value in ("Deployed", "Paused")), None)


def _model_out(m: ModelView, runtime: RuntimeStatusView | None) -> ModelOut:
    current = _in_service(m)
    return ModelOut(
        id=m.id,
        asset_code=m.asset_code,
        name=m.name,
        description=m.description,
        latest=_summary(m.latest),
        in_service=_summary(current) if current else None,
        runtime=_runtime(runtime),
    )


def _visible_model(session: Session, user: SignedIn, model_id: int) -> ModelView:
    try:
        model = get_model_by_id(session, model_id)
    except ModelError:
        raise not_found("Model") from None
    if not can_see(user, asset_path(session, model.asset_code)):
        raise not_found("Model")
    return model


@router.get("", response_model=list[ModelOut], summary="Models with runtime status")
def get_models(
    request: Request,
    user: User,
    asset: Annotated[str | None, Query(description="asset code")] = None,
) -> list[ModelOut]:
    with database_of(request).session() as session:
        try:
            models = list_models(session, asset)
        except ModelError:
            raise not_found("Asset") from None
        runtimes = {r.model_id: r for r in get_runtime_statuses(session)}
        paths = {m.asset_code: asset_path(session, m.asset_code) for m in models}
    return [_model_out(m, runtimes.get(m.id)) for m in models if can_see(user, paths[m.asset_code])]


@router.get("/{model_id}", response_model=ModelDetailOut, summary="A model in full")
def get_model(request: Request, user: User, model_id: int) -> ModelDetailOut:
    with database_of(request).session() as session:
        model = _visible_model(session, user, model_id)
        runtime = next((r for r in get_runtime_statuses(session) if r.model_id == model_id), None)
        rules = list_alert_rules(session, model_id)
        states = rule_states(session, model_id)
    versions = [
        VersionOut(
            **_summary(v).model_dump(),
            sensors=[
                SensorOut(
                    tag_id=s.tag_id,
                    source_name=s.source_name,
                    description=s.description,
                    required=s.required,
                )
                for s in v.sensors
            ],
            training_periods=[PeriodOut(start=p.start, end=p.end) for p in v.training_periods],
            validation_period=(
                PeriodOut(start=v.validation_period.start, end=v.validation_period.end)
                if v.validation_period
                else None
            ),
            mode_filters=list(v.mode_filters),
            params=dict(v.params),
            metrics=dict(v.metrics) if v.metrics else None,
            error=v.error,
            artefact_sha256=v.artefact_sha256,
        )
        for v in model.versions
    ]
    return ModelDetailOut(
        **_model_out(model, runtime).model_dump(),
        versions=versions,
        alert_rules=[
            AlertRuleOut(
                id=r.id,
                kind=r.spec.kind.value,
                tag_id=r.spec.tag_id,
                warning=r.spec.warning,
                alert=r.spec.alert,
                persistence_n=r.spec.persistence_n,
                persistence_m=r.spec.persistence_m,
                on_delay_s=r.spec.on_delay_s,
                deadband=r.spec.deadband,
                clear_cycles=r.spec.clear_cycles,
                enabled=r.spec.enabled,
                state=states.get(r.id, AlertState.NORMAL).value,
            )
            for r in rules
        ],
    )


class TrendOut(BaseModel):
    start: datetime
    end: datetime
    raw: bool = Field(description="True: every cycle; False: min and max per bucket")
    bucket_s: float | None
    source: str = Field(description="raw, or hourly (the hourly aggregates, above 30 days)")
    ts: list[datetime]
    min: dict[str, list[float | None]]
    max: dict[str, list[float | None]]


class SensorTrendOut(TrendOut):
    tag_id: int
    source_name: str


def _period(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    end = utc(end, "to") or datetime.now(UTC)
    start = utc(start, "from") or end - timedelta(days=1)
    return start, end


def _trend_out(trend: Trend) -> dict[str, Any]:
    return {
        "start": trend.start,
        "end": trend.end,
        "raw": trend.raw,
        "bucket_s": trend.bucket_s,
        "source": trend.source,
        "ts": trend.ts,
        "min": trend.min,
        "max": trend.max,
    }


Px = Annotated[int, Query(ge=1, le=MAX_PX, description="chart width: at most this many points")]
From = Annotated[datetime | None, Query(alias="from", description="default: 1 day before `to`")]
To = Annotated[datetime | None, Query(alias="to", description="default: now")]


@router.get("/{model_id}/scores", response_model=TrendOut, summary="DI and Health trend")
def get_scores(
    request: Request,
    user: User,
    model_id: int,
    start: From = None,
    end: To = None,
    px: Px = 1000,
) -> TrendOut:
    begin, finish = _period(start, end)
    with database_of(request).session() as session:
        _visible_model(session, user, model_id)
        try:
            trend = score_trend(session, model_id, begin, finish, px)
        except TrendError as error:
            raise ProblemError(400, "invalid_period", "Invalid trend request", str(error)) from None
    return TrendOut(**_trend_out(trend))


@router.get(
    "/{model_id}/outputs",
    response_model=list[SensorTrendOut],
    summary="Actual, predicted, residual, q and z per sensor",
)
def get_outputs(
    request: Request,
    user: User,
    model_id: int,
    tags: Annotated[
        str | None, Query(description="comma-separated source names; default: all sensors")
    ] = None,
    start: From = None,
    end: To = None,
    px: Px = 1000,
) -> list[SensorTrendOut]:
    begin, finish = _period(start, end)
    with database_of(request).session() as session:
        model = _visible_model(session, user, model_id)
        sensors = {s.source_name: s.tag_id for v in model.versions for s in v.sensors}
        wanted = [t.strip() for t in tags.split(",") if t.strip()] if tags else list(sensors)
        unknown = [t for t in wanted if t not in sensors]
        if unknown:
            raise ProblemError(400, "unknown_tag", "Not sensors of this model", ", ".join(unknown))
        try:
            trends = output_trends(
                session,
                [v.id for v in model.versions],
                [sensors[t] for t in wanted],
                begin,
                finish,
                px,
            )
        except TrendError as error:
            raise ProblemError(400, "invalid_period", "Invalid trend request", str(error)) from None
    return [
        SensorTrendOut(tag_id=sensors[t], source_name=t, **_trend_out(trends[sensors[t]]))
        for t in wanted
    ]


# ------------------------------------------------------------------ changes (UC-05, UC-06)


class ModelIn(BaseModel):
    """A model definition, as in data/demo/models/k101.json: asset, name, sensors,
    training_periods, validation_period, mode_filters, params, alert_rules. Relative times
    such as "-30d" are resolved against now."""

    model_config = {"extra": "allow"}

    asset: str
    name: str


class AlertRulesIn(BaseModel):
    """{"di": {"warning": 15, "alert": 25, ...}, "sensors": [{"tag": ..., ...}]}"""

    di: dict[str, Any] | None = None
    sensors: list[dict[str, Any]] = Field(default_factory=list)


class QueuedTraining(BaseModel):
    version: VersionSummary
    job_id: int | None


def _model_problem(error: Exception) -> ProblemError:
    problems = getattr(error, "problems", None) or [str(error)]
    return ProblemError(
        400, "model_refused", "Model change refused", "; ".join(problems), problems=problems
    )


def _detail(request: Request, user: SignedIn, model_id: int) -> ModelDetailOut:
    return get_model(request, user, model_id)


@router.post("", status_code=201, response_model=ModelDetailOut, summary="Save a model (Draft)")
def post_model(request: Request, user: User, body: ModelIn) -> ModelDetailOut:
    data = body.model_dump()
    try:
        with database_of(request).session() as session:
            definition = definition_from_dict(data, datetime.now(UTC))
            model = save_draft(session, user.actor, definition)
            sensors = {s.source_name: s.tag_id for s in model.latest.sensors}
            set_alert_rules(
                session, user.actor, model.id, rules_from_dict(data.get("alert_rules"), sensors)
            )
            model_id = model.id
    except (ModelError, AlertRuleError) as error:
        raise _model_problem(error) from None
    return _detail(request, user, model_id)


@router.put(
    "/{model_id}/alert-rules", response_model=ModelDetailOut, summary="Replace the alert rules"
)
def put_alert_rules(
    request: Request, user: User, model_id: int, body: AlertRulesIn
) -> ModelDetailOut:
    try:
        with database_of(request).session() as session:
            model = _visible_model(session, user, model_id)
            sensors = {s.source_name: s.tag_id for s in model.latest.sensors}
            set_alert_rules(
                session, user.actor, model_id, rules_from_dict(body.model_dump(), sensors)
            )
    except AlertRuleError as error:
        raise _model_problem(error) from None
    return _detail(request, user, model_id)


@router.post(
    "/{model_id}/versions",
    status_code=202,
    response_model=QueuedTraining,
    summary="Train the Draft version (the worker runs the job)",
)
def post_training(request: Request, user: User, model_id: int) -> QueuedTraining:
    try:
        with database_of(request).session() as session:
            model = _visible_model(session, user, model_id)
            view, job_id = start_training(session, user.actor, model.asset_code, model.name)
    except ModelError as error:
        raise _model_problem(error) from None
    return QueuedTraining(version=_summary(view), job_id=job_id)


versions = APIRouter(prefix="/api/v1/versions", tags=["models"])


@versions.post(
    "/{version_id}/{action}",
    response_model=ModelDetailOut,
    summary="Lifecycle: deploy, pause, resume, retire or reject (ARC Figure 7)",
)
def post_lifecycle(request: Request, user: User, version_id: int, action: Action) -> ModelDetailOut:
    try:
        with database_of(request).session() as session:
            try:
                model = model_of_version(session, version_id)
            except ModelError:
                raise not_found("Model version") from None
            if not can_see(user, asset_path(session, model.asset_code)):
                raise not_found("Model version")
            number = next(v.version for v in model.versions if v.id == version_id)
            change_status(
                session,
                user.actor,
                model.asset_code,
                model.name,
                action,
                version=number,
                deploy_checks=(require_di_rule,),
            )
            model_id = model.id
    except (ModelError, AlertRuleError) as error:
        raise ProblemError(409, "invalid_transition", "Not possible", str(error)) from None
    return _detail(request, user, model_id)
