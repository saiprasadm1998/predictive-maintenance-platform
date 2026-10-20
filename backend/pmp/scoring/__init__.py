"""scoring.

Cycle execution, prediction, per-sensor outputs, Deviation Index, Health Score and runtime
status.

Public interface of the module (ARC-001 §4.1). Other modules may import only
what this file exports, never the module's internal files.
"""

from pmp.core import EVENT_CHANNEL
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
from pmp.scoring.runtime import (
    CycleResult,
    RuntimeStatusView,
    ScoreComputed,
    evaluate,
    get_runtime_statuses,
    last_cycles,
    limits_for,
    references_for,
    score_models,
)
from pmp.scoring.scheduler import Scheduler, latest_due_cycle

__all__ = [
    "EVENT_CHANNEL",
    "RANGE_FLOOR",
    "SIGMA_FLOOR",
    "Band",
    "CycleResult",
    "Limits",
    "ModelOutput",
    "RuntimeStatus",
    "RuntimeStatusView",
    "ScaleError",
    "Scheduler",
    "ScoreComputed",
    "ScoringError",
    "SensorInput",
    "SensorLimits",
    "SensorOutput",
    "SensorScale",
    "Severity",
    "band_for",
    "compute_outputs",
    "evaluate",
    "get_runtime_statuses",
    "health_score",
    "last_cycles",
    "latest_due_cycle",
    "limits_for",
    "references_for",
    "scale_with_floors",
    "score_models",
]
