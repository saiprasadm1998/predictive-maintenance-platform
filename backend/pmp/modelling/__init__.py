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
from pmp.modelling.artefacts import ArtefactError
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
from pmp.modelling.lifecycle import (
    Action,
    ActiveVersion,
    DeployCheck,
    ModelDeployed,
    ModelStatusChanged,
    change_status,
    list_active_versions,
)
from pmp.modelling.loading import LoadedModel, ModelCache, load_version
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
    SensorUse,
    TrainingDataPreview,
    VersionView,
    asset_path,
    find_model,
    get_model,
    get_model_by_id,
    list_models,
    make_training_failure_handler,
    make_training_handler,
    model_asset_code,
    model_assets,
    model_of_version,
    preview_training_data,
    run_training,
    save_draft,
    start_training,
    version_numbers,
)

__all__ = [
    "DEFAULT_DETECTOR",
    "ENTRY_POINT_GROUP",
    "RANGE_FLOOR",
    "SIGMA_FLOOR",
    "TRAIN_JOB",
    "Action",
    "ActiveVersion",
    "ArtefactError",
    "ContractReport",
    "DeployCheck",
    "Detector",
    "DetectorError",
    "DetectorInfo",
    "Expression",
    "ExpressionError",
    "LoadedModel",
    "MedianDetector",
    "ModelCache",
    "ModelDefinition",
    "ModelDeployed",
    "ModelError",
    "ModelSensorView",
    "ModelStatusChanged",
    "ModelView",
    "Period",
    "ScaleError",
    "SensorChoice",
    "SensorScale",
    "SensorUse",
    "TrainingDataPreview",
    "VersionStatus",
    "VersionView",
    "asset_path",
    "available_detectors",
    "change_status",
    "check_definition",
    "check_detector",
    "definition_from_dict",
    "find_model",
    "get_detector",
    "get_model",
    "get_model_by_id",
    "list_active_versions",
    "list_models",
    "load_version",
    "make_training_failure_handler",
    "make_training_handler",
    "model_asset_code",
    "model_assets",
    "model_of_version",
    "parse_expression",
    "preview_training_data",
    "run_training",
    "save_draft",
    "scale_with_floors",
    "start_training",
    "version_numbers",
]
