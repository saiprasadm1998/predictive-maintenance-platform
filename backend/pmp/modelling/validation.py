"""Validation report and proposed limits (FR-MOD-06, UCS §6.4, UC-05 steps 7 and 8, plan 7.3).

The validation period is played back exactly as runtime scores it, then summarised:

- per sensor: normalised RMSE (RMSE / R) and bias, already in the training statistics
- the Deviation Index of every cycle, DI = 100 x sqrt(mean q^2) over the usable sensors with
  q = |residual| / R (UCS §6.2), and its percentiles P50, P95, P99 and P99.9
- the share of cycles outside the model's envelope, for detectors that have one (AAKR)
- proposed limits: DI warning 1.2 x P99; DI alert 1.5 x P99.9 with a minimum of 10 % (DI is
  a percentage: the alert limit is never below DI 10); sensor |z| warning 3 and alert 5
- the alerts the proposed DI limits would have raised over the hold-out, per model-week,
  with the default alert rule (3 of 5 cycles to raise; below the limit less a 10 % deadband
  for 5 cycles to clear). The hold-out is normal operation, so each one is a false alert;
  more than one a week brings the UC-05 8a warning.

Alerting sits above modelling (the import contract), so the rule is simulated here rather
than taken from the alert engine; the defaults are the same (pmp.alerting.domain).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

PERCENTILES = (50.0, 95.0, 99.0, 99.9)
WARNING_FACTOR, ALERT_FACTOR, ALERT_MINIMUM = 1.2, 1.5, 10.0
SENSOR_WARNING_Z, SENSOR_ALERT_Z = 3.0, 5.0
PERSISTENCE_N, PERSISTENCE_M = 3, 5  # pmp.alerting.domain defaults
DEADBAND, CLEAR_CYCLES = 0.10, 5
MAX_FALSE_PER_WEEK = 1.0
WEEK_S = 7 * 86_400


@dataclass(frozen=True)
class ProposedLimits:
    di_warning: float
    di_alert: float
    sensor_warning: float = SENSOR_WARNING_Z
    sensor_alert: float = SENSOR_ALERT_Z


@dataclass(frozen=True)
class ValidationReport:
    cycles: int  # validation cycles scored
    di_percentiles: dict[str, float]  # "P50", "P95", "P99", "P99.9"
    outside_envelope: float | None  # share of cycles; None: the detector has no envelope
    proposed: ProposedLimits
    alerts: int  # raised over the hold-out with the proposed DI limits
    alerts_per_week: float
    warning: str | None  # UC-05 8a, in plain language

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def deviation_index(
    actual: pd.DataFrame, predicted: pd.DataFrame, ranges: Mapping[str, float]
) -> npt.NDArray[np.float64]:
    """DI per cycle over the usable sensors (actual not NaN); NaN when none is usable."""
    columns = list(actual.columns)
    r = np.array([ranges[c] for c in columns], dtype=np.float64)
    q = np.abs(actual.to_numpy(dtype=np.float64) - predicted[columns].to_numpy(dtype=np.float64))
    q = q / r
    usable = ~np.isnan(q)
    count = usable.sum(axis=1)
    total = np.where(usable, q**2, 0.0).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        di = 100.0 * np.sqrt(total / count)
    return np.asarray(np.where(count > 0, di, np.nan), dtype=np.float64)


def _round_up(value: float) -> float:
    """Limits to one decimal, rounded up so a proposal is never below its formula."""
    return math.ceil(value * 10 - 1e-9) / 10


def propose_limits(percentiles: Mapping[str, float]) -> ProposedLimits:
    """UCS §6.4. P99.9 >= P99, so the alert limit is always above the warning limit."""
    warning = max(_round_up(WARNING_FACTOR * percentiles["P99"]), 0.1)  # 0.1: a perfect fit
    alert = _round_up(max(ALERT_FACTOR * percentiles["P99.9"], ALERT_MINIMUM))
    return ProposedLimits(di_warning=warning, di_alert=alert)


def count_alerts(di: Sequence[float] | npt.NDArray[np.float64], limit: float) -> int:
    """Alerts the default rule raises on a DI series: n of the last m cycles at or above the
    limit raises; clear after CLEAR_CYCLES cycles below limit x (1 - deadband). A cycle
    without a DI (NaN) counts as below and does not clear."""
    window: list[bool] = []
    raised, below, count = False, 0, 0
    for value in di:
        finite = not math.isnan(float(value))
        above = finite and value >= limit
        window = [*window[-(PERSISTENCE_M - 1) :], above]
        if not raised:
            if sum(window) >= PERSISTENCE_N:
                raised, below, count = True, 0, count + 1
        elif finite and value < limit * (1 - DEADBAND):
            below += 1
            if below >= CLEAR_CYCLES:
                raised, window = False, []
        else:
            below = 0
    return count


def validation_report(
    di: npt.NDArray[np.float64],
    cycle_s: int,
    outside_envelope: npt.NDArray[np.bool_] | None = None,
) -> ValidationReport:
    scored = di[~np.isnan(di)]
    if len(scored) == 0:
        raise ValueError("No validation cycle could be scored")
    values = np.percentile(scored, PERCENTILES)
    percentiles = {f"P{p:g}": round(float(v), 3) for p, v in zip(PERCENTILES, values, strict=True)}
    proposed = propose_limits(percentiles)
    alerts = count_alerts(di, proposed.di_warning)
    weeks = len(di) * cycle_s / WEEK_S
    per_week = round(alerts / weeks, 2) if weeks > 0 else 0.0
    warning = (
        f"About {per_week:g} false alerts per week are expected with these limits on normal "
        "operation (more than one a week). Review the training data or raise the limits."
        if per_week > MAX_FALSE_PER_WEEK
        else None
    )
    envelope = (
        round(float(np.mean(outside_envelope)), 4)
        if outside_envelope is not None and len(outside_envelope)
        else None
    )
    return ValidationReport(
        cycles=len(scored),
        di_percentiles=percentiles,
        outside_envelope=envelope,
        proposed=proposed,
        alerts=alerts,
        alerts_per_week=per_week,
        warning=warning,
    )
