"""Baseline training logic (UCS §6.2, §6.4; UC-05 6a): assembly, minimum data, scaling,
validation playback and the artefact folder."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pmp.modelling import MedianDetector, parse_expression
from pmp.modelling.artefacts import folder_digest, write_artefact
from pmp.modelling.training import (
    MIN_VECTORS,
    Assembled,
    SensorInfo,
    TrainingError,
    assemble,
    check_minimum_data,
    train,
)

STEP = 60 * 1_000_000_000
SENSORS = [
    SensorInfo("A", True, 100.0),
    SensorInfo("B", False, 100.0),
    SensorInfo("C", False, 200.0),
]


def grid(n: int, start: int = 0) -> np.ndarray:
    return np.arange(start, start + n, dtype=np.int64) * STEP


def data(
    n: int, seed: int = 1, start: int = 0
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    values = {
        "A": 50 + 10 * np.sin(t / 50) + rng.normal(0, 1, n),
        "B": 20 + 5 * np.sin(t / 50) + rng.normal(0, 0.5, n),
        "C": np.full(n, 80.0),  # did not move: its range is floored
        "MOTOR": np.where(t % 100 < 10, 0.0, 150.0),  # stopped 10 % of the time
    }
    usable = {k: np.ones(n, dtype=bool) for k in values}
    return values, usable


def test_assembly_applies_usability_mode_and_coverage() -> None:
    values, usable = data(10)
    values["MOTOR"] = np.array([0.0] + [150.0] * 9)  # stopped in the first cycle
    usable["A"][2] = False  # required sensor unusable: not covered
    usable["B"][3] = False
    usable["C"][3] = False  # 1 of 3 usable: below 70 %
    usable["MOTOR"][4] = False  # filter tag unusable: not in mode
    built = assemble(grid(10), SENSORS, values, usable, [parse_expression("MOTOR > 120")])
    assert list(built.frame.columns) == ["A", "B", "C"]
    assert np.isnan(built.frame["A"].iloc[2])
    assert built.in_mode.tolist() == [False] + [True] * 3 + [False] + [True] * 5
    assert built.covered.tolist() == [True, True, False, False] + [True] * 6
    assert built.retained.tolist() == [False, True, False, False, False] + [True] * 5
    assert isinstance(built.frame.index, pd.DatetimeIndex)
    assert str(built.frame.index.tz) == "UTC"


def test_minimum_data_messages_follow_the_design_spec() -> None:
    values, usable = data(MIN_VECTORS - 1)
    few = assemble(grid(MIN_VECTORS - 1), SENSORS, values, usable, [])
    with pytest.raises(TrainingError, match="only 1,999 clean samples; at least 2,000"):
        check_minimum_data(few)

    values, usable = data(5000)
    filtered = assemble(grid(5000), SENSORS, values, usable, [parse_expression("MOTOR > 1e9")])
    with pytest.raises(TrainingError, match="only 0 clean samples"):
        check_minimum_data(filtered)
    half = Assembled(filtered.frame, np.arange(5000) < 2400, filtered.covered)
    with pytest.raises(TrainingError, match="only 48% of the selected period"):
        check_minimum_data(half)


def _sets(n_train: int = 4000, n_valid: int = 1000) -> tuple[Assembled, Assembled]:
    mode = [parse_expression("MOTOR > 120")]
    tv, tu = data(n_train)
    vv, vu = data(n_valid, seed=2)
    return (
        assemble(grid(n_train), SENSORS, tv, tu, mode),
        assemble(grid(n_valid, n_train), SENSORS, vv, vu, mode),
    )


def test_training_statistics_follow_ucs_6_2() -> None:
    training, validation = _sets()
    result = train(MedianDetector, {"seed": 1}, SENSORS, training, validation)
    fit_a = training.frame["A"][training.retained].to_numpy()
    a = result.sensors["A"]
    assert a.median == pytest.approx(np.median(fit_a))
    assert (a.p1, a.p99) == pytest.approx(tuple(np.percentile(fit_a, [1, 99])))
    assert a.scale.range == pytest.approx(a.p99 - a.p1)

    # the placeholder predicts the median, so residuals are actual - median
    valid_a = validation.frame["A"][validation.retained].to_numpy()
    residuals = valid_a - a.median
    mad = np.median(np.abs(residuals - np.median(residuals)))
    assert a.raw_sigma == pytest.approx(1.4826 * mad)
    assert a.scale.sigma == pytest.approx(1.4826 * mad)
    assert a.bias == pytest.approx(residuals.mean())
    assert a.validation_count == len(residuals)

    c = result.sensors["C"]  # constant: both floors apply
    assert (c.scale.range, c.scale.range_floored) == (2.0, True)  # 1 % of 200
    assert (c.scale.sigma, c.scale.sigma_floored) == (0.02, True)

    assert result.training_cycles == 4000
    assert result.training_retained == 3600  # motor stopped 10 % of the time
    assert result.validation_retained == 900
    assert result.scaling()["sensor_order"] == ["A", "B", "C"]
    assert set(result.validation()["sensors"]) == {"A", "B", "C"}


def test_training_is_reproducible() -> None:
    training, validation = _sets()
    first = train(MedianDetector, {"seed": 7}, SENSORS, training, validation)
    second = train(MedianDetector, {"seed": 7}, SENSORS, training, validation)
    assert first.scaling() == second.scaling()
    assert first.validation() == second.validation()


def test_a_sensor_without_usable_training_data_blocks_training() -> None:
    training, validation = _sets()
    frame = training.frame.copy()
    frame["B"] = np.nan
    gappy = Assembled(frame, training.in_mode, training.covered)
    with pytest.raises(TrainingError, match="B has no usable value"):
        train(MedianDetector, {}, SENSORS, gappy, validation)


def test_an_empty_validation_period_blocks_training() -> None:
    training, validation = _sets()
    nothing = Assembled(
        validation.frame, np.zeros(validation.cycles, dtype=bool), validation.covered
    )
    with pytest.raises(TrainingError, match="Validation blocked"):
        train(MedianDetector, {}, SENSORS, training, nothing)


def test_the_artefact_folder_is_complete_and_hashed(tmp_path: Path) -> None:
    training, validation = _sets()
    result = train(MedianDetector, {"seed": 1}, SENSORS, training, validation)
    target = tmp_path / "models" / "1" / "1"
    sha = write_artefact(
        target,
        result.detector,
        scaling=result.scaling(),
        manifest={"model_id": 1},
        validation=result.validation(),
    )
    names = sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file())
    assert names == ["algorithm/median.json", "manifest.json", "scaling.json", "validation.json"]
    assert sha == folder_digest(target)
    assert len(sha) == 64
    assert json.loads((target / "scaling.json").read_text())["sensor_order"] == ["A", "B", "C"]

    # writing again (a retried job) replaces the folder and gives the same digest
    assert (
        write_artefact(
            target,
            result.detector,
            scaling=result.scaling(),
            manifest={"model_id": 1},
            validation=result.validation(),
        )
        == sha
    )
    assert not target.with_name("1.tmp").exists()

    (target / "scaling.json").write_text("{}")  # tampering changes the digest
    assert folder_digest(target) != sha
