"""Time-to-threshold forecasting (UCS §6.8, FR-PRG-01, -02). Pure: no database.

Times are in days relative to the forecast time (the newest point is at or before 0), so
the fits stay well conditioned. A crossing is the first time at or after 0 at which the
fitted curve reaches the threshold in the direction of concern (up for an upper limit).

Linear y = a + b·t and exponential y = c + a·e^(b·t) are fitted by least squares; the
exponential is used only if it improves adjusted R² by at least 0.05. The exponential is
fitted by profiling b: for a fixed b the model is linear in (c, a), so every b of a fine
logarithmic grid is solved in closed form and the best kept. The same grid fits all the
bootstrap refits at once (each refit is a different y on the same design), which keeps
500 refits fast and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

BOOTSTRAP = 500
SEED = 0
MIN_POINTS = 96  # UC-11 precondition: at least 24 h of valid data, as 15-minute means
MIN_R2 = 0.5
EXP_GAIN = 0.05  # adjusted R² the exponential must add to be used
GRID = 600  # b values per sign: neighbours 1 % apart
B_RANGE = (0.05, 20.0)  # e-folds over the fit window


class ForecastError(ValueError):
    pass


class Method(StrEnum):
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


class Urgency(StrEnum):
    IMMEDIATE = "Immediate"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    NONE = "None"


@dataclass(frozen=True)
class UrgencyBands:
    """Upper bounds in hours of the lower interval bound (UCS §6.8, configurable)."""

    immediate_h: float = 24.0
    high_h: float = 24.0 * 7
    medium_h: float = 24.0 * 30

    def classify(self, lower_h: float | None) -> Urgency:
        if lower_h is None:
            return Urgency.NONE
        if lower_h <= self.immediate_h:
            return Urgency.IMMEDIATE
        if lower_h <= self.high_h:
            return Urgency.HIGH
        if lower_h <= self.medium_h:
            return Urgency.MEDIUM
        return Urgency.LOW


@dataclass(frozen=True)
class Fit:
    method: Method
    params: dict[str, float]  # linear: a, b; exponential: c, a, b (t in days)
    r2: float
    adj_r2: float

    def value(self, t_days: NDArray[np.float64] | float) -> NDArray[np.float64]:
        t = np.asarray(t_days, dtype=float)
        p = self.params
        if self.method is Method.LINEAR:
            return np.asarray(p["a"] + p["b"] * t)
        return np.asarray(p["c"] + p["a"] * np.exp(p["b"] * t))

    def slope(self, t_days: float = 0.0) -> float:
        p = self.params
        if self.method is Method.LINEAR:
            return p["b"]
        return float(p["a"] * p["b"] * np.exp(p["b"] * t_days))


@dataclass(frozen=True)
class Forecast:
    threshold: float
    direction: int  # +1: the threshold is an upper limit; -1: a lower limit
    points: int
    fit: Fit | None
    linear_adj_r2: float | None
    valid: bool
    reason: str | None  # why there is no trend to threshold
    median_h: float | None  # None: no crossing
    lower_h: float | None
    upper_h: float | None  # None: beyond the reach of over 10 % of the refits
    urgency: Urgency


def _r2(y: NDArray[np.float64], sse: float, k: int) -> tuple[float, float]:
    sst = float(np.sum((y - y.mean()) ** 2))
    if sst <= 0:
        return 0.0, 0.0
    r2 = 1.0 - sse / sst
    n = len(y)
    adj = 1.0 - (1.0 - r2) * (n - 1) / max(n - k - 1, 1)
    return r2, adj


def _linear(t: NDArray[np.float64], ys: NDArray[np.float64]) -> NDArray[np.float64]:
    """(a, b) for each row of ys."""
    design = np.column_stack([np.ones_like(t), t])
    coef, *_ = np.linalg.lstsq(design, ys.T, rcond=None)
    return np.asarray(coef.T)


def _b_grid(t: NDArray[np.float64]) -> NDArray[np.float64]:
    span = max(float(t.max() - t.min()), 1e-9)
    magnitudes = np.geomspace(B_RANGE[0], B_RANGE[1], GRID) / span
    return np.concatenate([-magnitudes[::-1], magnitudes])


def _exponential(t: NDArray[np.float64], ys: NDArray[np.float64]) -> NDArray[np.float64]:
    """(c, a, b) for each row of ys: the best b of the grid, (c, a) in closed form."""
    n_rows = ys.shape[0]
    yy = np.sum(ys * ys, axis=1)
    best_sse = np.full(n_rows, np.inf)
    best = np.zeros((n_rows, 3))
    for b in _b_grid(t):
        e = np.exp(b * t)
        design = np.column_stack([np.ones_like(t), e])
        gram = design.T @ design
        det = float(np.linalg.det(gram))
        if abs(det) < 1e-12 * float(np.trace(gram)) ** 2:
            continue
        inverse = np.linalg.inv(gram)
        xty = ys @ design  # (rows, 2)
        coef = xty @ inverse  # symmetric inverse
        sse = yy - np.sum(coef * xty, axis=1)
        better = sse < best_sse
        best_sse[better] = sse[better]
        best[better, 0] = coef[better, 0]
        best[better, 1] = coef[better, 1]
        best[better, 2] = b
    return best


def _crossings(
    method: Method, params: NDArray[np.float64], threshold: float, direction: int
) -> NDArray[np.float64]:
    """Days from 0 until each fitted curve reaches the threshold; 0 if already beyond,
    inf if never."""
    if method is Method.LINEAR:
        a, b = params[:, 0], params[:, 1]
        now = a
        with np.errstate(divide="ignore", invalid="ignore"):
            t = (threshold - a) / b
        reaches = (b * direction > 0) & np.isfinite(t)
    else:
        c, a, b = params[:, 0], params[:, 1], params[:, 2]
        now = c + a
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = (threshold - c) / a
            t = np.log(ratio) / b
        reaches = (ratio > 0) & np.isfinite(t) & (t >= 0)
    beyond = (threshold - now) * direction <= 0
    out = np.where(reaches & (t >= 0), t, np.inf)
    return np.where(beyond, 0.0, out)


def _quantile(values: NDArray[np.float64], q: float) -> float | None:
    """A sample quantile that keeps infinities (no interpolation across them)."""
    found = float(np.quantile(values, q, method="inverted_cdf"))
    return None if not np.isfinite(found) else found


def fit_trend(t_days: NDArray[np.float64], y: NDArray[np.float64]) -> tuple[Fit, float]:
    """The better fit and the linear fit's adjusted R²."""
    ys = y[None, :]
    a, b = _linear(t_days, ys)[0]
    sse = float(np.sum((y - (a + b * t_days)) ** 2))
    r2, adj = _r2(y, sse, 1)
    linear = Fit(Method.LINEAR, {"a": float(a), "b": float(b)}, r2, adj)
    c, ea, eb = _exponential(t_days, ys)[0]
    sse_exp = float(np.sum((y - (c + ea * np.exp(eb * t_days))) ** 2))
    r2_exp, adj_exp = _r2(y, sse_exp, 2)
    if adj_exp >= adj + EXP_GAIN:
        exponential = {"c": float(c), "a": float(ea), "b": float(eb)}
        return Fit(Method.EXPONENTIAL, exponential, r2_exp, adj_exp), adj
    return linear, adj


