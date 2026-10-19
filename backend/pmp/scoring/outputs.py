"""Per-cycle model outputs: residual, q, z, Deviation Index, contributions, Health and band.

Formulas from UCS §6.2 and §6.5 (FR-RUN-02, FR-HLT-01, FR-DIA-01); verified against the
reference data set to 1e-6 (AC-03). Pure arithmetic: the detector's predictions are an
input, so these results do not depend on the algorithm.

For model sensors i with usable set V (|V| = n):

    residual  r_i = x_i - x̂_i                 (engineering units)
    q_i       = |r_i| / R_i                   R_i = P99 - P1 of cleansed training data
    z_i       = r_i / sigma_i                 sigma_i = 1.4826 x MAD of validation residuals
    DI        = 100 x sqrt(sum_V q_i^2 / n)   (% of training range)
    c_i       = q_i^2 / sum_V q_j^2           (sums to 100 %)
    Health    = 100 x max(0, 1 - DI / DIref)  DIref = 2 x DI alert limit by default

Residual, q and z are also given for excluded sensors that have an actual value (shown on
the asset screen), but only usable sensors count towards DI and contributions.

Two decisions where the spec is silent (implementation plan, decisions for 2.3):
- A sensor that did not move in training has R = 0 or sigma = 0. R is floored at 1 % of
  the instrument range and sigma at 1 % of R; the floor is recorded with the scale
  (pmp.modelling, which produces the scales in training).
- "A sensor z warning active" (UCS §6.5) is read as an active sensor alert. Until the
  alert engine exists (4.2) the band uses the current |z| against the sensor limits.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from pmp.modelling import SensorScale


class ScoringError(ValueError):
    """Inputs that cannot be scored: missing scales, inconsistent limits or sensors."""


class Band(StrEnum):
    HEALTHY = "Healthy"
    WATCH = "Watch"
    ALERT = "Alert"
    UNKNOWN = "Unknown"


class RuntimeStatus(StrEnum):
    """Model runtime statuses (FR-RUN-04). Only Running produces a Health value."""

    RUNNING = "Running"
    NOT_IN_OPERATING_MODE = "Not in operating mode"
    INSUFFICIENT_DATA = "Insufficient data"
    PAUSED = "Paused"
    OUT_OF_SERVICE = "Out of service"
    ERROR = "Error"


class Severity(StrEnum):
    WARNING = "Warning"
    ALERT = "Alert"


# ------------------------------------------------------------------ limits


@dataclass(frozen=True)
class SensorLimits:
    """Optional sensor rule: |z| warning and alert limits (proposed 3 and 5, UCS §6.4)."""

    warning: float = 3.0
    alert: float = 5.0

    def __post_init__(self) -> None:
        if not 0 < self.warning < self.alert:
            raise ScoringError("Sensor limits need 0 < warning < alert")


@dataclass(frozen=True)
class Limits:
    """DI warning and alert limits in %, DIref, and any per-sensor |z| rules."""

    di_warning: float
    di_alert: float
    di_ref: float | None = None  # default 2 x di_alert
    sensors: Mapping[str, SensorLimits] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0 < self.di_warning < self.di_alert:
            raise ScoringError("DI limits need 0 < warning < alert")
        if self.di_ref is not None and not self.di_ref > 0:
            raise ScoringError("DIref must be positive")

    @property
    def reference(self) -> float:
        return self.di_ref if self.di_ref is not None else 2.0 * self.di_alert


# ------------------------------------------------------------------ inputs and outputs


@dataclass(frozen=True)
class SensorInput:
    tag: str
    actual: float | None  # latest sample at or before the cycle (None: no value)
    predicted: float | None  # None only when the model was not run
    usable: bool  # from the data-quality rules


@dataclass(frozen=True)
class SensorOutput:
    tag: str
    actual: float | None
    predicted: float | None
    usable: bool
    residual: float | None = None
    q: float | None = None
    z: float | None = None
    contribution: float | None = None  # share of DI (0-1); usable sensors only


@dataclass(frozen=True)
class ModelOutput:
    status: RuntimeStatus
    band: Band
    coverage: float  # |V| / number of model sensors
    sensors: tuple[SensorOutput, ...]
    di: float | None = None
    health: float | None = None

    def top_contributors(self, count: int = 5) -> list[SensorOutput]:
        """Usable sensors by descending contribution (UCS §6.7.1: top five by default)."""
        ranked = [s for s in self.sensors if s.contribution is not None]
        ranked.sort(key=lambda s: s.contribution or 0.0, reverse=True)
        return ranked[:count]


# ------------------------------------------------------------------ computation


def health_score(di: float, di_ref: float) -> float:
    return 100.0 * max(0.0, 1.0 - di / di_ref)


def band_for(
    di: float,
    limits: Limits,
    sensor_severities: Sequence[Severity] = (),
) -> Band:
    """UCS §6.5: Alert if DI >= alert limit or a sensor alert; Watch if DI >= warning
    limit or a sensor warning; otherwise Healthy."""
    if di >= limits.di_alert or Severity.ALERT in sensor_severities:
        return Band.ALERT
    if di >= limits.di_warning or Severity.WARNING in sensor_severities:
        return Band.WATCH
    return Band.HEALTHY


def _z_severity(z: float, sensor_limits: SensorLimits) -> Severity | None:
    if abs(z) >= sensor_limits.alert:
        return Severity.ALERT
    if abs(z) >= sensor_limits.warning:
        return Severity.WARNING
    return None


def _finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def compute_outputs(
    sensors: Sequence[SensorInput],
    scales: Mapping[str, SensorScale],
    limits: Limits,
    status: RuntimeStatus = RuntimeStatus.RUNNING,
    sensor_alerts: Mapping[str, Severity] | None = None,
) -> ModelOutput:
    """Outputs for one model and cycle.

    `sensor_alerts` are the active sensor alerts by tag, from the alert engine (4.2).
    Without them the band uses each usable sensor's current |z| against its limits.
    """
    if not sensors:
        raise ScoringError("A model needs at least one sensor")
    tags = [s.tag for s in sensors]
    if len(set(tags)) != len(tags):
        raise ScoringError("Duplicate sensor tags")
    usable = [s for s in sensors if s.usable]
    coverage = len(usable) / len(sensors)

    if status is not RuntimeStatus.RUNNING:
        plain = tuple(SensorOutput(s.tag, s.actual, s.predicted, s.usable) for s in sensors)
        return ModelOutput(status, Band.UNKNOWN, coverage, plain)
    for s in sensors:
        if s.usable and not (_finite(s.actual) and _finite(s.predicted)):
            raise ScoringError(f"Usable sensor {s.tag} needs an actual and a prediction")
    if not usable:
        raise ScoringError("No usable sensor: the coverage rule should have stopped scoring")

    missing = [t for t in tags if t not in scales]
    if missing:
        raise ScoringError(f"No training scale for: {', '.join(missing)}")

    per_sensor: dict[str, tuple[float, float, float]] = {}  # residual, q, z
    for s in sensors:
        actual, predicted = s.actual, s.predicted
        if actual is None or predicted is None or not math.isfinite(actual - predicted):
            continue
        residual = actual - predicted
        scale = scales[s.tag]
        per_sensor[s.tag] = (residual, abs(residual) / scale.range, residual / scale.sigma)

    sum_q2 = math.fsum(per_sensor[s.tag][1] ** 2 for s in usable)
    di = 100.0 * math.sqrt(sum_q2 / len(usable))

    outputs = []
    for s in sensors:
        values = per_sensor.get(s.tag)
        if values is None:
            outputs.append(SensorOutput(s.tag, s.actual, s.predicted, s.usable))
            continue
        residual, q, z = values
        contribution = (q * q / sum_q2 if sum_q2 > 0 else 0.0) if s.usable else None
        outputs.append(
            SensorOutput(s.tag, s.actual, s.predicted, s.usable, residual, q, z, contribution)
        )

    if sensor_alerts is not None:
        severities = [sensor_alerts[s.tag] for s in usable if s.tag in sensor_alerts]
    else:
        severities = [
            severity
            for s in usable
            if s.tag in limits.sensors
            and (severity := _z_severity(per_sensor[s.tag][2], limits.sensors[s.tag]))
        ]
    return ModelOutput(
        status=status,
        band=band_for(di, limits, severities),
        coverage=coverage,
        sensors=tuple(outputs),
        di=di,
        health=health_score(di, limits.reference),
    )
