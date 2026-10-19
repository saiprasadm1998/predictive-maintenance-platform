"""scoring.

Cycle execution, prediction, per-sensor outputs, Deviation Index, Health Score and runtime
status.

Public interface of the module (ARC-001 §4.1). Other modules may import only
what this file exports, never the module's internal files.
"""

from pmp.modelling import RANGE_FLOOR, SIGMA_FLOOR, ScaleError, SensorScale, scale_with_floors
from pmp.scoring.outputs import (
    Band,
    Limits,
    ModelOutput,
    RuntimeStatus,
    ScoringError,
    SensorInput,
    SensorLimits,
    SensorOutput,
    Severity,
    band_for,
    compute_outputs,
    health_score,
)

__all__ = [
    "RANGE_FLOOR",
    "SIGMA_FLOOR",
    "Band",
    "Limits",
    "ModelOutput",
    "RuntimeStatus",
    "ScaleError",
    "ScoringError",
    "SensorInput",
    "SensorLimits",
    "SensorOutput",
    "SensorScale",
    "Severity",
    "band_for",
    "compute_outputs",
    "health_score",
    "scale_with_floors",
]
