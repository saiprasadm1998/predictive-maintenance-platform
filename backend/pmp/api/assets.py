"""The asset hierarchy with health, tags, asset types and sensor health (ARC §7.3;
UC-08, FR-HLT-01, FR-REG-01, FR-DQ-02)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from pmp.alerting import open_alerts_by_model
from pmp.api.common import MAX_LIMIT, Page, can_see, not_found, page
from pmp.api.deps import SignedIn, database_of, signed_in
from pmp.dataquality import get_sensor_statuses
from pmp.modelling import model_assets
from pmp.registry import (
    AssetView,
    RegistryError,
    TagView,
    find_asset,
    get_asset_by_id,
    list_ancestors,
    list_asset_types,
    list_subtree,
    list_tags,
)
from pmp.scoring import ModelHealth, NodeHealth, health_tree

router = APIRouter(prefix="/api/v1", tags=["assets"])
User = Annotated[SignedIn, Depends(signed_in)]


class ModelHealthOut(BaseModel):
    model_id: int
    name: str
    band: str
    health: float | None
    status: str | None
    reason: str | None
    last_cycle: datetime | None


class AssetNodeOut(BaseModel):
    id: int
    code: str
    name: str
    level: str
    criticality: str | None
    asset_type: str | None = Field(default=None, description="asset type code")
    asset_type_name: str | None = None
    open_alerts: int = Field(
        default=0, description="open alerts at or beneath this asset (out of service left out)"
    )
    band: str | None
    health: float | None
    counts: dict[str, int]
    worst: str | None
    models: list[ModelHealthOut]
    children: list[AssetNodeOut]


class AssetOut(BaseModel):
    id: int
    code: str
    name: str
    level: str
    parent_id: int | None
    criticality: str | None
    asset_type: str | None
    description: str


class Crumb(BaseModel):
    id: int
    code: str
    name: str


class AssetDetailOut(AssetOut):
    ancestors: list[Crumb]
    health: AssetNodeOut


def _model_out(m: ModelHealth) -> ModelHealthOut:
    return ModelHealthOut(
        model_id=m.model_id,
        name=m.name,
        band=m.band.value,
        health=m.health,
        status=m.status.value if m.status else None,
        reason=m.why,
        last_cycle=m.last_cycle,
    )


@dataclass(frozen=True)
class _Extras:
    """Per-asset facts the roll-up does not carry: type and open alerts."""

    types: dict[int, tuple[str, str]]  # asset ID: (type code, type name)
    alerts: dict[int, int]  # asset ID: open alerts on its own models


def _extras(session: Session, assets: list[AssetView]) -> _Extras:
    names = {t.code: t.name for t in list_asset_types(session)}
    types = {
        a.id: (a.asset_type_code, names.get(a.asset_type_code, a.asset_type_code))
        for a in assets
        if a.asset_type_code
    }
    per_model = open_alerts_by_model(session)
    alerts: dict[int, int] = {}
    for model_id, (asset_id, _name) in model_assets(session).items():
        alerts[asset_id] = alerts.get(asset_id, 0) + per_model.get(model_id, 0)
    return _Extras(types, alerts)


def _node_out(n: NodeHealth, extras: _Extras | None = None) -> AssetNodeOut:
    children = [_node_out(c, extras) for c in n.children]
    own = extras.alerts.get(n.asset_id, 0) if extras else 0
    kind = extras.types.get(n.asset_id) if extras else None
    return AssetNodeOut(
        id=n.asset_id,
        code=n.code,
        name=n.name,
        level=n.level.label,
        criticality=n.criticality.value if n.criticality else None,
        asset_type=kind[0] if kind else None,
        asset_type_name=kind[1] if kind else None,
        open_alerts=own + sum(c.open_alerts for c in children),
        band=n.band.value if n.band else None,
        health=n.health,
        counts={b.value: c for b, c in n.counts.items()},
        worst=n.worst,
        models=[_model_out(m) for m in n.models],
        children=children,
    )


def asset_out(a: AssetView) -> AssetOut:
    return AssetOut(
        id=a.id,
        code=a.code,
        name=a.name,
        level=a.level.label,
        parent_id=a.parent_id,
        criticality=a.criticality.value if a.criticality else None,
        asset_type=a.asset_type_code,
        description=a.description,
    )


def _visible_roots(user: SignedIn, assets: list[AssetView]) -> list[AssetView]:
    """The topmost assets the user may see: everything for an unscoped user, otherwise the
    scope nodes (a scope inside another scope is covered by it)."""
    visible = [a for a in assets if can_see(user, a.path)]
    ids = {a.id for a in visible}
    return [a for a in visible if a.parent_id not in ids]


@router.get(
    "/assets",
    response_model=list[AssetNodeOut] | Page[AssetOut],
    summary="The hierarchy with health roll-up (tree=true), or a flat page of assets",
)
def get_assets(
    request: Request,
    user: User,
    tree: bool = False,
    root: Annotated[str | None, Query(description="asset code: only this subtree")] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 500,
) -> list[AssetNodeOut] | Page[AssetOut]:
    with database_of(request).session() as session:
        if root is not None and find_asset(session, root) is None:
            raise not_found("Asset")
        assets = list_subtree(session, root)
        if not tree:
            visible = [a for a in assets if can_see(user, a.path)]
            items, next_cursor = page(visible, lambda a: a.path, cursor, limit)
            return Page[AssetOut](items=[asset_out(a) for a in items], next_cursor=next_cursor)
        roots = _visible_roots(user, assets)
        extras = _extras(session, assets)
        return [_node_out(node, extras) for r in roots for node in health_tree(session, r.code)]


@router.get("/assets/{asset_id}", response_model=AssetDetailOut, summary="One asset with health")
def get_asset(request: Request, user: User, asset_id: int) -> AssetDetailOut:
    with database_of(request).session() as session:
        try:
            asset = get_asset_by_id(session, asset_id)
        except RegistryError:
            raise not_found("Asset") from None
        if not can_see(user, asset.path):
            raise not_found("Asset")
        ancestors = [
            Crumb(id=a.id, code=a.code, name=a.name)
            for a in list_ancestors(session, asset.code)
            if can_see(user, a.path)
        ]
        (node,) = health_tree(session, asset.code)
        extras = _extras(session, list_subtree(session, asset.code))
    return AssetDetailOut(
        **asset_out(asset).model_dump(), ancestors=ancestors, health=_node_out(node, extras)
    )


class TagOut(BaseModel):
    id: int
    source: str
    source_name: str
    asset_id: int
    asset_code: str
    description: str
    unit: str
    range_lo: float
    range_hi: float
    interval_s: int
    role: str | None


@router.get("/tags", response_model=Page[TagOut], summary="Registered tags")
def get_tags(
    request: Request,
    user: User,
    asset: Annotated[str | None, Query(description="asset code")] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 500,
) -> Page[TagOut]:
    with database_of(request).session() as session:
        if asset is not None and find_asset(session, asset) is None:
            raise not_found("Asset")
        paths = {a.id: a.path for a in list_subtree(session)}
        tags = [t for t in list_tags(session, asset) if can_see(user, paths.get(t.asset_id))]
    tags.sort(key=lambda t: t.id)
    items, next_cursor = page(tags, lambda t: t.id, cursor, limit)
    return Page[TagOut](
        items=[tag_out(t) for t in items],
        next_cursor=next_cursor,
    )


def tag_out(t: TagView) -> TagOut:
    return TagOut(
        id=t.id,
        source=t.source,
        source_name=t.source_name,
        asset_id=t.asset_id,
        asset_code=t.asset_code,
        description=t.description,
        unit=t.unit,
        range_lo=t.range_lo,
        range_hi=t.range_hi,
        interval_s=t.interval_s,
        role=t.role_code,
    )


class RoleOut(BaseModel):
    code: str
    name: str
    unit: str


class AssetTypeOut(BaseModel):
    id: int
    code: str
    name: str
    description: str
    roles: list[RoleOut]


@router.get("/asset-types", response_model=list[AssetTypeOut], summary="Asset types and roles")
def get_asset_types(request: Request, user: User) -> list[AssetTypeOut]:
    with database_of(request).session() as session:
        types = list_asset_types(session)
    return [
        AssetTypeOut(
            id=t.id,
            code=t.code,
            name=t.name,
            description=t.description,
            roles=[RoleOut(code=r.code, name=r.name, unit=r.unit) for r in t.roles],
        )
        for t in types
    ]


@router.get(
    "/asset-types/{type_id}/roles", response_model=list[RoleOut], summary="An asset type's roles"
)
def get_type_roles(request: Request, user: User, type_id: int) -> list[RoleOut]:
    found = next((t for t in get_asset_types(request, user) if t.id == type_id), None)
    if found is None:
        raise not_found("Asset type")
    return found.roles


class SensorHealthOut(BaseModel):
    tag_id: int
    source: str
    source_name: str
    asset_code: str
    status: str
    rule: str
    effect: str
    since: datetime
    evaluated_at: datetime


@router.get(
    "/sensors/health",
    response_model=Page[SensorHealthOut],
    summary="Each sensor's NE 107 status as of the latest scoring cycle (UCS §6.1)",
)
def get_sensor_health(
    request: Request,
    user: User,
    asset: Annotated[str | None, Query(description="asset code: this asset's tags")] = None,
    status: Annotated[str | None, Query(description="only this NE 107 status")] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 500,
) -> Page[SensorHealthOut]:
    with database_of(request).session() as session:
        if asset is not None and find_asset(session, asset) is None:
            raise not_found("Asset")
        paths = {a.id: a.path for a in list_subtree(session)}
        tags = [t for t in list_tags(session, asset) if can_see(user, paths.get(t.asset_id))]
        statuses = get_sensor_statuses(session, [t.id for t in tags]) if tags else []
    statuses = sorted(
        (v for v in statuses if status is None or v.status.value == status), key=lambda v: v.tag_id
    )
    items, next_cursor = page(statuses, lambda v: v.tag_id, cursor, limit)
    return Page[SensorHealthOut](
        items=[
            SensorHealthOut(
                tag_id=v.tag_id,
                source=v.source,
                source_name=v.source_name,
                asset_code=v.asset_code,
                status=v.status.value,
                rule=v.rule.value,
                effect=v.effect.value,
                since=v.since,
                evaluated_at=v.evaluated_at,
            )
            for v in items
        ],
        next_cursor=next_cursor,
    )
