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
from pmp.modelling.definitions import (
    ModelDefinition,
    ModelError,
    Period,
    SensorChoice,
    VersionStatus,
    check_definition,
    definition_from_dict,
)
from pmp.modelling.expressions import Expression, ExpressionError, parse_expression
from pmp.modelling.service import (
    ModelSensorView,
    ModelView,
    VersionView,
    find_model,
    get_model,
    get_model_by_id,
    list_models,
    save_draft,
)

__all__ = [
    "DEFAULT_DETECTOR",
    "ENTRY_POINT_GROUP",
    "ContractReport",
    "Detector",
    "DetectorError",
    "DetectorInfo",
    "Expression",
    "ExpressionError",
    "MedianDetector",
    "ModelDefinition",
    "ModelError",
    "ModelSensorView",
    "ModelView",
    "Period",
    "SensorChoice",
    "VersionStatus",
    "VersionView",
    "available_detectors",
    "check_definition",
    "check_detector",
    "definition_from_dict",
    "find_model",
    "get_detector",
    "get_model",
    "get_model_by_id",
    "list_models",
    "parse_expression",
    "save_draft",
]
