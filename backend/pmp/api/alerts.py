"""Alerts, the priority matrix and fleet KPIs (ARC §7.3; UC-10, FR-ALM-02, -03, -04,
FR-VIS-01).

Alert actions go through the alerting services, which check the user's role and scope
(ARC §9.2). Alerts on models outside the user's scope are left out of lists and are "not
found" when asked for by ID.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from pmp.alerting import (
    SORTS,
    AlertChanged,
    AlertError,
    AlertQuery,
    AlertState,
    AlertView,
    RuleKind,
    Severity,
    acknowledge,
    alert_counts,
    alert_history,
    cleared_times,
    get_alert,
    get_alerts,
    get_priority_matrix,
    persistence,
    search_alerts,
    set_priority,
    shelve,
    unshelve,
)
from pmp.api.common import (
    MAX_LIMIT,
    Page,
    can_see,
    decode_cursor,
    encode_cursor,
    not_found,
    utc,
)
from pmp.api.deps import SignedIn, database_of, settings_of, signed_in
from pmp.api.problems import ProblemError
from pmp.core import user_names
from pmp.dataquality import get_sensor_statuses
from pmp.modelling import list_active_versions, model_assets, version_numbers
from pmp.prognostics import latest_for_alerts
from pmp.registry import AssetView, find_asset, get_tags, list_subtree, list_tags
from pmp.scoring import get_runtime_statuses, health_tree

router = APIRouter(prefix="/api/v1", tags=["alerts"])
User = Annotated[SignedIn, Depends(signed_in)]


class _Model:
    def __init__(self, name: str, asset_id: int, asset_code: str, asset_path: str) -> None:
        self.name, self.asset_id, self.asset_code = name, asset_id, asset_code
        self.asset_path = asset_path


def _path_label(asset: AssetView, assets: dict[int, AssetView]) -> str:
    """ "Site A / Ammonia unit / K-101": the names above the asset, below the top of the
    hierarchy, then its code (wireframe 02)."""
    ids = [int(x) for x in asset.path.split(".")]
    above = [assets[i].name for i in ids[1:-1] if i in assets]
    return " / ".join([*above, asset.code])


def visible_models(session: Session, user: SignedIn) -> dict[int, _Model]:
    """Models whose asset the user may see, with their asset's ID, code and path."""
    assets = {a.id: a for a in list_subtree(session)}
    out = {}
    for model_id, (asset_id, name) in model_assets(session).items():
        asset = assets.get(asset_id)
        if asset is not None and can_see(user, asset.path):
            out[model_id] = _Model(name, asset_id, asset.code, _path_label(asset, assets))
    return out


class AlertOut(BaseModel):
    id: int
    model_id: int
    model: str
    asset_id: int
    asset_code: str
    kind: str = Field(description="di or sensor")
    tag_id: int | None
    tag: str | None
    state: str
    severity: str
    priority: str | None = Field(description="null while out of service")
    raised_at: datetime
    condition_active: bool
    ack_at: datetime | None
    shelved_until: datetime | None
    shelve_reason: str | None
    closed_at: datetime | None
    cleared_at: datetime | None = Field(
        default=None, description="when the condition returned to normal (null while active)"
    )
    asset_path: str = Field(default="", description="e.g. Site A / Ammonia unit / K-101")
    version: int | None = Field(default=None, description="model version that raised it")
    di: float | None = Field(default=None, description="the model's latest DI")
    health: float | None = Field(default=None, description="the model's latest Health")
    persistence_n: int | None = Field(
        default=None, description="of the rule's last m cycles, how many met the severity"
    )
    persistence_m: int | None = None
    forecast_urgency: str | None = Field(
        default=None, description="the newest forecast stored with the alert (FR-PRG-02)"
    )
    forecast_lower_h: float | None = Field(default=None, description="its 80 % interval")
    forecast_upper_h: float | None = None


class HistoryOut(BaseModel):
    ts: datetime
    action: str
    from_state: str | None
    to_state: str
    severity: str
    priority: str
    user_id: int | None
    user: str | None = Field(default=None, description="username; null for the system")
    comment: str | None


class AlertDetailOut(AlertOut):
    trace: dict[str, Any] = Field(description="What the alert was based on (NFR-ACC-01)")
    history: list[HistoryOut]


