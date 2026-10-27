"""Model definition checks (UC-05 business rules) and definition files."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from pmp.modelling import (
    ModelDefinition,
    ModelError,
    Period,
    SensorChoice,
    check_definition,
    definition_from_dict,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
TAGS = {"T1", "T2", "T3", "MOTOR"}


def days(a: int, b: int) -> Period:
    return Period(T0 + timedelta(days=a), T0 + timedelta(days=b))


GOOD = ModelDefinition(
    asset_code="EQ-1",
    name="main",
    sensors=(SensorChoice("T1", required=True), SensorChoice("T2"), SensorChoice("T3")),
    training_periods=(days(0, 60), days(70, 100)),
    validation_period=days(100, 120),
    mode_filters=("MOTOR > 120",),
)


def problems(definition: ModelDefinition) -> list[str]:
    try:
        check_definition(definition, TAGS, {"median"})
    except ModelError as error:
        return error.problems
    return []


def test_a_good_definition_passes() -> None:
    assert problems(GOOD) == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"name": ""}, "Model name"),
        ({"name": "bad/name"}, "Model name"),
        ({"algorithm": "aakr"}, "Unknown or refused algorithm 'aakr'"),
        ({"sensors": ()}, "at least one sensor"),
        ({"sensors": (SensorChoice("T1"), SensorChoice("T1"))}, "listed twice: T1"),
        ({"sensors": (SensorChoice("T1"), SensorChoice("P9"))}, "Not tags of EQ-1: P9"),
        ({"training_periods": ()}, "at least one training period"),
        ({"training_periods": (days(5, 1),)}, "Training period 1 must end after"),
        ({"training_periods": (days(0, 50), days(40, 60))}, "Training periods 1 and 2 overlap"),
        ({"validation_period": days(50, 80)}, "overlaps the validation period"),
        (
            {"validation_period": Period(datetime(2026, 5, 1), datetime(2026, 6, 1))},
            "time zone",
        ),
        ({"mode_filters": ("MOTOR >",)}, "Operating-mode filter 1: Expression ends early"),
        ({"mode_filters": ("P9 > 1",)}, "names tags not on EQ-1: P9"),
        ({"exclusion_periods": (days(61, 65),)}, "Excluded period 1 is outside every training"),
        ({"exclusion_periods": (days(5, 5),)}, "Excluded period 1: the start must be before"),
    ],
)
def test_each_problem_is_reported(change: dict[str, object], expected: str) -> None:
    found = problems(replace(GOOD, **change))  # type: ignore[arg-type]
    assert any(expected in p for p in found), found


def test_touching_periods_do_not_overlap() -> None:
    assert problems(replace(GOOD, training_periods=(days(0, 100),))) == []


def test_all_problems_are_listed_together() -> None:
    found = problems(replace(GOOD, name="", sensors=(), algorithm="x"))
    assert len(found) == 3


def test_definition_files_accept_relative_and_absolute_times() -> None:
    now = datetime(2026, 10, 19, 14, 30, tzinfo=UTC)
    definition = definition_from_dict(
        {
            "asset": "EQ-1",
            "name": "main",
            "sensors": [{"tag": "T1", "required": True}, "T2"],
            "training_periods": [{"start": "-170d", "end": "2026-08-20T00:00:00+00:00"}],
            "validation_period": {"start": "-60d", "end": "-30d"},
            "mode_filters": ["MOTOR > 120"],
            "exclusion_periods": [{"start": "-150d", "end": "-149d"}],
            "params": {"seed": 1},
        },
        now,
    )
    assert definition.training_periods[0].start == datetime(2026, 5, 2, tzinfo=UTC)
    assert definition.validation_period == Period(
        datetime(2026, 8, 20, tzinfo=UTC), datetime(2026, 9, 19, tzinfo=UTC)
    )
    assert definition.sensors == (SensorChoice("T1", True), SensorChoice("T2"))
    assert definition.algorithm == "median"
    assert definition.params == {"seed": 1}
    assert definition.exclusion_periods == (
        Period(datetime(2026, 5, 22, tzinfo=UTC), datetime(2026, 5, 23, tzinfo=UTC)),
    )


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({}, "missing"),
        ({"asset": "A", "name": "m", "sensors": [], "training_periods": [{}]}, "expected"),
        (
            {
                "asset": "A",
                "name": "m",
                "sensors": [],
                "training_periods": [{"start": "yesterday", "end": "-1d"}],
                "validation_period": {"start": "-1d", "end": "-0d"},
            },
            "is not a time",
        ),
        (
            {
                "asset": "A",
                "name": "m",
                "sensors": [],
                "training_periods": [{"start": "2026-01-01T00:00", "end": "-1d"}],
                "validation_period": {"start": "-1d", "end": "-0d"},
            },
            "needs a time zone",
        ),
        (
            {
                "asset": "A",
                "name": "m",
                "sensors": [],
                "training_periods": [{"start": 5, "end": "-1d"}],
                "validation_period": {"start": "-1d", "end": "-0d"},
            },
            "expected a time",
        ),
        (
            {
                "asset": "A",
                "name": "m",
                "sensors": [],
                "training_periods": [],
                "validation_period": {"start": "-1d", "end": "-0d"},
                "params": [1],
            },
            "params must be an object",
        ),
        ({"asset": "A", "name": "m", "sensors": 5}, "malformed"),
    ],
)
def test_malformed_files_are_reported(data: dict[str, object], message: str) -> None:
    with pytest.raises(ModelError, match=message):
        definition_from_dict(data, T0)


@pytest.mark.parametrize("cycle_s", [5, 0, 9.5, "60", True])
def test_the_scoring_cycle_is_at_least_10_seconds(cycle_s: object) -> None:
    """FR-RUN-01: default 60 s, minimum 10 s."""
    definition = replace(GOOD, params={"cycle_s": cycle_s})
    with pytest.raises(ModelError, match="at least 10"):
        check_definition(definition, TAGS, {"median"})
