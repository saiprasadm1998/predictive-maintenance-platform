"""Auto-associative kernel regression (UCS §6.3.1, FR-MOD-04, ARC §8.1 and §8.3).

AAKR predicts what each sensor should read, given the others, as a kernel-weighted average
of remembered normal states (the memory matrix):

- memory: k-means centroids of the scaled training data, k from 20 to 200 chosen by
  silhouette score, plus for every sensor the training rows at its minimum and maximum,
  so the edges of normal operation are kept. 200 to 1,000 vectors: below 200 a seeded
  sample of training rows is added; above 1,000 the centroids are cut. Everything random
  uses config["seed"], so the same data and seed give the same model (ARC §8.3).
- prediction: Gaussian kernel on the distance over the sensors usable in that cycle
  (NaN = unusable), so an excluded sensor is still predicted, from the others.
- calibration on the validation period (optional contract step): the bandwidth is the one
  with the lowest validation error among 0.1 to 2.0 x the median nearest-neighbour distance
  of the memory; the out-of-envelope limit is the 99.5th percentile of the validation
  cycles' minimum distance to the memory. Without calibration both come from the memory
  itself (1.0 x the median distance; the 99.5th percentile of training distances).

Distances are root-mean-square over the usable sensors, so a cycle with fewer usable
sensors is judged on the same scale as a complete one.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
from sklearn.cluster import KMeans, MiniBatchKMeans
from sklearn.metrics import silhouette_score

from pmp.modelling.algorithms.contract import DetectorError

Array = npt.NDArray[np.float64]

K_MIN, K_MAX = 20, 200
MEMORY_MIN, MEMORY_MAX = 200, 1_000
K_CANDIDATES = (20, 30, 50, 75, 100, 150, 200)
SILHOUETTE_SAMPLE = 2_000
MINIBATCH_ABOVE = 20_000  # rows; beyond this k-means runs in mini-batches
BANDWIDTH_FACTORS = tuple(round(f, 2) for f in np.linspace(0.1, 2.0, 20))
ENVELOPE_PERCENTILE = 99.5
_META, _MEMORY = "aakr.json", "memory.npy"


def _rms_distances(query: Array, memory: Array) -> Array:
    """Root-mean-square distance from each query row to each memory row, over the query's
    usable (non-NaN) columns; rows with nothing usable get infinite distance."""
    out = np.full((len(query), len(memory)), np.inf)
    usable = ~np.isnan(query)
    patterns, inverse = np.unique(usable, axis=0, return_inverse=True)
    for p, pattern in enumerate(patterns):
        rows = np.flatnonzero(inverse.ravel() == p)
        if not pattern.any():
            continue
        q, m = query[np.ix_(rows, pattern)], memory[:, pattern]
        squared = (q**2).sum(1)[:, None] - 2 * q @ m.T + (m**2).sum(1)[None, :]
        out[rows] = np.sqrt(np.maximum(squared, 0.0) / pattern.sum())
    return out


class AakrDetector:
    name = "aakr"
    version = "1.0.0"

    def __init__(self) -> None:
        self._columns: list[str] | None = None
        self._memory: Array | None = None
        self._bandwidth = 0.0
        self._envelope = np.inf
        self._k = 0
        self._calibrated = False

    # ------------------------------------------------------------------ contract

    def fit(self, X: pd.DataFrame, config: Mapping[str, Any]) -> None:
        if X.empty or len(X.columns) == 0:
            raise DetectorError("Training data is empty")
        columns = [str(c) for c in X.columns]
        if len(set(columns)) != len(columns):
            raise DetectorError("Training data has duplicate sensor columns")
        values = X.to_numpy(dtype=np.float64)
        medians = np.nanmedian(values, axis=0) if len(values) else np.array([])
        missing = [c for c, m in zip(columns, medians, strict=True) if np.isnan(m)]
        if missing:
            raise DetectorError(f"No training values for: {', '.join(missing)}")
        # Clustering needs complete rows: a gap takes the sensor's (scaled) median.
        complete = np.where(np.isnan(values), medians, values)
        seed = int(config.get("seed", 0))
        rng = np.random.default_rng(seed)

        centroids, self._k = self._centroids(complete, seed)
        edges = np.vstack(
            [complete[np.argmin(complete, axis=0)], complete[np.argmax(complete, axis=0)]]
        )
        memory = np.unique(np.vstack([edges, centroids]), axis=0)
        if len(memory) < MEMORY_MIN:  # a seeded sample of training rows not yet remembered
            unique_rows = np.unique(complete, axis=0)
            known = {row.tobytes() for row in memory}
            fresh = [
                r
                for r in unique_rows[rng.permutation(len(unique_rows))]
                if r.tobytes() not in known
            ]
            if fresh:
                memory = np.vstack([memory, np.asarray(fresh[: MEMORY_MIN - len(memory)])])
        if len(memory) > MEMORY_MAX:  # edges first, then as many centroids as fit
            memory = np.unique(np.vstack([edges, centroids[: MEMORY_MAX - len(edges)]]), axis=0)

        self._columns, self._memory = columns, memory
        nearest = self._nearest_neighbour(memory)
        self._bandwidth = float(np.median(nearest)) or 1.0
        training_min = _rms_distances(complete, memory).min(axis=1)
        self._envelope = float(np.percentile(training_min, ENVELOPE_PERCENTILE))
        self._calibrated = False

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        memory = self._fitted_memory(X)
        query = X.to_numpy(dtype=np.float64)
        weights = self._weights(_rms_distances(query, memory), self._bandwidth)
        return pd.DataFrame(weights @ memory, index=X.index, columns=self._columns)

    def save(self, directory: Path) -> None:
        if self._columns is None or self._memory is None:
            raise DetectorError("The detector has not been fitted")
        directory.mkdir(parents=True, exist_ok=True)
        np.save(directory / _MEMORY, self._memory, allow_pickle=False)
        meta = {
            "name": self.name,
            "version": self.version,
            "columns": self._columns,
            "bandwidth": self._bandwidth,
            "envelope": self._envelope,
            "k": self._k,
            "calibrated": self._calibrated,
        }
        (directory / _META).write_text(json.dumps(meta, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> AakrDetector:
        try:
            meta = json.loads((directory / _META).read_text(encoding="utf-8"))
            memory = np.load(directory / _MEMORY, allow_pickle=False).astype(np.float64)
            columns = [str(c) for c in meta["columns"]]
            bandwidth, envelope = float(meta["bandwidth"]), float(meta["envelope"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise DetectorError(f"Cannot read an AAKR model from {directory}: {error}") from None
        if meta.get("name") != cls.name or memory.ndim != 2 or memory.shape[1] != len(columns):
            raise DetectorError(f"{directory} does not hold a valid AAKR model")
        detector = cls()
        detector._columns, detector._memory = columns, memory
        detector._bandwidth, detector._envelope = bandwidth, envelope
        detector._k, detector._calibrated = int(meta.get("k", 0)), bool(meta.get("calibrated"))
        return detector

    # ------------------------------------------------------------------ optional steps

    def calibrate(self, X: pd.DataFrame) -> None:
        """Tune the bandwidth and the envelope limit on the validation period (scaled)."""
        memory = self._fitted_memory(X)
        query = X.to_numpy(dtype=np.float64)
        distances = _rms_distances(query, memory)
        reachable = np.isfinite(distances).any(axis=1)
        if not reachable.any():
            raise DetectorError("The validation period has no usable cycle")
        query, distances = query[reachable], distances[reachable]
        base = float(np.median(self._nearest_neighbour(memory))) or 1.0
        best: tuple[float, float] | None = None
        for factor in BANDWIDTH_FACTORS:
            bandwidth = factor * base
            predicted = self._weights(distances, bandwidth) @ memory
            error = float(np.nanmean((query - predicted) ** 2))
            if best is None or error < best[0]:
                best = (error, bandwidth)
        assert best is not None
        self._bandwidth = best[1]
        self._envelope = float(np.percentile(distances.min(axis=1), ENVELOPE_PERCENTILE))
        self._calibrated = True

    def min_distance(self, X: pd.DataFrame) -> pd.Series:
        """Each cycle's distance to the nearest remembered state (inf: nothing usable)."""
        memory = self._fitted_memory(X)
        distances = _rms_distances(X.to_numpy(dtype=np.float64), memory)
        return pd.Series(distances.min(axis=1), index=X.index, name="min_distance")

    def out_of_envelope(self, X: pd.DataFrame) -> pd.Series:
        """True where a cycle is further from every remembered state than normal operation
        ever was: the prediction there is an extrapolation and less trustworthy."""
        return (self.min_distance(X) > self._envelope).rename("out_of_envelope")

    @property
    def summary(self) -> dict[str, Any]:
        """What was learnt, for the training report."""
        return {
            "memory_vectors": 0 if self._memory is None else len(self._memory),
            "clusters": self._k,
            "bandwidth": self._bandwidth,
            "envelope": self._envelope,
            "calibrated": self._calibrated,
        }

    # ------------------------------------------------------------------ internals

    def _fitted_memory(self, X: pd.DataFrame) -> Array:
        if self._columns is None or self._memory is None:
            raise DetectorError("The detector has not been fitted")
        if [str(c) for c in X.columns] != self._columns:
            raise DetectorError("Input columns differ from the training columns")
        return self._memory

    @staticmethod
    def _centroids(values: Array, seed: int) -> tuple[Array, int]:
        """k-means centroids with k (20 to 200) chosen by silhouette score on a sample."""
        distinct = len(np.unique(values, axis=0))
        candidates = [k for k in K_CANDIDATES if k < distinct] or [min(K_MIN, distinct)]
        rng = np.random.default_rng(seed)
        sample = values[rng.permutation(len(values))[:SILHOUETTE_SAMPLE]]
        best: tuple[float, Array, int] | None = None
        for k in candidates:
            model = (
                MiniBatchKMeans(n_clusters=k, random_state=seed, n_init=3, batch_size=4_096)
                if len(values) > MINIBATCH_ABOVE
                else KMeans(n_clusters=k, random_state=seed, n_init=3)
            )
            model.fit(values)
            labels = model.predict(sample)
            score = (
                float(silhouette_score(sample, labels, random_state=seed))
                if 1 < len(set(labels.tolist())) < len(sample)
                else -1.0
            )
            if best is None or score > best[0]:
                best = (score, np.asarray(model.cluster_centers_, dtype=np.float64), k)
        assert best is not None
        return best[1], best[2]

    @staticmethod
    def _nearest_neighbour(memory: Array) -> Array:
        distances = _rms_distances(memory, memory)
        np.fill_diagonal(distances, np.inf)
        nearest = distances.min(axis=1)
        return nearest[np.isfinite(nearest)] if len(memory) > 1 else np.array([1.0])

    @staticmethod
    def _weights(distances: Array, bandwidth: float) -> Array:
        """Gaussian kernel weights per row, normalised; a row with nothing usable (all
        distances infinite) or far from everything falls back to the nearest states."""
        finite = np.isfinite(distances)
        safe = np.where(finite, distances, 0.0)
        # Subtract each row's smallest distance before exponentiating: same weights after
        # normalisation, no underflow to zero for cycles far from the memory.
        shift = np.where(finite.any(axis=1), np.where(finite, safe, np.inf).min(axis=1), 0.0)
        kernel = np.exp(-((safe**2 - shift[:, None] ** 2) / (2 * bandwidth**2)))
        kernel = np.where(finite, kernel, 0.0)
        empty = kernel.sum(axis=1) == 0
        kernel[empty] = 1.0  # nothing usable: the average remembered state
        return kernel / kernel.sum(axis=1, keepdims=True)
