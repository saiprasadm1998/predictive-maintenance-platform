"""Results for plant systems (FR-API-02, ARC §7.2, plan 8.7).

GET /api/v1/results/health?scope=<asset code>   current health of every model in service

Authentication: a `results-read` API key only (ARC §8, conduit C1). One call returns
every model, as of its latest cycle, so a gateway can write them back to the DCS.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from pmp.alerting import AlertState, list_alerts
from pmp.api.common import not_found
from pmp.api.deps import authenticate_api_key, database_of
from pmp.core import ApiKeyScope
from pmp.ingestion import server_now
from pmp.modelling import list_active_versions
from pmp.prognostics import latest_for_alerts
from pmp.registry import RegistryError, list_subtree
from pmp.scoring import get_runtime_statuses, model_healths

router = APIRouter(prefix="/api/v1/results", tags=["results"])
URGENCY_ORDER = ("Immediate", "High", "Medium", "Low")
ACTIVE = (AlertState.ACTIVE_UNACK, AlertState.ACTIVE_ACK)


class ModelResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    asset: str
    model: str = Field(description="model name and version, e.g. 'main v3'")
    model_id: int = Field(alias="modelId")
    health: float | None
    di: float | None
    band: str = Field(description="Healthy, Watch, Alert or Unknown")
    status: str | None = Field(description="runtime status; null: deployed, not scored yet")
    last_cycle: datetime | None = Field(alias="lastCycle")
    active_alerts: int = Field(alias="activeAlerts")
    urgency: str | None = Field(description="the most urgent forecast of its open alerts")


class HealthResults(BaseModel):
    ts: datetime = Field(description="when the results were read (server clock)")
    models: list[ModelResult]


def _results(session: Session, scope: str | None) -> HealthResults:
    try:
        assets = {a.id: a.code for a in list_subtree(session, scope)}
    except RegistryError:
        raise not_found("Asset") from None
    versions = {v.model_id: v for v in list_active_versions(session)}
    di = {s.model_id: s.di for s in get_runtime_statuses(session)}
    open_alerts = list_alerts(session, open_only=True)
    forecasts = latest_for_alerts(session, [a.id for a in open_alerts])
    active: dict[int, int] = {}
    urgencies: dict[int, list[str]] = {}
    for alert in open_alerts:
        if alert.state in ACTIVE:
            active[alert.model_id] = active.get(alert.model_id, 0) + 1
        if alert.id in forecasts and forecasts[alert.id].urgency in URGENCY_ORDER:
            urgencies.setdefault(alert.model_id, []).append(forecasts[alert.id].urgency)
    models = []
    for h in model_healths(session):
        if h.asset_id not in assets:
            continue
        version = versions.get(h.model_id)
        found = urgencies.get(h.model_id)
        current_di = di.get(h.model_id) if h.health is not None else None  # Unknown: no DI
        models.append(
            ModelResult(
                asset=assets[h.asset_id],
                model=f"{h.name} v{version.version}" if version else h.name,
                model_id=h.model_id,
                health=None if h.health is None else round(h.health, 1),
                di=None if current_di is None else round(current_di, 2),
                band=h.band.value,
                status=h.status.value if h.status else None,
                last_cycle=h.last_cycle,
                active_alerts=active.get(h.model_id, 0),
                urgency=min(found, key=URGENCY_ORDER.index) if found else None,
            )
        )
    models.sort(key=lambda m: (m.asset, m.model))
    return HealthResults(ts=server_now(session), models=models)


@router.get(
    "/health",
    response_model=HealthResults,
    response_model_by_alias=True,
    summary="Current health of every model in service (results-read API key)",
)
async def get_results_health(
    request: Request,
    scope: str | None = Query(default=None, description="an asset code: it and beneath it"),
) -> HealthResults:
    await run_in_threadpool(authenticate_api_key, request, ApiKeyScope.RESULTS_READ)

    def read() -> HealthResults:
        with database_of(request).session() as session:
            return _results(session, scope)

    return await run_in_threadpool(read)
