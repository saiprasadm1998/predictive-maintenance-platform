"""Validation report and proposed limits (plan 7.3, UCS §6.4): formulas by hand."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from pmp.modelling.validation import (
    count_alerts,
    deviation_index,
    propose_limits,
    validation_report,
)


def test_deviation_index_is_the_rms_of_normalised_residuals_over_usable_sensors() -> None:
    actual = pd.DataFrame({"a": [12.0, 10.0, np.nan], "b": [5.0, np.nan, np.nan]})
    predicted = pd.DataFrame({"a": [10.0, 10.0, 10.0], "b": [4.0, 4.0, 4.0]})
    di = deviation_index(actual, predicted, {"a": 20.0, "b": 10.0})
    # cycle 1: q = 0.1 and 0.1 -> 100 x sqrt((0.01 + 0.01) / 2) = 10
    assert di[0] == pytest.approx(10.0)
    assert di[1] == pytest.approx(0.0)  # only a is usable, and it is on target
    assert math.isnan(di[2])  # nothing usable


@pytest.mark.parametrize(
    ("p99", "p999", "warning", "alert"),
    [
        (10.0, 20.0, 12.0, 30.0),  # 1.2 x 10; 1.5 x 20
        (10.0, 8.0, 12.0, 13.2),  # 1.5 x 8 = 12 is not 10 % above 12: 1.1 x 12
        (3.33, 4.0, 4.0, 6.0),  # 1.2 x 3.33 = 3.996 rounds up to 4.0
    ],
)
def test_proposed_limits_follow_ucs_6_4(
    p99: float, p999: float, warning: float, alert: float
) -> None:
    proposed = propose_limits({"P50": 1.0, "P95": 2.0, "P99": p99, "P99.9": p999})
    assert (proposed.di_warning, proposed.di_alert) == (warning, alert)
    assert (proposed.sensor_warning, proposed.sensor_alert) == (3.0, 5.0)


def test_the_default_rule_needs_3_of_5_to_raise_and_5_below_the_deadband_to_clear() -> None:
    assert count_alerts([20, 20, 0, 0, 0, 0, 0], 10) == 0  # 2 of 5: not raised
    assert count_alerts([20, 0, 20, 0, 20], 10) == 1  # 3 of 5
    # raised, then 9.5 is below the limit but inside the 10 % deadband: it never clears,
    # so the next burst is the same alert
    assert count_alerts([20] * 3 + [9.5] * 10 + [20] * 3, 10) == 1
    # below 9 (the deadband) for 5 cycles clears; the next burst is a new alert
    assert count_alerts([20] * 3 + [5] * 5 + [20] * 3, 10) == 2
    assert count_alerts([20] * 3 + [5] * 4 + [20] * 3, 10) == 1  # 4 below: not cleared


def test_the_report_warns_above_one_false_alert_a_week() -> None:
    rng = np.random.default_rng(1)
    quiet = rng.gamma(2.0, 2.0, 7 * 1440)  # one week of one-minute cycles
    report = validation_report(quiet, 60, np.zeros(len(quiet), dtype=bool))
    assert set(report.di_percentiles) == {"P50", "P95", "P99", "P99.9"}
    assert report.proposed.di_warning == pytest.approx(
        math.ceil(1.2 * report.di_percentiles["P99"] * 10 - 1e-9) / 10
    )
    assert report.outside_envelope == 0.0
    assert report.alerts_per_week == report.alerts  # exactly one week

    bursts = quiet.copy()
    limit = report.proposed.di_warning
    for start in range(500, len(bursts), 2_000):  # five long bursts above the warning
        bursts[start : start + 10] = limit * 2
    noisy = validation_report(bursts, 60, None)  # bursts sit far above the new warning too
    assert noisy.alerts >= 5
    assert noisy.warning is not None
    assert "false alerts per week" in noisy.warning
    assert noisy.outside_envelope is None


def test_nothing_scored_is_refused() -> None:
    with pytest.raises(ValueError, match="No validation cycle"):
        validation_report(np.array([np.nan, np.nan]), 60)
