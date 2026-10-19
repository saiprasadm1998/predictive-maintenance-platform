"""Model coverage rule (UCS §6.1, FR-DQ-03)."""

from __future__ import annotations

from pmp.dataquality import DEFAULTS, MIN_COVERAGE, Rule, coverage
from pmp.dataquality.domain import state_for

GOOD = state_for(Rule.NONE, DEFAULTS)
FAILED = state_for(Rule.STALE, DEFAULTS)
FLAGGED = state_for(Rule.UNCERTAIN_QUALITY, DEFAULTS)


def test_seventy_percent_usable_is_enough() -> None:
    states = dict.fromkeys(range(7), GOOD) | dict.fromkeys(range(7, 10), FAILED)
    result = coverage(states)
    assert result.share == MIN_COVERAGE == 0.70
    assert result.scoreable


def test_below_seventy_percent_is_insufficient() -> None:
    states = dict.fromkeys(range(6), GOOD) | dict.fromkeys(range(6, 10), FAILED)
    assert not coverage(states).scoreable


def test_one_failed_sensor_reduces_coverage_but_keeps_scoring() -> None:
    # FR-DQ-03 acceptance: the model scores on the remaining sensors
    states = dict.fromkeys(range(17), GOOD) | {17: FAILED}
    result = coverage(states)
    assert result.scoreable
    assert (result.usable, result.total) == (17, 18)


def test_a_failed_required_sensor_stops_scoring() -> None:
    states = dict.fromkeys(range(17), GOOD) | {17: FAILED}
    result = coverage(states, required={0, 17})
    assert not result.scoreable
    assert result.missing_required == (17,)


def test_uncertain_sensors_count_as_usable() -> None:
    assert coverage({1: FLAGGED, 2: FLAGGED}, required={1}).scoreable


def test_a_required_sensor_missing_from_the_states_is_not_usable() -> None:
    assert coverage({1: GOOD}, required={2}).missing_required == (2,)


def test_a_model_without_sensors_is_not_scoreable() -> None:
    result = coverage({})
    assert result.share == 0.0
    assert not result.scoreable
