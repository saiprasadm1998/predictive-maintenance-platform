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
from pmp.dataquality.exclusions import (
    ExclusionKind,
    ExclusionView,
    add_exclusion,
    end_exclusion,
    list_exclusions,
)
from pmp.dataquality.service import (
    PreviewReport,
    Reference,
    RuleScope,
    RuleSetView,
    ScopeKind,
    SensorReading,
    SensorStatusView,
    SeriesAssessment,
    TagPreview,
    assess_series,
    authorize_rule_change,
    cycle_grid,
    effective_params,
    evaluate_sensors,
    get_rule_set,
    get_sensor_statuses,
    list_rule_versions,
    preview_rules,
    read_sensors,
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
    "ExclusionKind",
    "ExclusionView",
    "Ne107",
    "PreviewReport",
    "Reference",
    "Rule",
    "RuleParams",
    "RuleScope",
    "RuleSetView",
    "ScopeKind",
    "SensorReading",
    "SensorState",
    "SensorStatusChanged",
    "SensorStatusView",
    "SeriesAssessment",
    "TagPreview",
    "add_exclusion",
    "assess_series",
    "authorize_rule_change",
    "coverage",
    "cycle_grid",
    "effective_params",
    "end_exclusion",
    "evaluate_sensors",
    "get_rule_set",
    "get_sensor_statuses",
    "list_exclusions",
    "list_rule_versions",
    "preview_rules",
    "read_sensors",
    "save_rule_set",
]
