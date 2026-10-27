"""Model definitions and their checks (UC-05 steps 1, 2 and 4; FR-MOD-03). Pure logic.

A definition is what the model engineer chooses before training: the asset, its sensors
(and which are required), one or more training periods, a hold-out validation period,
operating-mode filters, and the algorithm. It lives on a Draft model version until that
version is trained (3.2); once Validated a version never changes (ARC §6.2).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pmp.modelling.expressions import ExpressionError, parse_expression

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.\-]{0,99}")
_RELATIVE = re.compile(r"-(\d+)d")


class ModelError(ValueError):
    """A definition or request that cannot be accepted; lists every problem found."""

    def __init__(self, problems: str | list[str]) -> None:
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("; ".join(self.problems))


class VersionStatus(StrEnum):
    """Model version states (ARC Figure 7); transitions arrive in 3.3."""

    DRAFT = "Draft"
    TRAINING = "Training"
    FAILED = "Failed"
    VALIDATED = "Validated"
    REJECTED = "Rejected"
    DEPLOYED = "Deployed"
    PAUSED = "Paused"
    SUPERSEDED = "Superseded"
    RETIRED = "Retired"


@dataclass(frozen=True)
class Period:
    start: datetime
    end: datetime

    def problems(self, label: str) -> list[str]:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            return [f"{label} needs times with a time zone"]
        if not self.start < self.end:
            return [f"{label} must end after it starts"]
        return []

    def overlaps(self, other: Period) -> bool:
        return self.start < other.end and other.start < self.end

    def __str__(self) -> str:
        return f"{self.start:%Y-%m-%d %H:%M} to {self.end:%Y-%m-%d %H:%M} UTC"


@dataclass(frozen=True)
class SensorChoice:
    tag: str  # source name
    required: bool = False
    source: str | None = None  # only needed if the name exists in several sources


@dataclass(frozen=True)
class ModelDefinition:
    asset_code: str
    name: str
    sensors: tuple[SensorChoice, ...]
    training_periods: tuple[Period, ...]
    validation_period: Period
    mode_filters: tuple[str, ...] = ()
    description: str = ""
    # Periods the engineer excluded on the training trend (UC-05 step 5, plan 7.2).
    exclusion_periods: tuple[Period, ...] = ()
    algorithm: str = "aakr"  # the default detector (plan 7.4)
    params: Mapping[str, Any] = field(default_factory=dict)


MIN_CYCLE_S = 10  # FR-RUN-01: default 60 s, minimum 10 s


def check_definition(
    definition: ModelDefinition,
    asset_tags: Collection[str],
    algorithms: Collection[str],
) -> None:
    """Raise ModelError listing every problem: the UC-05 rules plus consistency checks.

    `asset_tags` are the source names of the asset's tags; `algorithms` the enabled
    detector names.
    """
    problems: list[str] = []
    if not _NAME.fullmatch(definition.name.strip()):
        problems.append("Model name must be 1 to 100 letters, digits, spaces, '.', '_' or '-'")
    if definition.algorithm not in algorithms:
        problems.append(f"Unknown or refused algorithm {definition.algorithm!r}")

    names = [s.tag for s in definition.sensors]
    if not names:
        problems.append("Select at least one sensor")
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        problems.append(f"Sensors listed twice: {', '.join(duplicates)}")
    foreign = [n for n in dict.fromkeys(names) if n not in asset_tags]
    if foreign:
        problems.append(f"Not tags of {definition.asset_code}: {', '.join(foreign)}")

    cycle_s = definition.params.get("cycle_s", 60)
    if isinstance(cycle_s, bool) or not isinstance(cycle_s, int) or cycle_s < MIN_CYCLE_S:
        problems.append(
            f"Scoring cycle (params.cycle_s) must be a whole number of seconds, at least "
            f"{MIN_CYCLE_S} (FR-RUN-01; default 60)"
        )

    if not definition.training_periods:
        problems.append("Select at least one training period")
    period_problems: list[str] = []
    for i, period in enumerate(definition.training_periods, start=1):
        period_problems += period.problems(f"Training period {i}")
    period_problems += definition.validation_period.problems("Validation period")
    problems += period_problems
    if not period_problems:
        periods = definition.training_periods
        for i, a in enumerate(periods):
            for j in range(i + 1, len(periods)):
                if a.overlaps(periods[j]):
                    problems.append(f"Training periods {i + 1} and {j + 1} overlap")
        for i, period in enumerate(periods, start=1):
            if period.overlaps(definition.validation_period):
                problems.append(
                    f"Training period {i} overlaps the validation period "
                    "(UC-05: they may not overlap)"
                )

    for i, period in enumerate(definition.exclusion_periods, start=1):
        if not period.start < period.end:
            problems.append(f"Excluded period {i}: the start must be before the end")
        elif not any(period.overlaps(t) for t in definition.training_periods):
            problems.append(f"Excluded period {i} is outside every training period")

    for i, text in enumerate(definition.mode_filters, start=1):
        try:
            expression = parse_expression(text)
        except ExpressionError as error:
            problems.append(f"Operating-mode filter {i}: {error}")
            continue
        unknown = sorted(expression.names - set(asset_tags))
        if unknown:
            problems.append(
                f"Operating-mode filter {i} names tags not on {definition.asset_code}: "
                f"{', '.join(unknown)}"
            )
    if problems:
        raise ModelError(problems)


# ------------------------------------------------------------------ definition files


def _moment(value: Any, now: datetime, label: str) -> datetime:
    """ISO 8601 with a time zone, or '-Nd': N days before today 00:00 UTC."""
    if not isinstance(value, str):
        raise ModelError(f"{label}: expected a time, got {value!r}")
    match = _RELATIVE.fullmatch(value.strip())
    if match:
        midnight = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight - timedelta(days=int(match.group(1)))
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise ModelError(f"{label}: {value!r} is not a time (ISO 8601 or -Nd)") from None
    if moment.tzinfo is None:
        raise ModelError(f"{label}: {value!r} needs a time zone, e.g. Z or +00:00")
    return moment


def _period(raw: Any, now: datetime, label: str) -> Period:
    if not isinstance(raw, Mapping) or "start" not in raw or "end" not in raw:
        raise ModelError(f"{label}: expected {{'start': ..., 'end': ...}}")
    return Period(_moment(raw["start"], now, label), _moment(raw["end"], now, label))


def definition_from_dict(data: Mapping[str, Any], now: datetime) -> ModelDefinition:
    """Read a model definition file's content (JSON); relative times resolve against now."""
    try:
        sensors = tuple(
            SensorChoice(str(s["tag"]), bool(s.get("required", False)), s.get("source"))
            if isinstance(s, Mapping)
            else SensorChoice(str(s))
            for s in data["sensors"]
        )
        training = tuple(
            _period(p, now, f"Training period {i}")
            for i, p in enumerate(data["training_periods"], start=1)
        )
        params = data.get("params", {})
        if not isinstance(params, Mapping):
            raise ModelError("params must be an object")
        return ModelDefinition(
            asset_code=str(data["asset"]),
            name=str(data["name"]),
            sensors=sensors,
            training_periods=training,
            validation_period=_period(data["validation_period"], now, "Validation period"),
            mode_filters=tuple(str(f) for f in data.get("mode_filters", [])),
            exclusion_periods=tuple(
                _period(p, now, f"Excluded period {i}")
                for i, p in enumerate(data.get("exclusion_periods", []), start=1)
            ),
            description=str(data.get("description", "")),
            algorithm=str(data.get("algorithm", "aakr")),
            params=dict(params),
        )
    except KeyError as missing:
        raise ModelError(f"Model definition is missing {missing}") from None
    except TypeError as error:
        raise ModelError(f"Model definition is malformed: {error}") from None
