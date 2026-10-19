"""dataquality.

Sensor data-quality rule evaluation, NAMUR NE 107 status and manual exclusions
(UCS §6.1, FR-DQ-01 to -03).

Public interface of the module (ARC-001 §4.1). Other modules may import only
what this file exports, never the module's internal files.
"""

from pmp.dataquality.domain import (
    DEFAULTS,
    MIN_COVERAGE,
    PARAM_NAMES,
    PREVIEW_WARN_SHARE,
    Coverage,
    DataQualityError,
    Effect,
    Ne107,
    Rule,
    RuleParams,
    SensorState,
    SensorStatusChanged,
    coverage,
)
from pmp.dataquality.service import (
    PreviewReport,
    Reference,
    RuleScope,
    RuleSetView,
    ScopeKind,
    SensorStatusView,
    SeriesAssessment,
    TagPreview,
    assess_series,
    cycle_grid,
    effective_params,
    evaluate_sensors,
    get_rule_set,
    get_sensor_statuses,
    list_rule_versions,
    preview_rules,
    save_rule_set,
)

__all__ = [
    "DEFAULTS",
    "MIN_COVERAGE",
    "PARAM_NAMES",
    "PREVIEW_WARN_SHARE",
    "Coverage",
    "DataQualityError",
    "Effect",
    "Ne107",
    "PreviewReport",
    "Reference",
    "Rule",
    "RuleParams",
    "RuleScope",
    "RuleSetView",
    "ScopeKind",
    "SensorState",
    "SensorStatusChanged",
    "SensorStatusView",
    "SeriesAssessment",
    "TagPreview",
    "assess_series",
    "coverage",
    "cycle_grid",
    "effective_params",
    "evaluate_sensors",
    "get_rule_set",
    "get_sensor_statuses",
    "list_rule_versions",
    "preview_rules",
    "save_rule_set",
]
