"""Data-quality rules, one test per row of the UCS §6.1 table (FR-DQ-01 to -03, AC-03).

Every rule triggers on a synthetic signal and clears when the condition ends
(FR-DQ-01 acceptance), and the first matching rule wins.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from pmp.dataquality import (
    DEFAULTS,
    PARAM_NAMES,
    DataQualityError,
    Effect,
    Ne107,
    Rule,
    RuleParams,
)
from pmp.dataquality.domain import (
    RULE_ORDER,
    Samples,
    SensorConfig,
    SensorState,
    evaluate_rules,
    evaluate_sensor,
    parse_overrides,
    resolve_params,
    to_ns,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
GOOD, UNCERTAIN, BAD = 0, 1, 2
CONFIG = SensorConfig(range_lo=0.0, range_hi=100.0, interval_s=60)  # range 100


def minute(i: int) -> datetime:
    return T0 + timedelta(minutes=i)


def healthy(n: int = 40) -> list[float]:
    """A live signal: ±3 % of range, well above the flatline threshold."""
    return [50.0 + 3.0 * np.sin(i / 3) for i in range(n)]


def samples(values: Sequence[float], quality: Sequence[int] | None = None) -> Samples:
    q = quality if quality is not None else [GOOD] * len(values)
    return Samples.from_rows([(minute(i), v, q[i]) for i, v in enumerate(values)])


def at_last(values: Sequence[float], **kwargs: object) -> SensorState:
    params = kwargs.pop("params", DEFAULTS)
    config = kwargs.pop("config", CONFIG)
    quality = kwargs.pop("quality", None)
    excluded = bool(kwargs.pop("excluded", False))
    return evaluate_sensor(
        samples(values, quality),  # type: ignore[arg-type]
        config,  # type: ignore[arg-type]
        params,  # type: ignore[arg-type]
        minute(len(values) - 1),
        excluded,
    )


def rules_over_time(values: Sequence[float], quality: Sequence[int] | None = None) -> list[Rule]:
    cycles = to_ns([minute(i) for i in range(len(values))])
    codes = evaluate_rules(samples(values, quality), CONFIG, DEFAULTS, cycles)
    return [RULE_ORDER[c] for c in codes]


# ------------------------------------------------------------------ one row each


def test_good_signal_is_good_and_used() -> None:
    state = at_last(healthy())
    assert state == SensorState(Ne107.GOOD, Rule.NONE, Effect.USED)
    assert state.usable


def test_bad_source_quality_is_failure_and_excluded() -> None:
    quality = [GOOD] * 39 + [BAD]
    state = at_last(healthy(), quality=quality)
    assert state == SensorState(Ne107.FAILURE, Rule.BAD_QUALITY, Effect.EXCLUDED)


def test_stale_after_more_than_three_intervals() -> None:
    s = samples(healthy())
    last = minute(39)
    at_limit = evaluate_sensor(s, CONFIG, DEFAULTS, last + timedelta(seconds=180))
    beyond = evaluate_sensor(s, CONFIG, DEFAULTS, last + timedelta(seconds=181))
    assert at_limit.rule is Rule.NONE  # exactly 3 times the interval is not yet stale
    assert beyond == SensorState(Ne107.FAILURE, Rule.STALE, Effect.EXCLUDED)


def test_no_samples_at_all_is_stale() -> None:
    state = evaluate_sensor(Samples.empty(), CONFIG, DEFAULTS, T0)
    assert state.rule is Rule.STALE
    assert state.status is Ne107.FAILURE


def test_manual_exclusion_is_function_check() -> None:
    state = at_last(healthy(), excluded=True)
    assert state == SensorState(Ne107.FUNCTION_CHECK, Rule.MANUAL_EXCLUSION, Effect.EXCLUDED)


@pytest.mark.parametrize("value", [-0.1, 100.1])
def test_out_of_instrument_range(value: float) -> None:
    values = [*healthy(39), value]
    values[-2] = value  # no jump, so only the range rule applies
    state = at_last(values)
    assert state == SensorState(Ne107.OUT_OF_SPECIFICATION, Rule.OUT_OF_RANGE, Effect.EXCLUDED)


def test_range_limits_themselves_are_in_range() -> None:
    assert at_last([*healthy(38), 100.0, 100.0]).rule is not Rule.OUT_OF_RANGE


def test_flatline_is_maintenance_required_and_excluded() -> None:
    values = [*healthy(10), *[42.0] * 30]
    state = at_last(values)
    assert state == SensorState(Ne107.MAINTENANCE_REQUIRED, Rule.FLATLINE, Effect.EXCLUDED)


def test_flatline_needs_a_full_window() -> None:
    assert at_last([*healthy(20), *[42.0] * 29]).rule is Rule.NONE


def test_flatline_threshold_is_point_one_percent_of_range() -> None:
    # standard deviation 0.09 (below 0.1) flags; 0.11 does not
    low = [42.0 + (0.09 if i % 2 else -0.09) for i in range(30)]
    high = [42.0 + (0.11 if i % 2 else -0.11) for i in range(30)]
    assert at_last(low).rule is Rule.FLATLINE
    assert at_last(high).rule is Rule.NONE


def test_flatline_can_be_configured_to_used() -> None:
    params = DEFAULTS.with_overrides({"flatline_used": True})
    state = at_last([*[42.0] * 30], params=params)
    assert state == SensorState(Ne107.MAINTENANCE_REQUIRED, Rule.FLATLINE, Effect.USED)


def test_flatline_guard_uses_training_standard_deviation() -> None:
    constant_in_training = SensorConfig(0.0, 100.0, 60, reference_range=100.0, training_std=0.5)
    lively_in_training = SensorConfig(0.0, 100.0, 60, reference_range=100.0, training_std=5.0)
    flat = [42.0] * 30
    assert at_last(flat, config=constant_in_training).rule is Rule.NONE  # 0.5 ≤ 1 % of 100
    assert at_last(flat, config=lively_in_training).rule is Rule.FLATLINE


def test_spike_excludes_the_sample_for_that_cycle() -> None:
    values = [*healthy(39), 50.0 + 26.0]  # jump > 25 % of range
    values[-2] = 50.0
    state = at_last(values)
    assert state == SensorState(Ne107.MAINTENANCE_REQUIRED, Rule.SPIKE, Effect.SAMPLE_EXCLUDED)
    assert not state.usable


def test_jump_of_exactly_25_percent_is_not_a_spike() -> None:
    values = [*healthy(38), 50.0, 75.0]
    assert at_last(values).rule is Rule.NONE


def test_uncertain_quality_is_used_and_flagged() -> None:
    quality = [GOOD] * 39 + [UNCERTAIN]
    state = at_last(healthy(), quality=quality)
    assert state == SensorState(
        Ne107.MAINTENANCE_REQUIRED, Rule.UNCERTAIN_QUALITY, Effect.USED_FLAGGED
    )
    assert state.usable


def test_training_range_replaces_instrument_range() -> None:
    narrow = SensorConfig(0.0, 100.0, 60, reference_range=20.0)
    values = [*healthy(38), 50.0, 56.0]  # 6 is 30 % of 20 but only 6 % of 100
    assert at_last(values).rule is Rule.NONE
    assert at_last(values, config=narrow).rule is Rule.SPIKE


# ------------------------------------------------------------------ order


@pytest.mark.parametrize(
    ("winner", "loser", "values", "quality", "excluded", "late_s"),
    [
        (Rule.BAD_QUALITY, Rule.STALE, healthy(), [GOOD] * 39 + [BAD], False, 600),
        (Rule.STALE, Rule.MANUAL_EXCLUSION, healthy(), None, True, 600),
        (Rule.MANUAL_EXCLUSION, Rule.OUT_OF_RANGE, [*healthy(38), 150.0, 150.0], None, True, 0),
        (Rule.OUT_OF_RANGE, Rule.FLATLINE, [150.0] * 30, None, False, 0),
        (Rule.FLATLINE, Rule.UNCERTAIN_QUALITY, [42.0] * 30, [UNCERTAIN] * 30, False, 0),
        (
            Rule.SPIKE,
            Rule.UNCERTAIN_QUALITY,
            [*healthy(38), 50.0, 90.0],
            [GOOD] * 39 + [UNCERTAIN],
            False,
            0,
        ),
        (Rule.OUT_OF_RANGE, Rule.SPIKE, [*healthy(38), 50.0, 150.0], None, False, 0),
    ],
)
def test_first_matching_rule_wins(
    winner: Rule,
    loser: Rule,
    values: list[float],
    quality: list[int] | None,
    excluded: bool,
    late_s: int,
) -> None:
    at = minute(len(values) - 1) + timedelta(seconds=late_s)
    state = evaluate_sensor(samples(values, quality), CONFIG, DEFAULTS, at, excluded)
    assert state.rule is winner
    assert RULE_ORDER.index(winner) < RULE_ORDER.index(loser)


def test_rule_order_matches_ucs_table() -> None:
    assert [r.value for r in RULE_ORDER] == [
        "bad_quality",
        "stale",
        "manual_exclusion",
        "out_of_range",
        "flatline",
        "spike",
        "uncertain_quality",
        "none",
    ]


# ------------------------------------------------------------------ clearing


def test_bad_quality_clears_when_good_returns() -> None:
    q = [GOOD] * 10 + [BAD] * 5 + [GOOD] * 5
    rules = rules_over_time(healthy(20), q)
    assert rules[12] is Rule.BAD_QUALITY
    assert rules[-1] is Rule.NONE


def test_flatline_clears_when_the_signal_moves_again() -> None:
    values = [*[42.0] * 30, *healthy(40)[10:]]
    rules = rules_over_time(values)
    assert rules[29] is Rule.FLATLINE
    assert rules[-1] is Rule.NONE


def test_spike_lasts_only_its_own_sample() -> None:
    values = healthy(20)
    values[10] = values[9] + 30.0
    values[11] = values[10]  # holds high: no new jump
    rules = rules_over_time(values)
    assert rules[10] is Rule.SPIKE
    assert rules[11] is Rule.NONE


def test_stale_clears_when_data_arrives() -> None:
    s = samples(healthy(20))
    gap = to_ns([minute(19) + timedelta(minutes=10)])
    resumed = Samples.from_rows(
        [(minute(i), 50.0 + 3.0 * np.sin(i / 3), GOOD) for i in [*range(20), 30]]
    )
    assert RULE_ORDER[evaluate_rules(s, CONFIG, DEFAULTS, gap)[0]] is Rule.STALE
    assert evaluate_sensor(resumed, CONFIG, DEFAULTS, minute(30)).rule is Rule.NONE


def test_out_of_range_clears_when_back_in_range() -> None:
    values = [*healthy(10), 101.0, 101.0, *healthy(20)[12:]]
    rules = rules_over_time(values)
    assert rules[11] is Rule.OUT_OF_RANGE
    assert rules[-1] is Rule.NONE


# ------------------------------------------------------------------ switches and parameters


def test_a_disabled_rule_is_skipped() -> None:
    params = DEFAULTS.with_overrides({"flatline": "off"})
    assert at_last([42.0] * 30, params=params).rule is Rule.NONE


def test_manual_exclusion_cannot_be_switched_off() -> None:
    with pytest.raises(DataQualityError, match="Unknown rule parameter"):
        parse_overrides({"manual_exclusion": False})


def test_thresholds_can_be_overridden() -> None:
    params = DEFAULTS.with_overrides({"spike_pct": "40"})
    values = [*healthy(38), 50.0, 80.0]  # 30 % jump
    assert at_last(values).rule is Rule.SPIKE
    assert at_last(values, params=params).rule is Rule.NONE


def test_layers_apply_global_then_role_then_tag() -> None:
    params = resolve_params(
        {"spike_pct": 30}, {"spike_pct": 35, "stale_factor": 5}, {"spike_pct": 40}
    )
    assert (params.spike_pct, params.stale_factor) == (40.0, 5.0)


def test_defaults_are_the_ucs_defaults() -> None:
    assert RuleParams() == DEFAULTS
    assert (DEFAULTS.stale_factor, DEFAULTS.flatline_window) == (3.0, 30)
    assert (DEFAULTS.flatline_std_pct, DEFAULTS.flatline_guard_pct) == (0.1, 1.0)
    assert (DEFAULTS.spike_pct, DEFAULTS.flatline_used) == (25.0, False)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"spike_pct": 0}, "greater than 0"),
        ({"spike_pct": "abc"}, "must be a number"),
        ({"spike_pct": True}, "must be a number"),
        ({"spike_pct": "nan"}, "finite"),
        ({"flatline_window": 2.5}, "whole number"),
        ({"flatline_window": 1}, "whole number"),
        ({"stale": "maybe"}, "on or off"),
        ({"bogus": 1}, "Unknown rule parameter"),
    ],
)
def test_invalid_parameters_are_rejected(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(DataQualityError, match=message):
        parse_overrides(overrides)


def test_switches_accept_on_off_words() -> None:
    assert parse_overrides({"spike": "OFF", "stale": "on", "flatline_window": "20"}) == {
        "spike": False,
        "stale": True,
        "flatline_window": 20,
    }


def test_the_bad_quality_rule_cannot_be_switched_off() -> None:
    """PRD FR-ING-05: bad-quality samples are always excluded from scoring."""
    with pytest.raises(DataQualityError, match="cannot be changed"):
        parse_overrides({"bad_quality": "off"})
    assert "bad_quality" not in PARAM_NAMES
