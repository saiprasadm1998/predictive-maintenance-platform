"""Sensor data-quality rules (UCS §6.1, FR-DQ-01 to -03). Pure logic, no database.

Rules are evaluated per sensor on every scoring cycle, before prediction. The first
matching rule, in the order of the UCS §6.1 table, sets the NAMUR NE 107 status:

    1 Bad source quality     Failure               excluded
    2 Stale                  Failure               excluded
    3 Manual exclusion       Function check        excluded
    4 Out of instrument range Out of specification excluded
    5 Flatline               Maintenance required  excluded (configurable to "used")
    6 Spike                  Maintenance required  sample excluded for that cycle
    7 Uncertain quality      Maintenance required  used, flagged
    8 None of the above      Good                  used

The same evaluator serves the live cycle (one cycle time) and the 30-day preview (one
cycle time per minute), so the two can never disagree.

Flatline and spike thresholds are percentages of the sensor's training range
(P99 - P1, UCS §6.2). Until a model is deployed there is no training range, so the
caller passes the instrument range instead and the flatline guard (training standard
deviation above 1 % of range) is skipped (implementation plan, decision for 2.1).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from pmp.core import Event

# Quality codes as stored in sample.quality (0 Good, 1 Uncertain, 2 Bad).
_UNCERTAIN = 1
_BAD = 2

MIN_COVERAGE = 0.70  # UCS §6.1 model coverage rule
PREVIEW_WARN_SHARE = 0.20  # UC-04 3a


class DataQualityError(ValueError):
    """Invalid rule parameters or scope."""


class Ne107(StrEnum):
    """NAMUR NE 107 sensor status categories (FR-DQ-02)."""

    GOOD = "Good"
    FAILURE = "Failure"
    FUNCTION_CHECK = "Function check"
    OUT_OF_SPECIFICATION = "Out of specification"
    MAINTENANCE_REQUIRED = "Maintenance required"


class Rule(StrEnum):
    """The rule that set a sensor's status, in evaluation order."""

    BAD_QUALITY = "bad_quality"
    STALE = "stale"
    MANUAL_EXCLUSION = "manual_exclusion"
    OUT_OF_RANGE = "out_of_range"
    FLATLINE = "flatline"
    SPIKE = "spike"
    UNCERTAIN_QUALITY = "uncertain_quality"
    NONE = "none"


class Effect(StrEnum):
    """What scoring does with the sensor this cycle."""

    USED = "used"
    USED_FLAGGED = "used_flagged"
    EXCLUDED = "excluded"
    SAMPLE_EXCLUDED = "sample_excluded"

    @property
    def usable(self) -> bool:
        return self in (Effect.USED, Effect.USED_FLAGGED)


RULE_ORDER: tuple[Rule, ...] = tuple(Rule)

STATUS_OF: Mapping[Rule, Ne107] = {
    Rule.BAD_QUALITY: Ne107.FAILURE,
    Rule.STALE: Ne107.FAILURE,
    Rule.MANUAL_EXCLUSION: Ne107.FUNCTION_CHECK,
    Rule.OUT_OF_RANGE: Ne107.OUT_OF_SPECIFICATION,
    Rule.FLATLINE: Ne107.MAINTENANCE_REQUIRED,
    Rule.SPIKE: Ne107.MAINTENANCE_REQUIRED,
    Rule.UNCERTAIN_QUALITY: Ne107.MAINTENANCE_REQUIRED,
    Rule.NONE: Ne107.GOOD,
}


# ------------------------------------------------------------------ parameters


@dataclass(frozen=True)
class RuleParams:
    """Thresholds and on/off switches. Defaults are the UCS §6.1 defaults.

    Percentages are of the sensor's reference range (training range once a model is
    deployed, instrument range before). Manual exclusion cannot be switched off, and a
    sensor with no sample at all is always reported Stale.
    """

    bad_quality: bool = True
    stale: bool = True
    stale_factor: float = 3.0  # times the expected sampling interval
    out_of_range: bool = True
    flatline: bool = True
    flatline_window: int = 30  # samples
    flatline_std_pct: float = 0.1  # % of range
    flatline_guard_pct: float = 1.0  # % of range (training standard deviation)
    flatline_used: bool = False  # True: flatlined sensors stay in scoring
    spike: bool = True
    spike_pct: float = 25.0  # % of range, between consecutive samples
    uncertain_quality: bool = True

    def with_overrides(self, overrides: Mapping[str, Any]) -> RuleParams:
        return replace(self, **parse_overrides(overrides))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULTS = RuleParams()
