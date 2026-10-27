"""Detector registry: built-ins plus plug-ins from the `pmp.algorithms` entry point.

Algorithms are installed Python packages only, never code uploaded through the UI
(ADR-09). Every detector found, built-in or plug-in, runs the contract suite once per
process, and only those that pass can be used (ARC-001 §8.1).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib.metadata import EntryPoint, entry_points
from typing import Any

from pmp.modelling.algorithms.aakr import AakrDetector
from pmp.modelling.algorithms.checks import check_detector
from pmp.modelling.algorithms.contract import Detector, DetectorError
from pmp.modelling.algorithms.median import MedianDetector

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "pmp.algorithms"
DEFAULT_DETECTOR = "aakr"  # plan 7.4; "median" stays available as a baseline
BUILT_IN: dict[str, type[Any]] = {
    MedianDetector.name: MedianDetector,
    AakrDetector.name: AakrDetector,
}


@dataclass(frozen=True)
class DetectorInfo:
    name: str
    version: str
    source: str  # "built-in" or "plug-in <entry point value>"
    failures: list[str] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        return not self.failures


_cache: dict[str, tuple[DetectorInfo, type[Any] | None]] | None = None


def _plugin_entry_points() -> list[EntryPoint]:
    return list(entry_points(group=ENTRY_POINT_GROUP))


def _discover() -> dict[str, tuple[DetectorInfo, type[Any] | None]]:
    found: dict[str, tuple[DetectorInfo, type[Any] | None]] = {}
    for name, cls in BUILT_IN.items():
        report = check_detector(cls)
        found[name] = (DetectorInfo(name, report.version, "built-in", report.failures), cls)

    for point in _plugin_entry_points():
        source = f"plug-in {point.value}"
        if point.name in BUILT_IN:
            if point.value != f"{BUILT_IN[point.name].__module__}:{BUILT_IN[point.name].__name__}":
                logger.warning("Refused detector %r from %s: name is built in", point.name, source)
            continue
        try:
            cls = point.load()
        except Exception as error:
            info = DetectorInfo(point.name, "?", source, [f"could not be loaded: {error}"])
            found[point.name] = (info, None)
            logger.warning("Refused detector %r: could not be loaded: %s", point.name, error)
            continue
        report = check_detector(cls)
        failures = list(report.failures)
        if report.name != point.name:
            failures.append(f"declares name {report.name!r}, registered as {point.name!r}")
        found[point.name] = (DetectorInfo(point.name, report.version, source, failures), cls)
        if failures:
            logger.warning("Refused detector %r: %s", point.name, "; ".join(failures))
    return found


def _registry(refresh: bool) -> dict[str, tuple[DetectorInfo, type[Any] | None]]:
    global _cache
    if _cache is None or refresh:
        _cache = _discover()
    return _cache


def available_detectors(refresh: bool = False) -> list[DetectorInfo]:
    """Every detector found, with whether it passed the contract and why not."""
    return sorted((info for info, _ in _registry(refresh).values()), key=lambda i: i.name)


def get_detector(name: str = DEFAULT_DETECTOR) -> type[Detector]:
    """The class of an enabled detector; unknown or refused names raise DetectorError."""
    entry = _registry(False).get(name)
    if entry is None:
        raise DetectorError(f"No detector named {name!r}")
    info, cls = entry
    if cls is None or info.failures:
        raise DetectorError(f"Detector {name!r} failed the contract: {'; '.join(info.failures)}")
    detector_cls: type[Detector] = cls
    return detector_cls
