"""The detector contract suite (ARC-001 §8.1): run before a detector is enabled.

ARC requires plug-ins to pass "fit/predict shape, NaN handling, save/load round trip,
determinism with a fixed seed" before they are used, so the suite is part of the
product, not only of the tests: the registry runs it on every detector it finds.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from pmp.modelling.algorithms.contract import DetectorError

SEED = 7
_ROWS, _SENSORS = 240, 5


@dataclass(frozen=True)
class ContractReport:
    name: str
    version: str
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def sample_data(seed: int = SEED) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Scaled training and test frames: five correlated sensors, one-minute rows."""
    rng = np.random.default_rng(seed)
    t = np.arange(2 * _ROWS)
    load = np.sin(t / 25.0)
    columns = [f"s{i}" for i in range(1, _SENSORS + 1)]
    values = np.column_stack(
        [(i + 1) * 0.2 * load + rng.normal(0, 0.05, len(t)) for i in range(_SENSORS)]
    )
    index = pd.date_range("2026-01-01", periods=len(t), freq="min", tz="UTC")
    frame = pd.DataFrame(values, index=index, columns=columns)
    return frame.iloc[:_ROWS], frame.iloc[_ROWS:]


def check_detector(cls: Any, seed: int = SEED) -> ContractReport:
    """Run every contract check on a detector class; failures are listed, not raised."""
    name = getattr(cls, "name", None)
    version = getattr(cls, "version", None)
    failures: list[str] = []
    if not isinstance(name, str) or not name:
        failures.append("has no name")
    if not isinstance(version, str) or not version:
        failures.append("has no version")
    report = ContractReport(str(name or "?"), str(version or "?"), failures)

    train, test = sample_data(seed)
    config = {"seed": seed}

    def check(label: str, step: Callable[[], None]) -> None:
        try:
            step()
        except AssertionError as error:
            failures.append(f"{label}: {error}")
        except Exception as error:
            failures.append(f"{label}: raised {type(error).__name__}: {error}")

    fitted: list[Any] = []

    def fit() -> None:
        detector = cls()
        detector.fit(train.copy(), config)
        fitted.append(detector)

    check("fit", fit)
    if not fitted:
        return report
    detector = fitted[0]

    def output_shape() -> None:
        before = test.copy()
        _assert_complete(detector.predict(test), test)
        assert test.equals(before), "predict changed its input"

    def missing_values() -> None:
        gappy = test.copy()
        gappy["s2"] = np.nan  # an excluded sensor
        gappy.iloc[10] = np.nan  # a cycle with nothing usable
        _assert_complete(detector.predict(gappy), gappy)

    def round_trip() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            detector.save(Path(tmp) / "model")
            loaded = cls.load(Path(tmp) / "model")
        expected = detector.predict(test)
        assert loaded.predict(test).equals(expected), "reloaded model predicts differently"

    def deterministic() -> None:
        again = cls()
        again.fit(train.copy(), config)
        assert again.predict(test).equals(detector.predict(test)), (
            "same data and seed gave different predictions"
        )

    def refuses_empty_training() -> None:
        _assert_refused(lambda: cls().fit(train.iloc[:0], config), "fit on empty data")

    def refuses_wrong_columns() -> None:
        _assert_refused(lambda: detector.predict(test[test.columns[::-1]]), "reordered columns")
        _assert_refused(lambda: detector.predict(test.drop(columns="s3")), "a missing column")

    def refuses_unfitted() -> None:
        _assert_refused(lambda: cls().predict(test), "predict before fit")

    check("output shape", output_shape)
    check("missing values", missing_values)
    check("save and load", round_trip)
    check("determinism", deterministic)
    check("empty training data", refuses_empty_training)
    check("wrong columns", refuses_wrong_columns)
    check("not fitted", refuses_unfitted)
    return report


def _assert_complete(result: Any, query: pd.DataFrame) -> None:
    assert isinstance(result, pd.DataFrame), "predict must return a DataFrame"
    assert list(result.columns) == list(query.columns), "columns or their order changed"
    assert result.index.equals(query.index), "rows changed"
    numeric = result.apply(pd.to_numeric, errors="coerce")
    assert not numeric.isna().to_numpy().any(), "predictions contain missing values"


def _assert_refused(action: Callable[[], object], what: str) -> None:
    try:
        action()
    except (DetectorError, ValueError):
        return
    raise AssertionError(f"accepted {what}")