PARAM_NAMES: tuple[str, ...] = tuple(f.name for f in fields(RuleParams))
_BOOL_PARAMS = frozenset(f.name for f in fields(RuleParams) if f.type in ("bool", bool))
_INT_PARAMS = frozenset({"flatline_window"})
_TRUE = {"true", "on", "yes", "1"}
_FALSE = {"false", "off", "no", "0"}


def parse_overrides(overrides: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a partial set of parameters; strings like 'off' or '30' are accepted."""
    parsed: dict[str, Any] = {}
    for name, raw in overrides.items():
        if name not in PARAM_NAMES:
            raise DataQualityError(
                f"Unknown rule parameter {name!r}; known: {', '.join(PARAM_NAMES)}"
            )
        if name in _BOOL_PARAMS:
            parsed[name] = _parse_bool(name, raw)
        elif name in _INT_PARAMS:
            value = _parse_number(name, raw)
            if value != int(value) or value < 2:
                raise DataQualityError(f"{name} must be a whole number of at least 2")
            parsed[name] = int(value)
        else:
            value = _parse_number(name, raw)
            if value <= 0:
                raise DataQualityError(f"{name} must be greater than 0")
            parsed[name] = value
    return parsed


def _parse_bool(name: str, raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.strip().lower() in _TRUE | _FALSE:
        return raw.strip().lower() in _TRUE
    raise DataQualityError(f"{name} must be on or off")


def _parse_number(name: str, raw: Any) -> float:
    if isinstance(raw, bool):
        raise DataQualityError(f"{name} must be a number")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise DataQualityError(f"{name} must be a number") from None
    if not np.isfinite(value):
        raise DataQualityError(f"{name} must be a finite number")
    return value


def resolve_params(*layers: Mapping[str, Any]) -> RuleParams:
    """Defaults, then each override layer in turn (global, role, tag)."""
    params = DEFAULTS
    for layer in layers:
        params = params.with_overrides(layer)
    return params


# ------------------------------------------------------------------ sensor and result


@dataclass(frozen=True)
class SensorConfig:
    """What the rules need to know about one sensor."""

    range_lo: float
    range_hi: float
    interval_s: int
    reference_range: float | None = None  # training range; None → instrument range
    training_std: float | None = None  # None → flatline guard skipped

    @property
    def range(self) -> float:
        if self.reference_range is not None and self.reference_range > 0:
            return self.reference_range
        return self.range_hi - self.range_lo


@dataclass(frozen=True)
class SensorState:
    status: Ne107
    rule: Rule
    effect: Effect

    @property
    def usable(self) -> bool:
        return self.effect.usable


def state_for(rule: Rule, params: RuleParams) -> SensorState:
    if rule is Rule.FLATLINE:
        effect = Effect.USED if params.flatline_used else Effect.EXCLUDED
    elif rule is Rule.SPIKE:
        effect = Effect.SAMPLE_EXCLUDED
    elif rule is Rule.UNCERTAIN_QUALITY:
        effect = Effect.USED_FLAGGED
    elif rule is Rule.NONE:
        effect = Effect.USED
    else:
        effect = Effect.EXCLUDED
    return SensorState(STATUS_OF[rule], rule, effect)


@dataclass(frozen=True)
class Samples:
    """One sensor's samples, oldest first: timestamps as int64 ns, values, quality codes."""

    ts: npt.NDArray[np.int64]
    value: npt.NDArray[np.float64]
    quality: npt.NDArray[np.int8]

    @classmethod
    def from_rows(cls, rows: Sequence[tuple[datetime, float, int]]) -> Samples:
        if not rows:
            return cls.empty()
        return cls(
            ts=_epoch_ns([r[0] for r in rows]),
            value=np.asarray([r[1] for r in rows], dtype=np.float64),
            quality=np.asarray([int(r[2]) for r in rows], dtype=np.int8),
        )

    @classmethod
    def empty(cls) -> Samples:
        return cls(
            np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float64), np.empty(0, dtype=np.int8)
        )


