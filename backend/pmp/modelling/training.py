"""Baseline training: assemble data, scale, fit, play back the validation period
(UC-05 steps 3, 7 and 8; UCS §6.2, §6.4; ARC §5.2).

Data is laid out on the model's cycle grid with sample-and-hold and the data-quality
rules, exactly as scoring will see it, so training and runtime agree. A cycle is retained
when it is in the operating mode and passes the coverage rule (at least 70 % of sensors
usable and every required sensor usable). Outlier removal and the full validation metrics
arrive in Phase 7 (7.2, 7.3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from pmp.modelling.algorithms.contract import Detector
from pmp.modelling.expressions import Expression
from pmp.modelling.scaling import SensorScale, scale_with_floors

MIN_VECTORS = 2000  # UCS §6.4 minimum data
MIN_RETAINED_SHARE = 0.5
MIN_COVERAGE = 0.70  # UCS §6.1 model coverage rule
MAD_TO_SIGMA = 1.4826


class TrainingError(Exception):
    """Training cannot produce a valid version; the message is shown to the engineer."""


@dataclass(frozen=True)
class SensorInfo:
    name: str  # source name, also the column name
    required: bool
    instrument_range: float


@dataclass(frozen=True)
class Assembled:
    """One period set on the cycle grid: sensor values (NaN where not usable)."""

    frame: pd.DataFrame  # index: cycle times (UTC); columns: sensors in model order
    in_mode: npt.NDArray[np.bool_]
    covered: npt.NDArray[np.bool_]

    @property
    def cycles(self) -> int:
        return len(self.frame)

    @property
    def retained(self) -> npt.NDArray[np.bool_]:
        return np.asarray(self.in_mode & self.covered, dtype=bool)


def assemble(
    cycle_ns: npt.NDArray[np.int64],
    sensors: Sequence[SensorInfo],
    values: Mapping[str, npt.NDArray[np.float64]],
    usable: Mapping[str, npt.NDArray[np.bool_]],
    filters: Sequence[Expression],
) -> Assembled:
    """Build the frame from held values and usable flags per tag (sensors and filter tags)."""
    index = pd.DatetimeIndex(pd.to_datetime(cycle_ns, unit="ns", utc=True))
    columns = [s.name for s in sensors]
    data = {name: np.where(usable[name], values[name], np.nan) for name in columns}
    frame = pd.DataFrame(data, index=index, columns=columns)

    in_mode = np.ones(len(cycle_ns), dtype=bool)
    if filters:
        names = sorted(set().union(*(f.names for f in filters)))
        filter_frame = pd.DataFrame(
            {n: np.where(usable[n], values[n], np.nan) for n in names}, index=index
        )
        for expression in filters:
            in_mode &= expression.evaluate_frame(filter_frame)

    present = frame.notna().to_numpy()
    share = present.mean(axis=1) if columns else np.zeros(len(frame))
    required = [i for i, s in enumerate(sensors) if s.required]
    covered = share >= MIN_COVERAGE
    if required:
        covered &= present[:, required].all(axis=1)
    return Assembled(frame, in_mode, np.asarray(covered, dtype=bool))


@dataclass(frozen=True)
class SensorStats:
    median: float
    p1: float
    p99: float
    raw_sigma: float
    scale: SensorScale
    validation_count: int
    bias: float  # mean residual over the validation period
    nrmse: float  # RMSE / R

    def as_dict(self) -> dict[str, Any]:
        return {
            "median": self.median,
            "p1": self.p1,
            "p99": self.p99,
            "range": self.scale.range,
            "range_floored": self.scale.range_floored,
            "residual_sigma_raw": self.raw_sigma,
            "sigma": self.scale.sigma,
            "sigma_floored": self.scale.sigma_floored,
        }


@dataclass(frozen=True)
class TrainingResult:
    detector: Detector
    sensors: dict[str, SensorStats]  # in model order
    training_cycles: int
    training_retained: int
    validation_cycles: int
    validation_retained: int

    def scaling(self) -> dict[str, Any]:
        return {
            "sensor_order": list(self.sensors),
            "sensors": {name: s.as_dict() for name, s in self.sensors.items()},
        }

    def validation(self) -> dict[str, Any]:
        return {
            "cycles": self.validation_cycles,
            "retained": self.validation_retained,
            "sensors": {
                name: {
                    "count": s.validation_count,
                    "bias": s.bias,
                    "nrmse": s.nrmse,
                    "sigma": s.scale.sigma,
                }
                for name, s in self.sensors.items()
            },
        }


def check_minimum_data(data: Assembled) -> None:
    """UC-05 6a: at least 2,000 retained vectors and 50 % of the selected period."""
    retained = int(data.retained.sum())
    if retained < MIN_VECTORS:
        raise TrainingError(
            f"Training blocked: only {retained:,} clean samples; at least {MIN_VECTORS:,} are "
            "needed. Extend the training period or relax the operating-mode filter."
        )
    share = retained / data.cycles
    if share < MIN_RETAINED_SHARE:
        raise TrainingError(
            f"Training blocked: only {share:.0%} of the selected period is usable; at least "
            f"{MIN_RETAINED_SHARE:.0%} is needed. Choose a period with better data or relax "
            "the operating-mode filter."
        )


def _mad_sigma(residuals: npt.NDArray[np.float64]) -> float:
    if len(residuals) == 0:
        return 0.0
    centre = float(np.median(residuals))
    return MAD_TO_SIGMA * float(np.median(np.abs(residuals - centre)))


def train(
    detector_cls: type[Detector],
    params: Mapping[str, Any],
    sensors: Sequence[SensorInfo],
    training: Assembled,
    validation: Assembled,
) -> TrainingResult:
    """Fit on the retained training cycles and play back the validation period."""
    check_minimum_data(training)
    fit_rows = training.frame[training.retained]
    medians: dict[str, float] = {}
    percentiles: dict[str, tuple[float, float]] = {}
    ranges: dict[str, SensorScale] = {}
    for sensor in sensors:
        column = fit_rows[sensor.name].dropna().to_numpy(dtype=np.float64)
        if len(column) == 0:
            raise TrainingError(
                f"Training blocked: {sensor.name} has no usable value in the retained "
                "training data. Remove the sensor or choose another period."
            )
        p1, p99 = (float(v) for v in np.percentile(column, [1, 99]))
        medians[sensor.name] = float(np.median(column))
        percentiles[sensor.name] = (p1, p99)
        ranges[sensor.name] = scale_with_floors(p99 - p1, 0.0, sensor.instrument_range)

    def scaled(frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        for sensor in sensors:
            out[sensor.name] = (frame[sensor.name] - medians[sensor.name]) / ranges[
                sensor.name
            ].range
        return out

    detector = detector_cls()
    detector.fit(scaled(fit_rows), dict(params))

    playback = validation.frame[validation.retained]
    if playback.empty:
        raise TrainingError(
            "Validation blocked: no usable cycles in the validation period. Choose a period "
            "with data in the operating mode."
        )
    predicted = detector.predict(scaled(playback))
    stats: dict[str, SensorStats] = {}
    for sensor in sensors:
        r = ranges[sensor.name].range
        estimate = predicted[sensor.name].to_numpy(dtype=np.float64) * r + medians[sensor.name]
        actual = playback[sensor.name].to_numpy(dtype=np.float64)
        residuals = (actual - estimate)[~np.isnan(actual)]
        raw_sigma = _mad_sigma(residuals)
        p1, p99 = percentiles[sensor.name]
        stats[sensor.name] = SensorStats(
            median=medians[sensor.name],
            p1=p1,
            p99=p99,
            raw_sigma=raw_sigma,
            scale=scale_with_floors(p99 - p1, raw_sigma, sensor.instrument_range),
            validation_count=len(residuals),
            bias=float(residuals.mean()) if len(residuals) else 0.0,
            nrmse=float(np.sqrt(np.mean(residuals**2)) / r) if len(residuals) else 0.0,
        )
    return TrainingResult(
        detector=detector,
        sensors=stats,
        training_cycles=training.cycles,
        training_retained=int(training.retained.sum()),
        validation_cycles=validation.cycles,
        validation_retained=int(validation.retained.sum()),
    )
