"""Training-data cleansing (UC-05 steps 3 to 6, FR-MOD-02, -03, UCS §6.4, plan 7.2).

The rules run in this order on the training periods' cycle grid; each sees only the
cycles the rules before it kept, so the effect of every rule can be shown on its own
(SCR-06 step 3):

1. mode: outside the operating-mode filters
2. quality: the data-quality rules and the coverage rule (70 % of sensors usable, every
   required sensor usable)
3. excluded: inside a period the engineer excluded on the trend
4. outlier: any sensor with |robust z| > 4 (median and MAD of the cycles kept so far);
   the whole cycle goes (decision 7.2), so the model remembers only clean states
5. multivariate: further from the nearest operating cluster's centre than 99.9 % of the
   cycles kept so far (k-means on robust-scaled data, 2 to 8 clusters by silhouette score)

The clusters are reported with the cycles retained in each, so an operating state with
little data shows up before training. Validation playback applies rules 1 and 2 only:
it is scored as runtime will score it.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from pmp.modelling.definitions import Period

OUTLIER_Z = 4.0
MULTIVARIATE_PERCENTILE = 99.9
CLUSTER_RANGE = range(2, 9)
MIN_FOR_CLUSTERS = 50  # fewer kept cycles: no clustering (the minimum-data rule blocks)
SILHOUETTE_SAMPLE = 2_000
MAD_TO_SIGMA = 1.4826

RULES = ("mode", "quality", "excluded", "outlier", "multivariate")

Mask = npt.NDArray[np.bool_]


@dataclass(frozen=True)
class Cluster:
    cycles: int  # retained cycles nearest this centre
    share: float  # of all retained cycles


@dataclass(frozen=True)
class Cleansing:
    retained: Mask  # per cycle of the training grid
    removed: dict[str, int]  # cycles each rule removed, in RULES order
    clusters: tuple[Cluster, ...]

    @property
    def cycles(self) -> int:
        return len(self.retained)

    @property
    def kept(self) -> int:
        return int(self.retained.sum())


def in_periods(index: pd.DatetimeIndex, periods: Sequence[Period]) -> Mask:
    """True for cycles inside any of the periods (start inclusive, end exclusive)."""
    times = index.to_numpy(dtype="datetime64[ns]").astype(np.int64)  # ns since the epoch
    inside = np.zeros(len(index), dtype=bool)
    for period in periods:
        start, end = pd.Timestamp(period.start).value, pd.Timestamp(period.end).value
        inside |= (times >= start) & (times < end)
    return inside


def robust_z(frame: pd.DataFrame) -> npt.NDArray[np.float64]:
    """(x - median) / (1.4826 x MAD) per column; a constant column gives 0."""
    values = frame.to_numpy(dtype=np.float64)
    with warnings.catch_warnings():  # a sensor with no value at all: its z is 0
        warnings.simplefilter("ignore", RuntimeWarning)
        median = np.nanmedian(values, axis=0)
        sigma = MAD_TO_SIGMA * np.nanmedian(np.abs(values - median), axis=0)
    safe = np.where(sigma > 0, sigma, 1.0)
    z = (values - median) / safe
    z[:, ~(sigma > 0)] = 0.0
    return np.asarray(z, dtype=np.float64)


def cleanse(
    frame: pd.DataFrame,
    in_mode: Mask,
    covered: Mask,
    exclusions: Sequence[Period] = (),
    seed: int = 0,
) -> Cleansing:
    """Apply the five rules to the training cycles; see the module notes for the order."""
    kept = np.ones(len(frame), dtype=bool)
    removed: dict[str, int] = {}

    def drop(rule: str, out: Mask) -> None:
        nonlocal kept
        hit = kept & out
        removed[rule] = int(hit.sum())
        kept = kept & ~out

    drop("mode", ~in_mode)
    drop("quality", ~covered)
    drop("excluded", in_periods(pd.DatetimeIndex(frame.index), exclusions))

    if kept.any():
        z = robust_z(frame[kept])
        extreme = np.zeros(len(frame), dtype=bool)
        extreme[np.flatnonzero(kept)] = np.nan_to_num(np.abs(z), nan=0.0).max(axis=1) > OUTLIER_Z
        drop("outlier", extreme)
    else:
        removed["outlier"] = 0

    clusters: tuple[Cluster, ...] = ()
    if kept.sum() >= MIN_FOR_CLUSTERS:
        rows = np.flatnonzero(kept)
        scaled = np.nan_to_num(robust_z(frame.iloc[rows]), nan=0.0)
        labels, distances = _clusters(scaled, seed)
        limit = float(np.percentile(distances, MULTIVARIATE_PERCENTILE))
        far = np.zeros(len(frame), dtype=bool)
        far[rows] = distances > limit
        drop("multivariate", far)
        survivors = labels[distances <= limit]
        total = max(len(survivors), 1)
        counts = np.bincount(survivors, minlength=int(labels.max()) + 1)
        clusters = tuple(
            Cluster(int(c), round(float(c) / total, 4)) for c in sorted(counts, reverse=True)
        )
    else:
        removed["multivariate"] = 0
    return Cleansing(np.asarray(kept, dtype=bool), removed, clusters)


def _clusters(
    values: npt.NDArray[np.float64], seed: int
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64]]:
    """Labels and distance to the nearest centre, k from 2 to 8 by silhouette score."""
    rng = np.random.default_rng(seed)
    sample = values[rng.permutation(len(values))[:SILHOUETTE_SAMPLE]]
    distinct = len(np.unique(values, axis=0))
    best: tuple[float, KMeans] | None = None
    for k in CLUSTER_RANGE:
        if k >= distinct:
            break
        model = KMeans(n_clusters=k, random_state=seed, n_init=3).fit(values)
        labels = model.predict(sample)
        score = (
            float(silhouette_score(sample, labels, random_state=seed))
            if 1 < len(set(labels.tolist())) < len(sample)
            else -1.0
        )
        if best is None or score > best[0]:
            best = (score, model)
    if best is None:  # everything identical: one cluster, no distance
        return np.zeros(len(values), dtype=np.int64), np.zeros(len(values))
    model = best[1]
    labels = np.asarray(model.predict(values), dtype=np.int64)
    centres = np.asarray(model.cluster_centers_, dtype=np.float64)
    distances = np.linalg.norm(values - centres[labels], axis=1)
    return labels, np.asarray(distances, dtype=np.float64)
