"""The algorithm plug-in contract (ARC-001 §8.1, UCS §6.3.3, ADR-09).

Every normal-behaviour model, built-in or plug-in, implements this interface. PMP
supplies cleansed, scaled data and consumes predictions; data quality, outputs,
alerting, diagnostics, forecasting and cases do not depend on the algorithm.

A detector class must be constructible without arguments. Columns are the model's
sensors in a fixed order. A plug-in registers itself in its package's pyproject.toml:

    [project.entry-points."pmp.algorithms"]
    my_detector = "my_pkg.detector:MyDetector"

and is enabled only if it passes the contract suite (pmp.modelling.algorithms.checks).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pandas as pd


class DetectorError(Exception):
    """A detector was used incorrectly or failed: wrong columns, not fitted, bad data."""


@runtime_checkable
class Detector(Protocol):
    """Normal-behaviour model. Columns are model sensors in a fixed order."""

    name: str  # registry key, e.g. "aakr"
    version: str  # semantic version of the implementation

    def fit(self, X: pd.DataFrame, config: Mapping[str, Any]) -> None:
        """X: cleansed, scaled training data (rows = time, columns = sensors).

        config holds algorithm parameters, including "seed" for anything random
        (ARC §8.3). Raises DetectorError for unusable data, such as an empty frame.
        """
        ...

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        """X may contain NaN for unusable sensors; return predictions for ALL columns.

        The result has X's index and the training columns in training order, with no
        missing values. Raises DetectorError if not fitted or the columns differ.
        """
        ...

    def save(self, directory: Path) -> None:
        """Write the fitted model's files into `directory` (created if missing)."""
        ...

    @classmethod
    def load(cls, directory: Path) -> Detector:
        """Read a model written by save()."""
        ...
