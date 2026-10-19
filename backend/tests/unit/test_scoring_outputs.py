"""Scoring outputs: edge cases around the UCS §6.2 and §6.5 formulas."""

from __future__ import annotations

import math

import pytest

from pmp.scoring import (
    RANGE_FLOOR,
    SIGMA_FLOOR,
    Band,
    Limits,
    RuntimeStatus,
    ScoringError,
    SensorInput,
    SensorLimits,
    SensorScale,
    Severity,
    band_for,
    compute_outputs,
    health_score,
    scale_with_floors,
)

LIMITS = Limits(di_warning=15, di_alert=25)
UNIT = SensorScale(range=10.0, sigma=1.0)


def run(*sensors: SensorInput, **kwargs: object) -> object:
    scales = {s.tag: UNIT for s in sensors}
    return compute_outputs(list(sensors), scales, kwargs.pop("limits", LIMITS), **kwargs)  # type: ignore[arg-type]


def test_contributions_sum_to_one_and_rank_descending() -> None:
    result = compute_outputs(
        [SensorInput(t, v, 0.0, True) for t, v in [("a", 1.0), ("b", 3.0), ("c", -2.0)]],
        dict.fromkeys("abc", UNIT),
        LIMITS,
    )
    assert math.isclose(sum(s.contribution or 0 for s in result.sensors), 1.0)
    assert [s.tag for s in result.top_contributors()] == ["b", "c", "a"]
    assert [s.tag for s in result.top_contributors(1)] == ["b"]
    signs = {s.tag: math.copysign(1, s.z or 0) for s in result.sensors}
    assert signs == {"a": 1, "b": 1, "c": -1}


def test_perfect_predictions_give_zero_di_and_full_health() -> None:
    result = compute_outputs([SensorInput("a", 5.0, 5.0, True)], {"a": UNIT}, LIMITS)
    assert (result.di, result.health, result.band) == (0.0, 100.0, Band.HEALTHY)
    assert result.sensors[0].contribution == 0.0


def test_excluded_sensors_keep_their_prediction_but_not_their_vote() -> None:
    result = compute_outputs(
        [SensorInput("a", 11.0, 10.0, True), SensorInput("x", None, 42.0, False)],
        {"a": UNIT, "x": UNIT},
        LIMITS,
    )
    excluded = result.sensors[1]
    assert excluded.predicted == 42.0
    assert (excluded.residual, excluded.q, excluded.z, excluded.contribution) == (None,) * 4
    assert result.coverage == 0.5
    assert math.isclose(result.di or 0, 10.0)


@pytest.mark.parametrize(
    "status",
    [s for s in RuntimeStatus if s is not RuntimeStatus.RUNNING],
)
def test_any_status_but_running_is_unknown_without_health(status: RuntimeStatus) -> None:
    result = compute_outputs(
        [SensorInput("a", 11.0, 10.0, True), SensorInput("b", None, None, False)],
        {},
        LIMITS,
        status,
    )
    assert result.band is Band.UNKNOWN
    assert result.di is None
    assert result.health is None
    assert result.coverage == 0.5


def test_active_sensor_alerts_replace_the_current_z_check() -> None:
    limits = Limits(15, 25, sensors={"a": SensorLimits()})
    sensors = [SensorInput("a", 14.0, 10.0, True), SensorInput("b", 10.0, 10.0, True)]
    scales = dict.fromkeys("ab", SensorScale(range=100.0, sigma=1.0))  # DI about 2.8 %
    assert compute_outputs(sensors, scales, limits).band is Band.WATCH  # |z| = 4 now
    no_alert = compute_outputs(sensors, scales, limits, sensor_alerts={})
    assert no_alert.band is Band.HEALTHY  # persistence not met yet: no active alert
    alert = compute_outputs(sensors, scales, limits, sensor_alerts={"b": Severity.ALERT})
    assert alert.band is Band.ALERT


def test_alerts_on_excluded_sensors_do_not_count() -> None:
    sensors = [SensorInput("a", 10.0, 10.0, True), SensorInput("b", None, 10.0, False)]
    result = compute_outputs(
        sensors, dict.fromkeys("ab", UNIT), LIMITS, sensor_alerts={"b": Severity.ALERT}
    )
    assert result.band is Band.HEALTHY


@pytest.mark.parametrize(
    ("di", "severities", "band"),
    [
        (14.999, (), Band.HEALTHY),
        (15.0, (), Band.WATCH),
        (24.999, (), Band.WATCH),
        (25.0, (), Band.ALERT),
        (1.0, (Severity.WARNING,), Band.WATCH),
        (1.0, (Severity.WARNING, Severity.ALERT), Band.ALERT),
        (20.0, (Severity.ALERT,), Band.ALERT),
    ],
)
def test_band_boundaries(di: float, severities: tuple[Severity, ...], band: Band) -> None:
    assert band_for(di, LIMITS, severities) is band


def test_health_is_fifty_at_the_alert_limit_and_clamped_at_zero() -> None:
    assert health_score(25.0, LIMITS.reference) == 50.0
    assert health_score(80.0, LIMITS.reference) == 0.0
    assert Limits(15, 25, di_ref=40).reference == 40


def test_floors_apply_only_when_needed() -> None:
    constant = scale_with_floors(0.0, 0.0, 15000.0)
    assert constant.range == RANGE_FLOOR * 15000.0
    assert constant.sigma == SIGMA_FLOOR * constant.range
    assert (constant.range_floored, constant.sigma_floored) == (True, True)
    normal = scale_with_floors(20.0, 2.0, 200.0)
    assert (normal.range, normal.sigma, normal.range_floored, normal.sigma_floored) == (
        20.0,
        2.0,
        False,
        False,
    )


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda: SensorScale(0.0, 1.0), "positive"),
        (lambda: SensorScale(1.0, float("nan")), "positive"),
        (lambda: scale_with_floors(1.0, 1.0, 0.0), "Instrument range"),
        (lambda: Limits(25, 15), "warning < alert"),
        (lambda: Limits(15, 25, di_ref=0), "DIref"),
        (lambda: SensorLimits(5, 3), "warning < alert"),
    ],
)
def test_invalid_scales_and_limits_are_refused(make: object, message: str) -> None:
    with pytest.raises(ScoringError, match=message):
        make()  # type: ignore[operator]


def test_inconsistent_inputs_are_refused() -> None:
    with pytest.raises(ScoringError, match="at least one sensor"):
        compute_outputs([], {}, LIMITS)
    with pytest.raises(ScoringError, match="Duplicate"):
        compute_outputs([SensorInput("a", 1, 1, True)] * 2, {"a": UNIT}, LIMITS)
    with pytest.raises(ScoringError, match="needs an actual"):
        compute_outputs([SensorInput("a", None, 1, True)], {"a": UNIT}, LIMITS)
    with pytest.raises(ScoringError, match="No usable sensor"):
        compute_outputs([SensorInput("a", 1, 1, False)], {"a": UNIT}, LIMITS)
    with pytest.raises(ScoringError, match="No training scale for: b"):
        compute_outputs(
            [SensorInput("a", 1, 1, True), SensorInput("b", 1, 1, True)], {"a": UNIT}, LIMITS
        )


def test_a_non_finite_excluded_value_is_ignored() -> None:
    result = compute_outputs(
        [SensorInput("a", 11.0, 10.0, True), SensorInput("b", float("inf"), 1.0, False)],
        dict.fromkeys("ab", UNIT),
        LIMITS,
    )
    assert result.sensors[1].residual is None
