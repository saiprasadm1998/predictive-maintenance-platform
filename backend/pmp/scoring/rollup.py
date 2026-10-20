"""Health roll-up over the asset hierarchy (UC-08, FR-HLT-01, UCS §6.5).

An asset takes the worst band and the lowest Health of its models in service; every asset
above it takes the worst band of its children (and of its own models, if any) and, as its
Health figure, the lowest Health beneath it (PDS: the bar shows the minimum of the
children). Band order, worst first: Alert, Watch, Unknown, Healthy. Unknown ranks above
Healthy so an asset that cannot be assessed never makes its parent look healthy, and
below Watch so it never hides a real deviation (decision 4.3).

A model counts as Unknown, with its reason, while its status is Insufficient data, Not in
operating mode, Paused, Error or not scored yet (UCS §6.5). A retired model (Out of
service) counts as Unknown only while its asset has no other model in service, so a
decommissioned model never greys out an asset that is monitored by another (decision 4.4).
Models never deployed count for nothing: an asset with no counting model has no band and
no Health ("no model"), and so has a parent with only such assets beneath it.

`roll_up` is pure; `health_tree` reads the registry and the latest runtime statuses, so the
result is always as of the latest cycle.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from pmp.modelling import list_active_versions, model_assets
from pmp.registry import AssetLevel, AssetView, Criticality, list_subtree
from pmp.scoring.outputs import Band, RuntimeStatus
from pmp.scoring.runtime import get_runtime_statuses

RANK = {Band.HEALTHY: 0, Band.UNKNOWN: 1, Band.WATCH: 2, Band.ALERT: 3}


@dataclass(frozen=True)
class ModelHealth:
    """One counting model at its latest cycle. `status` None: deployed, not scored yet."""

    model_id: int
    asset_id: int
    name: str
    band: Band
    health: float | None
    status: RuntimeStatus | None = None
    reason: str | None = None  # why Unknown (UC-08 2a: shown on hover)
    last_cycle: datetime | None = None  # latest scored cycle (stale-data banner, PDS SCR-01)

    @property
    def why(self) -> str | None:
        """The Unknown reason in words: the status, plus its detail if any."""
        if self.band is not Band.UNKNOWN:
            return None
        status = self.status.value if self.status else "Not scored yet"
        return f"{status}: {self.reason}" if self.reason else status


@dataclass(frozen=True)
class NodeHealth:
    asset_id: int
    code: str
    name: str
    level: AssetLevel
    criticality: Criticality | None
    band: Band | None  # None: no model counts here
    health: float | None  # lowest Health beneath (Running models only)
    counts: Mapping[Band, int]  # monitored assets at or beneath this one, by their own band
    models: tuple[ModelHealth, ...]  # this asset's own models in service
    worst: str | None  # code of the monitored asset that sets the band (lowest Health first)
    children: tuple[NodeHealth, ...] = field(default=())

    @property
    def monitored(self) -> bool:
        return self.band is not None

    def walk(self) -> Iterable[NodeHealth]:
        yield self
        for child in self.children:
            yield from child.walk()


def worst_band(bands: Iterable[Band]) -> Band | None:
    ranked = list(bands)
    return max(ranked, key=RANK.__getitem__) if ranked else None


def _own(models: Sequence[ModelHealth]) -> tuple[Band | None, float | None]:
    band = worst_band(m.band for m in models)
    healths = [m.health for m in models if m.health is not None]
    return band, (min(healths) if healths else None)


def _severity(candidate: tuple[Band, float | None, str]) -> tuple[int, float]:
    """Worst band first, then the lowest Health (no Health counts as the least severe)."""
    band, health, _ = candidate
    return RANK[band], -(health if health is not None else float("inf"))


def roll_up(assets: Sequence[AssetView], models: Iterable[ModelHealth]) -> list[NodeHealth]:
    """The hierarchy with health on every node; returns the top-level nodes (those whose
    parent is not among `assets`), in the order given."""
    by_asset: dict[int, list[ModelHealth]] = defaultdict(list)
    for model in models:
        by_asset[model.asset_id].append(model)
    ids = {a.id for a in assets}
    children: dict[int, list[AssetView]] = defaultdict(list)
    roots = []
    for asset in assets:
        if asset.parent_id is not None and asset.parent_id in ids:
            children[asset.parent_id].append(asset)
        else:
            roots.append(asset)

    def build(asset: AssetView) -> NodeHealth:
        kids = tuple(build(child) for child in children[asset.id])
        own = tuple(by_asset.get(asset.id, ()))
        own_band, own_health = _own(own)
        counts: Counter[Band] = Counter()
        candidates: list[tuple[Band, float | None, str]] = []
        if own_band is not None:
            counts[own_band] += 1
            candidates.append((own_band, own_health, asset.code))
        for kid in kids:
            counts.update(kid.counts)
            if kid.band is not None and kid.worst is not None:
                candidates.append((kid.band, kid.health, kid.worst))
        band = worst_band(c[0] for c in candidates)
        healths = [c[1] for c in candidates if c[1] is not None]
        worst = None
        if candidates:
            inf = float("inf")
            worst = max(
                candidates, key=lambda c: (RANK[c[0]], -(c[1] if c[1] is not None else inf))
            )[2]
        return NodeHealth(
            asset_id=asset.id,
            code=asset.code,
            name=asset.name,
            level=asset.level,
            criticality=asset.criticality,
            band=band,
            health=min(healths) if healths else None,
            counts=dict(counts),
            models=own,
            worst=worst,
            children=kids,
        )

    return [build(root) for root in roots]


def model_healths(session: Session) -> list[ModelHealth]:
    """Every counting model at its latest cycle (see the module docstring)."""
    statuses = {v.model_id: v for v in get_runtime_statuses(session)}
    active = list_active_versions(session)
    in_service_assets = {v.asset_id for v in active}
    healths = []
    for version in active:
        status = statuses.get(version.model_id)
        if version.status.value == "Paused":
            healths.append(
                ModelHealth(
                    version.model_id,
                    version.asset_id,
                    version.name,
                    Band.UNKNOWN,
                    None,
                    RuntimeStatus.PAUSED,
                    last_cycle=status.last_cycle if status else None,
                )
            )
            continue
        current = (
            status is not None
            and status.version_id == version.version_id
            and status.status not in (RuntimeStatus.PAUSED, RuntimeStatus.OUT_OF_SERVICE)
        )
        if status is None or not current:
            healths.append(
                ModelHealth(version.model_id, version.asset_id, version.name, Band.UNKNOWN, None)
            )
            continue
        healths.append(
            ModelHealth(
                model_id=version.model_id,
                asset_id=version.asset_id,
                name=version.name,
                band=status.band,
                health=status.health,
                status=status.status,
                reason=status.reason,
                last_cycle=status.last_cycle,
            )
        )
    assets = model_assets(session)
    active_ids = {v.model_id for v in active}
    for model_id, status in statuses.items():
        if model_id in active_ids or model_id not in assets:
            continue
        asset_id, name = assets[model_id]
        if asset_id in in_service_assets:
            continue  # retired, but its asset is monitored by another model
        healths.append(
            ModelHealth(
                model_id,
                asset_id,
                name,
                Band.UNKNOWN,
                None,
                RuntimeStatus.OUT_OF_SERVICE,
                last_cycle=status.last_cycle,
            )
        )
    return healths


def health_tree(session: Session, asset_code: str | None = None) -> list[NodeHealth]:
    """The roll-up for the whole hierarchy, or for one asset and everything beneath it."""
    return roll_up(list_subtree(session, asset_code), model_healths(session))
