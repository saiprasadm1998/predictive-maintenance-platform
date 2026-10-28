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
from pmp.scoring.rollup import (
    ModelHealth,
    NodeHealth,
    health_tree,
    model_healths,
    roll_up,
    worst_band,
)
from pmp.scoring.runtime import (
    CycleResult,
    RuntimeStatusView,
    ScoreComputed,
    deployed_references,
    evaluate,
    get_runtime_statuses,
    last_cycles,
    limits_for,
    references_for,
    score_models,
)
from pmp.scoring.scheduler import (
    RETAINED_TABLES,
    Scheduler,
    latest_due_cycle,
    make_retention_handler,
)
from pmp.scoring.trends import (
    MAX_PX,
    SensorReadingOut,
    StatusPeriod,
    Trend,
    TrendError,
    UnusedPeriod,
    cycle_outputs,
    latest_cycle,
    output_trends,
    quarter_hour_means,
    score_trend,
    status_periods,
    unused_periods,
    z_history,
)

__all__ = [
    "EVENT_CHANNEL",
    "MAX_PX",
    "RANGE_FLOOR",
    "RETAINED_TABLES",
    "SIGMA_FLOOR",
    "Band",
    "CycleResult",
    "Limits",
    "ModelHealth",
    "ModelOutput",
    "NodeHealth",
    "RuntimeStatus",
    "RuntimeStatusView",
    "ScaleError",
    "Scheduler",
    "ScoreComputed",
    "ScoringError",
    "SensorInput",
    "SensorLimits",
    "SensorOutput",
    "SensorReadingOut",
    "SensorScale",
    "Severity",
    "StatusPeriod",
    "Trend",
    "TrendError",
    "UnusedPeriod",
    "band_for",
    "compute_outputs",
    "cycle_outputs",
    "deployed_references",
    "evaluate",
    "get_runtime_statuses",
    "health_score",
    "health_tree",
    "last_cycles",
    "latest_cycle",
    "latest_due_cycle",
    "limits_for",
    "make_retention_handler",
    "model_healths",
    "output_trends",
    "quarter_hour_means",
    "references_for",
    "roll_up",
    "scale_with_floors",
    "score_models",
    "score_trend",
    "status_periods",
    "unused_periods",
    "worst_band",
    "z_history",
]
