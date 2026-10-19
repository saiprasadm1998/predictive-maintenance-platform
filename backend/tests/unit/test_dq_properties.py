"""Property-based tests of the data-quality rules with generated signals (ARC §12.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from pmp.dataquality import DEFAULTS, Ne107, Rule
from pmp.dataquality.domain import (
    RULE_ORDER,
    STATUS_OF,
    Samples,
    SensorConfig,
    evaluate_rules,
    evaluate_sensor,
    state_for,
    to_ns,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
CONFIG = SensorConfig(range_lo=0.0, range_hi=100.0, interval_s=60)

values = st.floats(min_value=-20.0, max_value=120.0, allow_nan=False, width=32)
qualities = st.sampled_from([0, 0, 0, 0, 1, 2])
signals = st.lists(st.tuples(values, qualities), min_size=1, max_size=80)
gaps = st.lists(st.integers(min_value=30, max_value=400), min_size=80, max_size=80)


def build(signal: list[tuple[float, int]], gap_s: list[int]) -> Samples:
    t = T0
    rows = []
    for (v, q), gap in zip(signal, gap_s, strict=False):
        t += timedelta(seconds=gap)
        rows.append((t, v, q))
    return Samples.from_rows(rows)


@settings(max_examples=200, deadline=None)
@given(signal=signals, gap_s=gaps, offset=st.integers(min_value=0, max_value=900))
def test_live_evaluation_matches_the_full_series(
    signal: list[tuple[float, int]], gap_s: list[int], offset: int
) -> None:
    """The live cycle sees only the last 30 samples; the preview sees the whole history.
    They must agree, so the preview predicts exactly what scoring will do."""
    full = build(signal, gap_s)
    at_ns = int(full.ts[-1]) + offset * 1_000_000_000
    at = datetime.fromtimestamp(at_ns / 1e9, tz=UTC)
    tail = Samples(full.ts[-30:], full.value[-30:], full.quality[-30:])
    whole = RULE_ORDER[evaluate_rules(full, CONFIG, DEFAULTS, np.array([at_ns]))[0]]
    assert evaluate_sensor(tail, CONFIG, DEFAULTS, at).rule is whole


@settings(max_examples=200, deadline=None)
@given(signal=signals, gap_s=gaps)
def test_every_cycle_has_exactly_one_consistent_status(
    signal: list[tuple[float, int]], gap_s: list[int]
) -> None:
    s = build(signal, gap_s)
    cycles = np.arange(
        int(s.ts[0]) - 60_000_000_000, int(s.ts[-1]) + 600_000_000_000, 60_000_000_000
    )
    for code in evaluate_rules(s, CONFIG, DEFAULTS, cycles):
        rule = RULE_ORDER[code]
        state = state_for(rule, DEFAULTS)
        assert state.status is STATUS_OF[rule]
        assert state.usable == (rule in (Rule.NONE, Rule.UNCERTAIN_QUALITY))


@settings(max_examples=200, deadline=None)
@given(signal=signals, gap_s=gaps)
def test_bad_quality_always_fails_the_sensor(
    signal: list[tuple[float, int]], gap_s: list[int]
) -> None:
    s = build([*signal[:-1], (signal[-1][0], 2)], gap_s)
    at = datetime.fromtimestamp(int(s.ts[-1]) / 1e9, tz=UTC)
    state = evaluate_sensor(s, CONFIG, DEFAULTS, at)
    assert state.rule is Rule.BAD_QUALITY
    assert state.status is Ne107.FAILURE


@settings(max_examples=200, deadline=None)
@given(
    phase=st.floats(min_value=0, max_value=6.3),
    amplitude=st.floats(min_value=1.0, max_value=10.0),
    level=st.floats(min_value=20.0, max_value=80.0),
)
def test_a_healthy_signal_is_always_good(phase: float, amplitude: float, level: float) -> None:
    """In range, good quality, on time, moving, and no jumps: never flagged."""
    rows = [
        (T0 + timedelta(minutes=i), level + amplitude * np.sin(phase + i / 4), 0) for i in range(60)
    ]
    s = Samples.from_rows(rows)
    cycles = to_ns([T0 + timedelta(minutes=i, seconds=30) for i in range(30, 60)])
    assert set(evaluate_rules(s, CONFIG, DEFAULTS, cycles)) == {RULE_ORDER.index(Rule.NONE)}


@settings(max_examples=100, deadline=None)
@given(level=st.floats(min_value=1.0, max_value=99.0), n=st.integers(min_value=30, max_value=60))
def test_a_constant_signal_is_always_a_flatline(level: float, n: int) -> None:
    rows = [(T0 + timedelta(minutes=i), level, 0) for i in range(n)]
    state = evaluate_sensor(
        Samples.from_rows(rows), CONFIG, DEFAULTS, T0 + timedelta(minutes=n - 1)
    )
    assert state.rule is Rule.FLATLINE