def _outs(session: Session, views: list[AlertView], models: dict[int, _Model]) -> list[AlertOut]:
    tags = {t.id: t.source_name for t in get_tags(session, {v.tag_id for v in views if v.tag_id})}
    cleared = cleared_times(session, [v.id for v in views if not v.condition_active])
    numbers = version_numbers(session, {v.version_id for v in views})
    runtimes = {r.model_id: r for r in get_runtime_statuses(session)} if views else {}
    persisted = persistence(session, [v.id for v in views])
    forecasts = latest_for_alerts(session, [v.id for v in views])
    return [
        AlertOut(
            id=v.id,
            model_id=v.model_id,
            model=models[v.model_id].name,
            asset_id=models[v.model_id].asset_id,
            asset_code=models[v.model_id].asset_code,
            kind=v.kind.value,
            tag_id=v.tag_id,
            tag=tags.get(v.tag_id) if v.tag_id else None,
            state=v.state.value,
            severity=v.severity.value,
            priority=v.priority,
            raised_at=v.raised_at,
            condition_active=v.condition_active,
            ack_at=v.ack_at,
            shelved_until=v.shelved_until,
            shelve_reason=v.shelve_reason,
            closed_at=v.closed_at,
            cleared_at=cleared.get(v.id) if not v.condition_active else None,
            asset_path=models[v.model_id].asset_path,
            version=numbers.get(v.version_id),
            di=runtimes[v.model_id].di if v.model_id in runtimes else None,
            health=runtimes[v.model_id].health if v.model_id in runtimes else None,
            persistence_n=persisted[v.id][0] if v.id in persisted else None,
            persistence_m=persisted[v.id][1] if v.id in persisted else None,
            forecast_urgency=forecasts[v.id].urgency if v.id in forecasts else None,
            forecast_lower_h=forecasts[v.id].lower_h if v.id in forecasts else None,
            forecast_upper_h=forecasts[v.id].upper_h if v.id in forecasts else None,
        )
        for v in views
    ]


@router.get("/alerts", response_model=Page[AlertOut], summary="The alert list (FR-ALM-03)")
def list_alert_page(
    request: Request,
    user: User,
    state: Annotated[list[AlertState] | None, Query()] = None,
    priority: Annotated[list[str] | None, Query()] = None,
    severity: Annotated[list[Severity] | None, Query()] = None,
    kind: RuleKind | None = None,
    asset: Annotated[str | None, Query(description="asset code: alerts at or below it")] = None,
    model_id: int | None = None,
    include_closed: bool = False,
    raised_after: Annotated[datetime | None, Query(description="age: raised at or after")] = None,
    raised_before: Annotated[datetime | None, Query(description="age: raised before")] = None,
    sort: Annotated[
        str,
        Query(description="default (PDS §4.2), newest, oldest, priority or severity"),
    ] = "default",
    scope: Annotated[str | None, Query(description="asset code (ARC §7.3 name)")] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 100,
) -> Page[AlertOut]:
    """Unacknowledged first, then priority, then age; out of service last (PDS §4.2);
    or sorted by age, priority or severity (FR-ALM-03)."""
    asset = asset or scope
    if sort not in SORTS:
        raise ProblemError(400, "invalid_sort", "Unknown sort", f"Use one of {', '.join(SORTS)}.")
    with database_of(request).session() as session:
        models = visible_models(session, user)
        ids = set(models)
        if asset is not None:
            if find_asset(session, asset) is None:
                raise not_found("Asset")
            subtree = {a.id for a in list_subtree(session, asset)}
            ids = {m for m in ids if models[m].asset_id in subtree}
        if model_id is not None:
            ids &= {model_id}
        query = AlertQuery(
            open_only=not include_closed,
            model_ids=tuple(sorted(ids)),
            states=tuple(state or ()),
            priorities=tuple(priority or ()),
            severities=tuple(severity or ()),
            kind=kind,
            raised_after=utc(raised_after, "raised_after"),
            raised_before=utc(raised_before, "raised_before"),
            sort=sort,
        )
        after = decode_cursor(cursor) if cursor else None
        try:
            views, last = search_alerts(session, query, after=after, limit=limit)
        except AlertError as error:
            raise ProblemError(400, "invalid_cursor", "Invalid request", str(error)) from None
        items = _outs(session, views, models)
    return Page[AlertOut](items=items, next_cursor=encode_cursor(last) if last else None)


def _visible_alert(session: Session, user: SignedIn, alert_id: int) -> AlertView:
    try:
        view = get_alert(session, alert_id)
    except AlertError:
        raise not_found("Alert") from None
    if view.model_id not in visible_models(session, user):
        raise not_found("Alert")
    return view