def _epoch_ns(moments: Sequence[datetime]) -> npt.NDArray[np.int64]:
    """Nanoseconds since the Unix epoch (UTC); naive times are taken as UTC."""
    index = pd.DatetimeIndex(list(moments))
    if index.tz is not None:
        index = index.tz_convert("UTC").tz_localize(None)
    return np.asarray(index.as_unit("ns").to_numpy().view(np.int64), dtype=np.int64)


def to_ns(moments: Sequence[datetime] | datetime) -> npt.NDArray[np.int64]:
    return _epoch_ns([moments] if isinstance(moments, datetime) else list(moments))


# ------------------------------------------------------------------ evaluation


def evaluate_rules(
    samples: Samples,
    config: SensorConfig,
    params: RuleParams,
    cycle_ns: npt.NDArray[np.int64],
    excluded: npt.NDArray[np.bool_] | None = None,
) -> npt.NDArray[np.int8]:
    """The rule that sets the status at each cycle time, as an index into RULE_ORDER.

    Each cycle uses the latest sample at or before the cycle time (sample-and-hold, UCS
    §6.2). `excluded` marks cycles with an active manual exclusion.
    """
    n = len(cycle_ns)
    if excluded is None:
        excluded = np.zeros(n, dtype=bool)
    idx = np.searchsorted(samples.ts, cycle_ns, side="right") - 1
    has = idx >= 0
    safe = np.where(has, idx, 0)
    if len(samples.ts) == 0:
        return np.full(n, RULE_ORDER.index(Rule.STALE), dtype=np.int8)

    quality = samples.quality[safe]
    value = samples.value[safe]
    age_ns = cycle_ns - samples.ts[safe]
    width = config.range

    no_data = ~has
    bad = has & (quality == _BAD)
    stale = has & (age_ns > params.stale_factor * config.interval_s * 1_000_000_000)
    out = has & ((value < config.range_lo) | (value > config.range_hi))

    window = params.flatline_window
    rolling_std = (
        pd.Series(samples.value).rolling(window, min_periods=window).std(ddof=0).to_numpy()
    )
    guard_ok = (
        config.training_std is None or config.training_std > params.flatline_guard_pct / 100 * width
    )
    flat_at_sample = np.nan_to_num(rolling_std, nan=np.inf) < params.flatline_std_pct / 100 * width
    flat = has & flat_at_sample[safe] & guard_ok

    jump = np.zeros(len(samples.value))
    jump[1:] = np.abs(np.diff(samples.value))
    spike = has & (jump[safe] > params.spike_pct / 100 * width)
    uncertain = has & (quality == _UNCERTAIN)

    conditions = [
        bad & params.bad_quality,
        no_data | (stale & params.stale),
        excluded,
        out & params.out_of_range,
        flat & params.flatline,
        spike & params.spike,
        uncertain & params.uncertain_quality,
    ]
    choices = list(range(len(conditions)))
    return np.select(conditions, choices, default=RULE_ORDER.index(Rule.NONE)).astype(np.int8)


def evaluate_sensor(
    samples: Samples,
    config: SensorConfig,
    params: RuleParams,
    at: datetime,
    excluded: bool = False,
) -> SensorState:
    """The sensor's status at one cycle time (the live scoring cycle)."""
    code = evaluate_rules(samples, config, params, to_ns(at), np.array([excluded]))[0]
    return state_for(RULE_ORDER[int(code)], params)


# ------------------------------------------------------------------ coverage


@dataclass(frozen=True)
class Coverage:
    usable: int
    total: int
    missing_required: tuple[int, ...]

    @property
    def share(self) -> float:
        return self.usable / self.total if self.total else 0.0

    @property
    def scoreable(self) -> bool:
        """UCS §6.1: at least 70 % of sensors usable and every required sensor usable."""
        return self.total > 0 and self.share >= MIN_COVERAGE and not self.missing_required


def coverage(states: Mapping[int, SensorState], required: Collection[int] = ()) -> Coverage:
    """Model coverage over its sensors (tag ID → state)."""
    missing = tuple(sorted(t for t in required if t not in states or not states[t].usable))
    usable = sum(1 for s in states.values() if s.usable)
    return Coverage(usable=usable, total=len(states), missing_required=missing)


# ------------------------------------------------------------------ events


@dataclass(frozen=True, kw_only=True)
class SensorStatusChanged(Event):
    """Published when a sensor's NE 107 status or the rule that set it changes."""

    tag_id: int
    previous: Ne107 | None
    status: Ne107
    rule: Rule
