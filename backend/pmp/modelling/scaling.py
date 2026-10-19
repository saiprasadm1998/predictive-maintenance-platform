"""Per-sensor training statistics used to score: training range R and residual sigma.

R = P99 - P1 of a sensor's cleansed training data; sigma = 1.4826 x MAD of its residuals
over the validation period (UCS §6.2). A sensor that did not move in training would have
R = 0 or sigma = 0, so R is floored at 1 % of the instrument range and sigma at 1 % of R,
and the floor is recorded (implementation plan, decision for 2.3). Training (3.2) produces
these values; scoring (pmp.scoring) uses them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

RANGE_FLOOR = 0.01  # x instrument range
SIGMA_FLOOR = 0.01  # x training range


class ScaleError(ValueError):
    """Training statistics that cannot be used."""


@dataclass(frozen=True)
class SensorScale:
    """A sensor's training range R and residual sigma, after any floor."""

    range: float
    sigma: float
    range_floored: bool = False
    sigma_floored: bool = False

    def __post_init__(self) -> None:
        if not (self.range > 0 and self.sigma > 0) or not math.isfinite(self.range + self.sigma):
            raise ScaleError("Training range and residual sigma must be positive")


def scale_with_floors(
    training_range: float, residual_sigma: float, instrument_range: float
) -> SensorScale:
    """R and sigma from training, floored so q and z are always defined."""
    if not instrument_range > 0:
        raise ScaleError("Instrument range must be positive")
    range_floor = RANGE_FLOOR * instrument_range
    value_range = max(training_range, range_floor) if math.isfinite(training_range) else range_floor
    sigma_floor = SIGMA_FLOOR * value_range
    sigma = max(residual_sigma, sigma_floor) if math.isfinite(residual_sigma) else sigma_floor
    return SensorScale(
        range=value_range,
        sigma=sigma,
        range_floored=not training_range >= range_floor,
        sigma_floored=not residual_sigma >= sigma_floor,
    )
