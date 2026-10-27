"""Training-data cleansing (UC-05 steps 3 to 6, FR-MOD-02, -03, UCS §6.4, plan 7.2).

The rules run in this order on the training periods' cycle grid; each sees only the
cycles the rules before it kept, so the effect of every rule can be shown on its own
(SCR-06 step 3):

1. quality: the data-quality rules and the coverage rule (70 % of sensors usable, every
   required sensor usable)
2. mode: outside the operating-mode filters
3. outlier: any sensor with |robust z| > 4 against the median and MAD of its operating
   cluster (decision 7.4, for review; UCS §6.4 says the training median and MAD); the
   whole cycle goes (decision 7.2), so the model remembers only clean states
4. multivariate: further from its operating cluster's centre than 99.9 % of the cycles
   kept so far

The operating clusters come from a first k-means pass on the robust-scaled data, 2 to 8
clusters by silhouette score, seeded.
5. excluded: inside a period the engineer excluded on the trend

This is the order of the UCS §6.4 table (corrected in 7.4; 7.2 had mode first and the
excluded periods before the outlier rules).

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
MIN_PER_CLUSTER = 30  # a cluster this small keeps all its cycles (no outlier rule)
SILHOUETTE_SAMPLE = 2_000
MAD_TO_SIGMA = 1.4826

RULES = ("quality", "mode", "outlier", "multivariate", "excluded")

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

    drop("quality", ~covered)
    drop("mode", ~in_mode)

    # A first k-means pass finds the operating clusters (UCS §6.4). The per-sensor outlier
    # rule runs within each cluster (decision 7.4, for review): on the whole data set, one
    # median and MAD would make a smaller operating state, such as a turndown, look like
    # outliers and remove it from training.
    labels_of = np.full(len(frame), -1)
    if kept.sum() >= MIN_FOR_CLUSTERS:
        rows = np.flatnonzero(kept)
        scaled = np.nan_to_num(robust_z(frame.iloc[rows]), nan=0.0)
        labels, centres = _clusters(scaled, seed)
        # A cluster of a handful of cycles is not an operating state (often a spike): its
        # cycles join the nearest real cluster, so the rules below can still judge them.
        sizes = np.bincount(labels, minlength=len(centres))
        real = np.flatnonzero(sizes >= MIN_PER_CLUSTER)
        if len(real) and len(real) < len(centres):
            stray = ~np.isin(labels, real)
            gaps = np.linalg.norm(scaled[stray][:, None, :] - centres[real][None], axis=2)
            labels = labels.copy()
            labels[stray] = real[gaps.argmin(axis=1)]
        labels_of[rows] = labels
        position = np.full(len(frame), -1)
        position[rows] = np.arange(len(rows))
        extreme = np.zeros(len(frame), dtype=bool)
        for label in np.unique(labels):
            members = rows[labels == label]
            if len(members) < MIN_PER_CLUSTER:
                continue  # too few cycles for a median and MAD
            z = np.nan_to_num(np.abs(robust_z(frame.iloc[members])), nan=0.0)
            extreme[members] = z.max(axis=1) > OUTLIER_Z
        drop("outlier", extreme)

        # Multivariate: distance to the cluster centre, beyond the 99.9th percentile.
        # (in the first pass's scaling, so the centres and the cycles agree)
        rows = np.flatnonzero(kept)
        distances = np.linalg.norm(scaled[position[rows]] - centres[labels_of[rows]], axis=1)
        far = np.zeros(len(frame), dtype=bool)
        if len(rows):
            far[rows] = distances > float(np.percentile(distances, MULTIVARIATE_PERCENTILE))
        drop("multivariate", far)
    else:
        removed["outlier"] = removed["multivariate"] = 0

    drop("excluded", in_periods(pd.DatetimeIndex(frame.index), exclusions))

    clusters: tuple[Cluster, ...] = ()
    survivors = labels_of[kept & (labels_of >= 0)]
    if len(survivors):
        counts = np.bincount(survivors)
        total = len(survivors)
        clusters = tuple(
            Cluster(int(c), round(float(c) / total, 4))
            for c in sorted(counts, reverse=True)
            if c > 0
        )
    return Cleansing(np.asarray(kept, dtype=bool), removed, clusters)


def _clusters(
    values: npt.NDArray[np.float64], seed: int
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64]]:
    """Labels and centres, k from 2 to 8 by silhouette score on a seeded sample."""
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
    if best is None:  # everything identical: one cluster at its centre
        return np.zeros(len(values), dtype=np.int64), values[:1].copy()
    model = best[1]
    labels = np.asarray(model.predict(values), dtype=np.int64)
    return labels, np.asarray(model.cluster_centers_, dtype=np.float64)
