"""The placeholder detector: predicts each sensor as its training median.

It stands in for AAKR (Phase 7) so the whole pipeline and every screen can be built and
demonstrated (implementation plan, assumptions). It ignores the current inputs, so its
predictions never move: scores made with it are for demonstration only and do not
indicate real anomalies. It still predicts every sensor, including excluded ones, as
the contract requires.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from pmp.modelling.algorithms.contract import DetectorError

_FILE = "median.json"


class MedianDetector:
    name = "median"
    version = "0.1.0"

    def __init__(self) -> None:
        self._columns: list[str] | None = None
        self._medians: npt.NDArray[np.float64] | None = None

    def fit(self, X: pd.DataFrame, config: Mapping[str, Any]) -> None:
        if X.empty or len(X.columns) == 0:
            raise DetectorError("Training data is empty")
        columns = [str(c) for c in X.columns]
        if len(set(columns)) != len(columns):
            raise DetectorError("Training data has duplicate sensor columns")
        medians = X.median(skipna=True).to_numpy(dtype=np.float64)
        missing = [c for c, m in zip(columns, medians, strict=True) if np.isnan(m)]
        if missing:
            raise DetectorError(f"No training values for: {', '.join(missing)}")
        self._columns, self._medians = columns, medians

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        if self._columns is None or self._medians is None:
            raise DetectorError("The detector has not been fitted")
        if [str(c) for c in X.columns] != self._columns:
            raise DetectorError("Input columns differ from the training columns")
        values = np.tile(self._medians, (len(X), 1))
        return pd.DataFrame(values, index=X.index, columns=self._columns)

    def save(self, directory: Path) -> None:
        if self._columns is None or self._medians is None:
            raise DetectorError("The detector has not been fitted")
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "name": self.name,
            "version": self.version,
            "columns": self._columns,
            "medians": [float(m) for m in self._medians],
        }
        (directory / _FILE).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> MedianDetector:
        try:
            payload = json.loads((directory / _FILE).read_text(encoding="utf-8"))
            columns = [str(c) for c in payload["columns"]]
            medians = np.asarray(payload["medians"], dtype=np.float64)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise DetectorError(f"Cannot read a median model from {directory}: {error}") from None
        if payload.get("name") != cls.name or len(columns) != len(medians):
            raise DetectorError(f"{directory} does not hold a valid median model")
        detector = cls()
        detector._columns, detector._medians = columns, medians
        return detector