class AlertSettingsOut(BaseModel):
    max_shelve_days: int


@router.get(
    "/alerts/settings", response_model=AlertSettingsOut, summary="Limits the alert panel needs"
)
def get_alert_settings(request: Request, user: User) -> AlertSettingsOut:
    return AlertSettingsOut(max_shelve_days=settings_of(request).alert_max_shelve_days)


@router.get("/alerts/{alert_id}", response_model=AlertDetailOut, summary="One alert in full")
def get_one_alert(request: Request, user: User, alert_id: int) -> AlertDetailOut:
    with database_of(request).session() as session:
        view = _visible_alert(session, user, alert_id)
        (base,) = _outs(session, [view], visible_models(session, user))
        events = alert_history(session, alert_id)
        names = user_names(session, {e.user_id for e in events if e.user_id is not None})
        history = [
            HistoryOut(
                ts=e.ts,
                action=e.action,
                from_state=e.from_state,
                to_state=e.to_state,
                severity=e.severity,
                priority=e.priority,
                user_id=e.user_id,
                user=names.get(e.user_id) if e.user_id is not None else None,
                comment=e.comment,
            )
            for e in events
        ]
    return AlertDetailOut(**base.model_dump(), trace=dict(view.trace), history=history)


class AckIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=1000)
    comment: str | None = Field(default=None, max_length=2000)


class ShelveIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=2000)
    minutes: int = Field(gt=0, description="how long; at most the configured maximum (7 days)")


class IdsIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=1000)


