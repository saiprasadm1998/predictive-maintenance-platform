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
from pmp.modelling.scaling import (
    RANGE_FLOOR,
    SIGMA_FLOOR,
    ScaleError,
    SensorScale,
    scale_with_floors,
)
from pmp.modelling.service import (
    TRAIN_JOB,
    ModelSensorView,
    ModelView,
    VersionView,
    find_model,
    get_model,
    get_model_by_id,
    list_models,
    make_training_handler,
    run_training,
    save_draft,
    start_training,
)

__all__ = [
    "DEFAULT_DETECTOR",
    "ENTRY_POINT_GROUP",
    "RANGE_FLOOR",
    "SIGMA_FLOOR",
    "TRAIN_JOB",
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
    "ScaleError",
    "SensorChoice",
    "SensorScale",
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
    "make_training_handler",
    "parse_expression",
    "run_training",
    "save_draft",
    "scale_with_floors",
    "start_training",
]
