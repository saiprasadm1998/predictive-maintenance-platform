"""Time-to-threshold forecasting (plan 8.3, UCS §6.8, FR-PRG-01, -02).

"Done when": a forecast on a synthetic ramp returns the analytical crossing time within 5 %.
"""

from __future__ import annotations

import numpy as np
import pytest

from pmp.prognostics import (
    MIN_POINTS,
    ForecastError,
    Method,
    Urgency,
    UrgencyBands,
    forecast,
)

T = np.arange(-7 * 96 + 1, 1) / 96.0  # 7 days of 15-minute means, in days up to now


def noise(scale: float, seed: int = 1) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0, scale, len(T))


def test_a_linear_ramp_crosses_at_the_analytical_time() -> None:
    y = 50 + 2.0 * T + noise(0.5)  # reaches 80 in 15 days
    f = forecast(T, y, 80)
    assert f.valid
    assert f.fit is not None
    assert f.fit.method is Method.LINEAR
    assert f.median_h == pytest.approx(15 * 24, rel=0.05)
    assert f.lower_h is not None
    assert f.median_h is not None
    assert f.upper_h is not None
    assert f.lower_h <= f.median_h <= f.upper_h
    assert f.urgency is Urgency.MEDIUM  # lower bound between 7 and 30 days


def test_an_exponential_rise_is_fitted_as_one() -> None:
    y = 40 + 5 * np.exp(0.3 * T) + noise(0.1)  # 40 + 5·e^(0.3t) = 70 at t = ln(6)/0.3
    f = forecast(T, y, 70)
    assert f.fit is not None
    assert f.fit.method is Method.EXPONENTIAL
    assert f.fit.adj_r2 >= (f.linear_adj_r2 or 0) + 0.05
    assert f.median_h == pytest.approx(np.log(6) / 0.3 * 24, rel=0.05)
    assert f.urgency is Urgency.HIGH


def test_a_lower_limit_is_reached_falling() -> None:
    t = T[-96 * 2 :]  # two days
    level = 5 - 2.0 * t + noise(0.05)[: len(t)]  # 5 now, falling at 2 per day
    f = forecast(t, level, 1.0, direction=-1)
    assert f.valid
    assert f.direction == -1
    assert f.median_h == pytest.approx(2 * 24, rel=0.05)  # 5 -> 1 at 2 per day
    assert f.urgency is Urgency.HIGH


def test_a_flat_trend_has_no_trend_to_threshold() -> None:
    f = forecast(T, 50 + noise(1.0), 80)
    assert not f.valid
    assert f.urgency is Urgency.NONE
    assert f.median_h is None
    assert f.reason is not None
    assert "R²" in f.reason


def test_a_trend_moving_away_has_no_trend_to_threshold() -> None:
    f = forecast(T, 50 - 2.0 * T + noise(0.5), 80)  # falling, away from the upper limit
    assert not f.valid
    assert f.urgency is Urgency.NONE
    assert f.reason is not None
    assert "not moving towards" in f.reason


def test_already_beyond_the_threshold_and_rising_is_immediate() -> None:
    f = forecast(T, 50 + 2.0 * T + noise(0.5), 45, direction=1)
    assert f.valid
    assert f.median_h == 0
    assert f.urgency is Urgency.IMMEDIATE


def test_the_bootstrap_is_repeatable_with_its_seed() -> None:
    y = 50 + 2.0 * T + noise(3.0)
    assert forecast(T, y, 80) == forecast(T, y, 80)
    assert forecast(T, y, 80, seed=7).median_h != forecast(T, y, 80).median_h


def test_a_forecast_needs_a_day_of_data() -> None:
    with pytest.raises(ForecastError, match="24 h"):
        forecast(T[: MIN_POINTS - 1], (50 + 2.0 * T)[: MIN_POINTS - 1], 80)


def test_urgency_follows_the_lower_bound_and_the_bands() -> None:
    bands = UrgencyBands()
    assert [bands.classify(h) for h in (None, 24, 25, 168, 169, 720, 721)] == [
        Urgency.NONE,
        Urgency.IMMEDIATE,
        Urgency.HIGH,
        Urgency.HIGH,
        Urgency.MEDIUM,
        Urgency.MEDIUM,
        Urgency.LOW,
    ]
    assert UrgencyBands(immediate_h=48).classify(30) is Urgency.IMMEDIATE
