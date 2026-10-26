"""AAKR (plan 7.1): the contract, accuracy on seeded healthy data, a rising Deviation Index
on seeded drift, calibration and the out-of-envelope flag, and per-model latency."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pmp.modelling.algorithms.aakr import MEMORY_MAX, MEMORY_MIN, AakrDetector
from pmp.modelling.algorithms.checks import check_detector
from pmp.modelling.algorithms.contract import DetectorError

SEED = 11
SENSORS = [f"s{i}" for i in range(1, 7)]


def plant(rows: int, seed: int, start: str = "2026-01-01") -> pd.DataFrame:
    """Six scaled sensors driven by two shared factors (load and ambient), plus noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(rows)
    load = np.sin(t / 90.0) + 0.3 * np.sin(t / 17.0)
    ambient = np.cos(t / 400.0)
    weights = [(0.9, 0.1), (0.7, 0.3), (0.5, -0.4), (0.3, 0.6), (-0.6, 0.2), (0.4, 0.4)]
    values = np.column_stack(
        [a * load + b * ambient + rng.normal(0, 0.02, rows) for a, b in weights]
    )
    index = pd.date_range(start, periods=rows, freq="min", tz="UTC")
    return pd.DataFrame(values * 0.3, index=index, columns=SENSORS)


def di(actual: pd.DataFrame, predicted: pd.DataFrame) -> pd.Series:
    """UCS §6.2 on scaled data: 100 x the root-mean-square residual over the sensors."""
    mean_square: pd.Series = ((actual - predicted) ** 2).mean(axis=1)
    return mean_square.pow(0.5) * 100


@pytest.fixture(scope="module")
def trained() -> tuple[AakrDetector, pd.DataFrame]:
    data = plant(8_000, SEED)
    detector = AakrDetector()
    detector.fit(data.iloc[:6_000], {"seed": SEED})
    validation = data.iloc[6_000:]
    detector.calibrate(validation)
    return detector, validation


def test_passes_the_contract_suite() -> None:
    assert check_detector(AakrDetector).failures == []


def test_memory_matrix_size_and_calibration(trained: tuple[AakrDetector, pd.DataFrame]) -> None:
    detector, _ = trained
    summary = detector.summary
    assert MEMORY_MIN <= summary["memory_vectors"] <= MEMORY_MAX
    assert 20 <= summary["clusters"] <= 200
    assert summary["calibrated"]
    assert summary["bandwidth"] > 0


def test_predicts_healthy_data_closely_including_an_excluded_sensor(
    trained: tuple[AakrDetector, pd.DataFrame],
) -> None:
    detector, _ = trained
    healthy = plant(9_000, SEED).iloc[8_000:]  # later, unseen healthy operation
    predicted = detector.predict(healthy)
    rms = np.sqrt(((healthy - predicted) ** 2).mean())
    assert (rms < 0.03).all(), rms  # noise is 0.006 scaled; the signal spans about 0.6

    excluded = healthy.copy()
    excluded["s3"] = np.nan  # s3 unusable: still predicted, from the others
    estimate = detector.predict(excluded)["s3"]
    assert np.sqrt(((healthy["s3"] - estimate) ** 2).mean()) < 0.04
    assert di(healthy, predicted).median() < 3


def test_seeded_drift_raises_the_deviation_index(
    trained: tuple[AakrDetector, pd.DataFrame],
) -> None:
    detector, _ = trained
    drifting = plant(9_000, SEED).iloc[8_000:].copy()
    ramp = np.linspace(0, 0.25, len(drifting))  # s2 drifts away from its relationships
    drifting["s2"] += ramp
    scores = di(drifting, detector.predict(drifting))
    by_quarter = [float(np.median(q)) for q in np.array_split(scores.to_numpy(), 4)]
    assert by_quarter == sorted(by_quarter), by_quarter
    assert by_quarter[-1] > 3 * by_quarter[0]
    # The drifting sensor carries the deviation, not its healthy neighbours.
    residual = (drifting - detector.predict(drifting)).iloc[-200:].abs().mean()
    assert residual.idxmax() == "s2"


def test_flags_cycles_outside_the_envelope(trained: tuple[AakrDetector, pd.DataFrame]) -> None:
    detector, validation = trained
    assert detector.out_of_envelope(validation).mean() <= 0.01  # 99.5th percentile
    far = validation.iloc[:10] + 2.0  # nothing like normal operation
    assert detector.out_of_envelope(far).all()
    nothing = validation.iloc[:1].copy()
    nothing.iloc[0] = np.nan
    assert not np.isfinite(detector.min_distance(nothing).iloc[0])


def test_same_seed_same_model_and_a_round_trip(
    trained: tuple[AakrDetector, pd.DataFrame], tmp_path: Path
) -> None:
    detector, validation = trained
    detector.save(tmp_path / "m")
    loaded = AakrDetector.load(tmp_path / "m")
    assert loaded.summary == detector.summary
    pd.testing.assert_frame_equal(loaded.predict(validation), detector.predict(validation))
    (tmp_path / "m" / "aakr.json").write_text("{}", encoding="utf-8")
    with pytest.raises(DetectorError):
        AakrDetector.load(tmp_path / "m")


def test_calibration_needs_a_usable_cycle(trained: tuple[AakrDetector, pd.DataFrame]) -> None:
    detector, validation = trained
    empty = validation.iloc[:5].copy()
    empty.iloc[:, :] = np.nan
    with pytest.raises(DetectorError, match="no usable cycle"):
        detector.calibrate(empty)  # refused before anything is changed


def test_one_cycle_scores_well_within_the_cycle_budget(
    trained: tuple[AakrDetector, pd.DataFrame],
) -> None:
    """NFR-PERF: a model's prediction takes a small share of the one-minute cycle."""
    detector, validation = trained
    one = validation.iloc[:1]
    detector.predict(one)
    started = time.perf_counter()
    for _ in range(50):
        detector.predict(one)
    assert (time.perf_counter() - started) / 50 < 0.05  # seconds per model per cycle
