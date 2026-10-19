"""Loading deployed models for scoring (ARC §8.2, §5.1): verify, load, cache.

`load_version` checks the artefact's SHA-256 before reading it and builds everything a
scoring cycle needs. `ModelCache` keeps each loaded version per worker process until its
model's status changes (deploy, pause, resume, retire, supersede), as ARC §8.2 requires.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from pmp.core import EventBus
from pmp.modelling.algorithms.contract import Detector, DetectorError
from pmp.modelling.algorithms.registry import get_detector
from pmp.modelling.artefacts import ArtefactError, read_artefact
from pmp.modelling.definitions import ModelError
from pmp.modelling.expressions import parse_expression
from pmp.modelling.lifecycle import ModelStatusChanged
from pmp.modelling.models import Model, ModelVersion
from pmp.modelling.scaling import ScaleError, SensorScale
from pmp.modelling.service import _version_view
from pmp.registry import get_asset_by_id, list_tags


def _asset_id(session: Session, row: ModelVersion) -> int:
    return session.get_one(Model, row.model_id).asset_id


@dataclass(frozen=True)
class LoadedModel:
    """A verified, loaded model version, ready to predict."""

    model_id: int
    version_id: int
    version: int
    detector: Detector
    sensors: tuple[str, ...]  # source names, in model order
    tag_ids: Mapping[str, int]
    required: frozenset[str]
    medians: Mapping[str, float]
    scales: Mapping[str, SensorScale]
    training_std: Mapping[str, float | None]  # None for artefacts written before 4.1
    mode_filters: tuple[str, ...]
    filter_tag_ids: Mapping[str, int]  # every tag the operating-mode filters name
    cycle_s: int
    sha256: str


def _scales(
    scaling: Mapping[str, Any], order: tuple[str, ...]
) -> tuple[dict[str, float], dict[str, SensorScale]]:
    try:
        if tuple(scaling["sensor_order"]) != order:
            raise ArtefactError("Artefact sensor order differs from the version's sensors")
        sensors = scaling["sensors"]
        medians = {n: float(sensors[n]["median"]) for n in order}
        scales = {
            n: SensorScale(
                range=float(sensors[n]["range"]),
                sigma=float(sensors[n]["sigma"]),
                range_floored=bool(sensors[n]["range_floored"]),
                sigma_floored=bool(sensors[n]["sigma_floored"]),
            )
            for n in order
        }
    except (KeyError, TypeError, ValueError, ScaleError) as error:
        if isinstance(error, ArtefactError):
            raise
        raise ArtefactError(f"scaling.json is not valid: {error}") from None
    return medians, scales


def load_version(session: Session, version_id: int) -> LoadedModel:
    """Verify and load one trained version (Validated, Deployed, Paused or Superseded)."""
    row = session.get(ModelVersion, version_id)
    if row is None:
        raise ModelError(f"Model version {version_id} does not exist")
    if row.artefact_path is None or row.artefact_sha256 is None:
        raise ArtefactError(f"Version {row.version} is {row.status} and has no trained artefact")
    algorithm_dir, scaling, manifest = read_artefact(Path(row.artefact_path), row.artefact_sha256)
    view = _version_view(session, row)
    order = tuple(s.source_name for s in view.sensors)
    medians, scales = _scales(scaling, order)
    stds = {
        n: (float(v) if (v := scaling["sensors"][n].get("std")) is not None else None)
        for n in order
    }
    asset_tags = {
        t.source_name: t.id
        for t in list_tags(session, get_asset_by_id(session, _asset_id(session, row)).code)
    }
    filter_names = sorted(set().union(*(parse_expression(f).names for f in view.mode_filters)))
    try:
        detector = get_detector(str(manifest.get("algorithm", row.algorithm))).load(algorithm_dir)
    except DetectorError as error:
        raise ArtefactError(f"Cannot load the algorithm: {error}") from None
    return LoadedModel(
        model_id=row.model_id,
        version_id=row.id,
        version=row.version,
        detector=detector,
        sensors=order,
        tag_ids={s.source_name: s.tag_id for s in view.sensors},
        required=frozenset(s.source_name for s in view.sensors if s.required),
        medians=medians,
        scales=scales,
        training_std=stds,
        mode_filters=view.mode_filters,
        filter_tag_ids={n: asset_tags[n] for n in filter_names if n in asset_tags},
        cycle_s=int((row.params or {}).get("cycle_s", 60)),
        sha256=row.artefact_sha256,
    )


class ModelCache:
    """Loaded versions per worker process, dropped when their model's status changes."""

    def __init__(self, bus: EventBus | None = None) -> None:
        self._loaded: dict[int, LoadedModel] = {}
        self.loads = 0
        if bus is not None:
            bus.subscribe(ModelStatusChanged, self._on_change)

    def get(self, session: Session, version_id: int) -> LoadedModel:
        cached = self._loaded.get(version_id)
        if cached is None:
            cached = load_version(session, version_id)
            self.loads += 1
            self._loaded[version_id] = cached
        return cached

    def forget_model(self, model_id: int) -> None:
        for version_id in [v for v, m in self._loaded.items() if m.model_id == model_id]:
            del self._loaded[version_id]

    def _on_change(self, event: ModelStatusChanged) -> None:
        self.forget_model(event.model_id)

    def __len__(self) -> int:
        return len(self._loaded)
