"""modelling.

Model definitions, training-data assembly, cleansing, algorithms, plug-in registry, validation,
artefacts and lifecycle.

Public interface of the module (ARC-001 §4.1). Other modules may import only
what this file exports, never the module's internal files.
"""

from pmp.modelling.algorithms.checks import ContractReport, check_detector
from pmp.modelling.algorithms.contract import Detector, DetectorError
from pmp.modelling.algorithms.median import MedianDetector
from pmp.modelling.algorithms.registry import (
    DEFAULT_DETECTOR,
    ENTRY_POINT_GROUP,
    DetectorInfo,
    available_detectors,
    get_detector,
)

__all__ = [
    "DEFAULT_DETECTOR",
    "ENTRY_POINT_GROUP",
    "ContractReport",
    "Detector",
    "DetectorError",
    "DetectorInfo",
    "MedianDetector",
    "available_detectors",
    "check_detector",
    "get_detector",
]
