"""scoring.

Cycle execution, prediction, per-sensor outputs, Deviation Index, Health Score and runtime
status.

Public interface of the module (ARC-001 §4.1). Other modules may import only
what this file exports, never the module's internal files.
"""

from pmp.scoring.outputs import (
    RANGE_FLOOR,
    SIGMA_FLOOR,
    Band,
    Limits,
    ModelOutput,
    RuntimeStatus,
    ScoringError,
    SensorInput,
    SensorLimits,
    SensorOutput,
    SensorScale,
    Severity,
    band_for,
    compute_outputs,
    health_score,
    scale_with_floors,
)

__all__ = [
    "RANGE_FLOOR",
    "SIGMA_FLOOR",
    "Band",
    "Limits",
    "ModelOutput",
    "RuntimeStatus",
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