class CommentIn(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class ShelveOneIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    minutes: int = Field(gt=0)


def _act(request: Request, user: SignedIn, ids: list[int], action: Any) -> list[AlertOut]:
    """Run an alert action on every ID or none (UC-10 bulk actions are all or nothing)."""
    try:
        with database_of(request).session() as session:
            models = visible_models(session, user)
            try:
                targets = get_alerts(session, ids)
            except AlertError:
                raise not_found("Alert") from None
            if any(v.model_id not in models for v in targets):
                raise not_found("Alert")
            changes: list[AlertChanged] = action(session, datetime.now(UTC))
            views = get_alerts(session, [c.alert_id for c in changes])
            return _outs(session, views, models)
    except AlertError as error:
        raise ProblemError(
            409, "invalid_state", "Not possible in the alert's state", str(error)
        ) from None


@router.post("/alerts/ack", response_model=list[AlertOut], summary="Acknowledge alerts")
def post_ack(request: Request, user: User, body: AckIn) -> list[AlertOut]:
    return _act(
        request,
        user,
        body.ids,
        lambda s, now: acknowledge(s, user.actor, body.ids, now, body.comment),
    )


@router.post("/alerts/shelve", response_model=list[AlertOut], summary="Shelve alerts")
def post_shelve(request: Request, user: User, body: ShelveIn) -> list[AlertOut]:
    return _shelve(request, user, body.ids, body.reason, body.minutes)


@router.post("/alerts/unshelve", response_model=list[AlertOut], summary="End shelving early")
def post_unshelve(request: Request, user: User, body: IdsIn) -> list[AlertOut]:
    return _act(request, user, body.ids, lambda s, now: unshelve(s, user.actor, body.ids, now))


@router.post("/alerts/{alert_id}/ack", response_model=list[AlertOut], summary="Acknowledge")
def post_ack_one(
    request: Request, user: User, alert_id: int, body: CommentIn | None = None
) -> list[AlertOut]:
    comment = body.comment if body else None
    return _act(
        request,
        user,
        [alert_id],
        lambda s, now: acknowledge(s, user.actor, [alert_id], now, comment),
    )


@router.post("/alerts/{alert_id}/shelve", response_model=list[AlertOut], summary="Shelve")
def post_shelve_one(
    request: Request, user: User, alert_id: int, body: ShelveOneIn
) -> list[AlertOut]:
    return _shelve(request, user, [alert_id], body.reason, body.minutes)


@router.post("/alerts/{alert_id}/unshelve", response_model=list[AlertOut], summary="Unshelve")
def post_unshelve_one(request: Request, user: User, alert_id: int) -> list[AlertOut]:
    return _act(request, user, [alert_id], lambda s, now: unshelve(s, user.actor, [alert_id], now))


def _shelve(
    request: Request, user: SignedIn, ids: list[int], reason: str, minutes: int
) -> list[AlertOut]:
    maximum = timedelta(days=settings_of(request).alert_max_shelve_days)
    return _act(
        request,
        user,
        ids,
        lambda s, now: shelve(
            s,
            user.actor,
            ids,
            now,
            reason=reason,
            duration=timedelta(minutes=minutes),
            max_duration=maximum,
        ),
    )


# ------------------------------------------------------------------ priority matrix


class PriorityCell(BaseModel):
    criticality: str = Field(pattern="^[ABC]$")
    severity: Severity
    priority: str = Field(pattern="^P[1-4]$")


@router.get("/priority-matrix", response_model=list[PriorityCell], summary="FR-ALM-04")
def get_matrix(request: Request, user: User) -> list[PriorityCell]:
    with database_of(request).session() as session:
        matrix = get_priority_matrix(session)
    return [
        PriorityCell(criticality=c, severity=s, priority=p)
        for (c, s), p in sorted(matrix.items(), key=lambda kv: (kv[0][0], kv[0][1].value))
    ]


@router.put(
    "/priority-matrix",
    response_model=list[AlertOut],
    summary="Change one cell; open alerts it covers are re-prioritised",
)
def put_matrix(request: Request, user: User, body: PriorityCell) -> list[AlertOut]:
    try:
        with database_of(request).session() as session:
            changes = set_priority(
                session,
                user.actor,
                body.criticality,
                body.severity,
                body.priority,
                datetime.now(UTC),
            )
            models = visible_models(session, user)
            views = get_alerts(session, [c.alert_id for c in changes])
            return _outs(session, [v for v in views if v.model_id in models], models)
    except AlertError as error:
        raise ProblemError(400, "invalid_priority", "Invalid priority", str(error)) from None


# ------------------------------------------------------------------ fleet KPIs


class FleetKpis(BaseModel):
    assets_by_band: dict[str, int] = Field(description="monitored assets by their own band")
    open_alerts: dict[str, int] = Field(description="by priority (out of service excluded)")
    unacknowledged_alerts: dict[str, int]
    sensors_by_status: dict[str, int] = Field(description="NE 107 status of every sensor")
    models_by_status: dict[str, int] = Field(description="runtime status of deployed models")
    stale_models: list[int] = Field(
        description="deployed models with no cycle for 3 cycles (stale-data banner, SCR-01)"
    )
    last_cycle: datetime | None = Field(
        default=None, description="the newest scoring cycle of a visible model (live indicator)"
    )


@router.get("/fleet/kpis", response_model=FleetKpis, summary="Fleet overview figures (SCR-01)")
def get_kpis(request: Request, user: User) -> FleetKpis:
    now = datetime.now(UTC)
    with database_of(request).session() as session:
        models = visible_models(session, user)
        assets = list_subtree(session)
        ids = {a.id for a in assets if can_see(user, a.path)}
        roots = [a for a in assets if a.id in ids and a.parent_id not in ids]
        bands: Counter[str] = Counter()
        for root in roots:
            for node in health_tree(session, root.code):
                bands.update({b.value: n for b, n in node.counts.items()})
        counts = alert_counts(session, sorted(models))
        paths = {a.id: a.path for a in assets}
        tag_ids = [t.id for t in list_tags(session) if can_see(user, paths.get(t.asset_id))]
        sensors = Counter(v.status.value for v in get_sensor_statuses(session, tag_ids))
        runtimes = {r.model_id: r for r in get_runtime_statuses(session)}
        deployed = [
            v
            for v in list_active_versions(session)
            if v.model_id in models and v.status.value == "Deployed"
        ]
    statuses = Counter(
        runtimes[v.model_id].status.value if v.model_id in runtimes else "Not scored yet"
        for v in deployed
    )
    stale = [
        v.model_id
        for v in deployed
        if (r := runtimes.get(v.model_id)) is None
        or r.last_cycle is None
        or now - r.last_cycle > timedelta(seconds=3 * v.cycle_s + 60)
    ]
    cycles = [r.last_cycle for m, r in runtimes.items() if m in models and r.last_cycle]
    return FleetKpis(
        last_cycle=max(cycles, default=None),
        assets_by_band=dict(bands),
        open_alerts=counts["open"],
        unacknowledged_alerts=counts["unacknowledged"],
        sensors_by_status=dict(sensors),
        models_by_status=dict(statuses),
        stale_models=sorted(stale),
    )