def forecast(
    t_days: NDArray[np.float64] | list[float],
    y: NDArray[np.float64] | list[float],
    threshold: float,
    *,
    direction: int | None = None,
    bands: UrgencyBands | None = None,
    refits: int = BOOTSTRAP,
    seed: int = SEED,
) -> Forecast:
    """UCS §6.8: fit, median crossing of `refits` residual-bootstrap refits, 80 % interval,
    validity and urgency. `direction` None: up if the threshold is above the fitted value
    now, else down."""
    bands = bands or UrgencyBands()
    t = np.asarray(t_days, dtype=float)
    values = np.asarray(y, dtype=float)
    keep = np.isfinite(t) & np.isfinite(values)
    t, values = t[keep], values[keep]
    if len(t) < MIN_POINTS:
        raise ForecastError(
            f"A forecast needs at least 24 h of valid data ({MIN_POINTS} 15-minute means); "
            f"the window has {len(t)}"
        )
    fit, linear_adj = fit_trend(t, values)
    now = float(fit.value(0.0))
    if direction is None:
        direction = 1 if threshold >= now else -1
    if direction not in (1, -1):
        raise ForecastError("direction must be +1 (upper limit) or -1 (lower limit)")

    def no_trend(reason: str) -> Forecast:
        return Forecast(
            threshold, direction, len(t), fit, linear_adj, False, reason,
            None, None, None, Urgency.NONE,
        )  # fmt: skip

    if fit.r2 < MIN_R2:
        return no_trend(f"No trend to threshold: fit quality R² {fit.r2:.2f} is below {MIN_R2}")
    if fit.slope(0.0) * direction <= 0:
        return no_trend("No trend to threshold: the trend is not moving towards the threshold")

    fitted = fit.value(t)
    residuals = values - fitted
    rng = np.random.default_rng(seed)
    samples = fitted[None, :] + residuals[rng.integers(0, len(t), size=(refits, len(t)))]
    params = _linear(t, samples) if fit.method is Method.LINEAR else _exponential(t, samples)
    days = _crossings(fit.method, params, threshold, direction)
    hours = days * 24.0
    median = _quantile(hours, 0.5)
    if median is None:
        return no_trend("No trend to threshold: most refits never reach the threshold")
    lower = _quantile(hours, 0.1)
    upper = _quantile(hours, 0.9)
    return Forecast(
        threshold,
        direction,
        len(t),
        fit,
        linear_adj,
        True,
        None,
        median,
        lower,
        upper,
        bands.classify(lower),
    )
