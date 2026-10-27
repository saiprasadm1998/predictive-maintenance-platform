"""Training-data cleansing (plan 7.2): each rule on its own, in order, and the clusters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from pmp.modelling.cleansing import RULES, cleanse, in_periods, robust_z
from pmp.modelling.definitions import Period

T0 = datetime(2026, 9, 1, tzinfo=UTC)


def frame(n: int = 3_000, seed: int = 3) -> pd.DataFrame:
    """Two operating states (low and high load) of three related sensors."""
    rng = np.random.default_rng(seed)
    load = np.where(np.arange(n) % 600 < 300, 30.0, 80.0) + rng.normal(0, 1, n)
    index = pd.date_range(T0, periods=n, freq="min", tz="UTC")
    return pd.DataFrame(
        {
            "flow": load + rng.normal(0, 0.5, n),
            "temp": 0.5 * load + 40 + rng.normal(0, 0.5, n),
            "vib": 0.02 * load + rng.normal(0, 0.05, n),
        },
        index=index,
    )


def test_clean_data_loses_only_the_multivariate_tail_and_shows_both_states() -> None:
    result = cleanse(frame(), np.ones(3_000, bool), np.ones(3_000, bool))
    assert list(result.removed) == list(RULES)
    assert result.removed["mode"] == result.removed["quality"] == 0
    assert result.removed["excluded"] == result.removed["outlier"] == 0
    assert 0 < result.removed["multivariate"] <= 3  # 0.1 % of 3,000
    assert len(result.clusters) >= 2  # low and high load
    assert sum(c.cycles for c in result.clusters) == result.kept
    assert result.clusters[0].share == pytest.approx(0.5, abs=0.05)


def test_rules_run_in_order_and_each_counts_only_what_it_removed() -> None:
    data = frame()
    in_mode = np.ones(len(data), bool)
    in_mode[:100] = False
    covered = np.ones(len(data), bool)
    covered[50:150] = False  # half already outside the mode
    excluded = Period(T0 + timedelta(minutes=140), T0 + timedelta(minutes=200))
    result = cleanse(data, in_mode, covered, [excluded])
    assert result.removed["mode"] == 100
    assert result.removed["quality"] == 50  # 100 to 149: the other 50 went with the mode
    assert result.removed["excluded"] == 50  # 150 to 199
    assert not result.retained[:200].any()


def test_a_spike_on_one_sensor_removes_its_whole_cycle() -> None:
    data = frame()
    data.iloc[1_000, 2] = 5.0  # vib jumps far beyond |robust z| 4
    result = cleanse(data, np.ones(len(data), bool), np.ones(len(data), bool))
    assert result.removed["outlier"] >= 1
    assert not result.retained[1_000]


def test_a_cycle_unlike_any_operating_state_is_removed_as_multivariate() -> None:
    data = frame()
    # Every sensor within its own normal spread, but the combination never happens:
    # high flow with the temperature and vibration of low load.
    data.iloc[2_000] = [80.0, 55.0, 0.6]
    z = robust_z(data)
    assert np.abs(z[2_000]).max() <= 4
    result = cleanse(data, np.ones(len(data), bool), np.ones(len(data), bool))
    assert not result.retained[2_000]


def test_periods_are_start_inclusive_and_end_exclusive() -> None:
    index = pd.date_range(T0, periods=5, freq="min", tz="UTC")
    period = Period(T0 + timedelta(minutes=1), T0 + timedelta(minutes=3))
    assert in_periods(index, [period]).tolist() == [False, True, True, False, False]


def test_nothing_left_gives_no_clusters_and_no_error() -> None:
    data = frame(100)
    result = cleanse(data, np.zeros(100, bool), np.ones(100, bool))
    assert result.kept == 0
    assert result.clusters == ()
    assert result.removed["outlier"] == result.removed["multivariate"] == 0


def test_same_seed_same_result() -> None:
    data = frame()
    ones = np.ones(len(data), bool)
    first, second = cleanse(data, ones, ones, seed=5), cleanse(data, ones, ones, seed=5)
    assert (first.retained == second.retained).all()
    assert first.clusters == second.clusters
