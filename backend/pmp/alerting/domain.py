"""Alert rule definitions (UCS §6.6, FR-ALM-01). Pure logic; evaluation arrives in 4.2.

A model has one Deviation Index rule and optional sensor rules on |z|. Each has a warning
and an alert limit (DI in %, sensor rules in |z|), persistence (raise when the condition
holds in n of the last m cycles, default 3 of 5), an on-delay (default 0 s) and a deadband
(clear when below limit x (1 - deadband) for k cycles, default 10 % for 5 cycles).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class AlertRuleError(ValueError):
    """An alert rule that cannot be accepted."""


class RuleKind(StrEnum):
    DI = "di"
    SENSOR = "sensor"


DEFAULT_SENSOR_WARNING = 3.0  # |z|, UCS §6.4
DEFAULT_SENSOR_ALERT = 5.0


@dataclass(frozen=True)
class AlertRuleSpec:
    kind: RuleKind
    warning: float
    alert: float
    tag_id: int | None = None  # sensor rules only
    persistence_n: int = 3
    persistence_m: int = 5
    on_delay_s: int = 0
    deadband: float = 0.10
    clear_cycles: int = 5
    enabled: bool = True

    def __post_init__(self) -> None:
        what = "DI rule" if self.kind is RuleKind.DI else f"Sensor rule on tag {self.tag_id}"
        if (self.kind is RuleKind.DI) != (self.tag_id is None):
            raise AlertRuleError("A DI rule has no tag; a sensor rule needs one")
        if not (math.isfinite(self.warning) and math.isfinite(self.alert)):
            raise AlertRuleError(f"{what}: limits must be numbers")
        if not 0 < self.warning < self.alert:
            raise AlertRuleError(f"{what}: limits need 0 < warning < alert")
        if not 1 <= self.persistence_n <= self.persistence_m:
            raise AlertRuleError(f"{what}: persistence needs 1 <= n <= m")
        if self.on_delay_s < 0:
            raise AlertRuleError(f"{what}: on-delay cannot be negative")
        if not 0 <= self.deadband < 1:
            raise AlertRuleError(f"{what}: deadband must be from 0 up to (not including) 100 %")
        if self.clear_cycles < 1:
            raise AlertRuleError(f"{what}: clearing needs at least 1 cycle")

    @property
    def key(self) -> tuple[RuleKind, int | None]:
        return (self.kind, self.tag_id)
