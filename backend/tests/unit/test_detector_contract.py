"""The detector contract suite and the placeholder detector (ARC-001 §8.1, UCS §6.3.3).

The placeholder must pass the suite, and each broken detector below must be caught,
which proves the suite would refuse a faulty plug-in.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from pmp.modelling import Detector, DetectorError, MedianDetector, check_detector
from pmp.modelling.algorithms.checks import sample_data


def test_the_placeholder_passes_the_contract() -> None:
    report = check_detector(MedianDetector)
    assert report.passed, report.failures
    assert (report.name, report.version) == ("median", "0.1.0")
    assert isinstance(MedianDetector(), Detector)


def test_the_placeholder_predicts_training_medians_for_every_sensor() -> None:
    train, test = sample_data()
    detector = MedianDetector()
    detector.fit(train, {"seed": 1})
    gappy = test.copy()
    gappy["s2"] = np.nan  # excluded sensor: still predicted
    predicted = detector.predict(gappy)
    for column in train.columns:
        assert (predicted[column] == train[column].median()).all()


def test_the_placeholder_ignores_missing_training_values() -> None:
    train, _ = sample_data()
    train.iloc[:50, 0] = np.nan
    detector = MedianDetector()
    detector.fit(train, {})
    assert detector.predict(train.iloc[:1]).iloc[0, 0] == train["s1"].median()


def test_a_sensor_without_any_training_value_is_refused() -> None:
    train, _ = sample_data()
    train["s4"] = np.nan
    with pytest.raises(DetectorError, match="No training values for: s4"):
        MedianDetector().fit(train, {})


def test_duplicate_columns_are_refused() -> None:
    train, _ = sample_data()
    with pytest.raises(DetectorError, match="duplicate"):
        MedianDetector().fit(train[["s1", "s1"]], {})


def test_the_saved_model_is_plain_json(tmp_path: Path) -> None:
    train, _ = sample_data()
    detector = MedianDetector()
    detector.fit(train, {})
    detector.save(tmp_path)
    payload = json.loads((tmp_path / "median.json").read_text())
    assert payload["columns"] == list(train.columns)
    assert payload["medians"][0] == pytest.approx(train["s1"].median(), abs=0)


def test_saving_an_unfitted_model_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DetectorError, match="not been fitted"):
        MedianDetector().save(tmp_path)


@pytest.mark.parametrize(
    "content", [None, "not json", '{"name": "aakr", "columns": [], "medians": []}']
)
def test_a_missing_or_foreign_file_does_not_load(tmp_path: Path, content: str | None) -> None:
    if content is not None:
        (tmp_path / "median.json").write_text(content)
    with pytest.raises(DetectorError):
        MedianDetector.load(tmp_path)


# ------------------------------------------------------------------ broken detectors


class _Broken(MedianDetector):
    name = "broken"


class WrongShape(_Broken):
    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        return super().predict(X).iloc[:, :-1]


class LeavesGaps(_Broken):
    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        return super().predict(X).where(X.notna())  # NaN where the input is NaN


class Random(_Broken):
    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        noise = np.random.default_rng().normal(size=(len(X), len(X.columns)))
        return super().predict(X) + noise


class Forgetful(_Broken):
    @classmethod
    def load(cls, directory: Path) -> MedianDetector:
        detector = super().load(directory)
        assert detector._medians is not None
        detector._medians = detector._medians + 1.0
        return detector


class AcceptsAnything(_Broken):
    def fit(self, X: pd.DataFrame, config: Mapping[str, Any]) -> None:
        if X.empty:
            self._columns, self._medians = [], np.empty(0)
            return
        super().fit(X, config)


class Mutates(_Broken):
    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        result = super().predict(X)
        X.iloc[0, 0] = 99.0
        return result


class CannotFit(_Broken):
    def fit(self, X: pd.DataFrame, config: Mapping[str, Any]) -> None:
        raise RuntimeError("boom")


class Nameless(MedianDetector):
    name = ""
    version = ""


@pytest.mark.parametrize(
    ("cls", "expected"),
    [
        (WrongShape, "output shape: columns or their order changed"),
        (LeavesGaps, "missing values: predictions contain missing values"),
        (Random, "determinism"),
        (Forgetful, "save and load: reloaded model predicts differently"),
        (AcceptsAnything, "empty training data: accepted fit on empty data"),
        (Mutates, "output shape: predict changed its input"),
        (CannotFit, "fit: raised RuntimeError: boom"),
        (Nameless, "has no name"),
    ],
)
def test_the_suite_catches_broken_detectors(cls: type[Any], expected: str) -> None:
    report = check_detector(cls)
    assert not report.passed
    assert any(expected in f for f in report.failures), report.failures
