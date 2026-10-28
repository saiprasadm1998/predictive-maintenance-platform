"""Failure-mode signature matching (plan 8.2, UCS §6.7.2): the formula on reference cases."""

from __future__ import annotations

import pytest

from pmp.diagnostics import (
    Direction,
    LibraryError,
    ModeSpec,
    Reading,
    Symptom,
    SymptomResult,
    agreement,
    check_mode,
    match_mode,
    rank,
)

UP, DOWN, ANY = Direction.UP, Direction.DOWN, Direction.ANY


@pytest.mark.parametrize(
    ("z", "direction", "expected"),
    [
        (3.1, UP, 1.0),  # capped at 1
        (1.5, UP, 0.5),
        (-1.5, UP, 0.0),  # the opposite direction counts nothing
        (-1.5, DOWN, 0.5),
        (-1.4, ANY, 1.4 / 3),
        (0.0, ANY, 0.0),
    ],
)
def test_agreement_follows_ucs_6_7_2(z: float, direction: Direction, expected: float) -> None:
    assert agreement(z, direction) == pytest.approx(expected)


# Wireframe 04: thrust bearing degradation, its thrust pad sensor excluded.
THRUST = ModeSpec(
    "thrust_bearing_degradation",
    "Thrust bearing degradation",
    (
        Symptom("de_bearing_temp", UP, 2),
        Symptom("axial_displacement", UP, 3),
        Symptom("lube_oil_supply_temp", ANY, 1),
        Symptom("thrust_pad_temp", UP, 3),
    ),
)


def test_an_excluded_sensor_is_not_evaluated_and_leaves_both_sums() -> None:
    readings = {
        "de_bearing_temp": Reading(3.1, True),
        "axial_displacement": Reading(2.0, True),
        "lube_oil_supply_temp": Reading(1.4, True),
        "thrust_pad_temp": Reading(4.0, False),  # excluded (UC-14)
    }
    match = match_mode(THRUST, readings)
    # 100 x (2 x 1 + 3 x 2/3 + 1 x 1.4/3) / (2 + 3 + 1)
    assert match.score == pytest.approx(100 * (2 + 2 + 1.4 / 3) / 6)
    assert (match.evaluated_weight, match.total_weight) == (6, 9)
    assert not match.insufficient  # 6 of 9 is over half
    assert [s.result for s in match.symptoms] == [
        SymptomResult.MATCH,
        SymptomResult.MATCH,
        SymptomResult.PARTIAL,
        SymptomResult.NOT_EVALUATED,
    ]


def test_less_than_half_the_weight_is_insufficient_evidence() -> None:
    readings = {"de_bearing_temp": Reading(3.0, True), "lube_oil_supply_temp": Reading(3.0, True)}
    match = match_mode(THRUST, readings)  # 3 of 9 evaluated
    assert match.insufficient
    assert match.score == pytest.approx(100.0)  # computed, but shown as insufficient


def test_each_sensor_uses_its_own_warning_limit_as_z_ref() -> None:
    mode = ModeSpec("m", "M", (Symptom("a", UP, 1),))
    assert match_mode(mode, {"a": Reading(2.0, True, z_ref=4.0)}).score == pytest.approx(50.0)


def test_modes_rank_by_score_with_insufficient_evidence_last() -> None:
    a = ModeSpec("a", "A", (Symptom("x", UP, 1),))
    b = ModeSpec("b", "B", (Symptom("x", ANY, 1),))
    c = ModeSpec("c", "C", (Symptom("x", UP, 1), Symptom("y", UP, 5)))
    readings = {"x": Reading(-3.0, True)}
    ranked = rank([match_mode(m, readings) for m in (a, b, c)])
    assert [m.spec.code for m in ranked] == ["b", "a", "c"]  # c: 1 of 6 evaluated


def test_a_mode_needs_known_roles_and_positive_weights() -> None:
    bad = ModeSpec(
        "Bad Code",
        " ",
        (Symptom("nope", UP, 0), Symptom("nope", UP, 1)),
        tasks=("",),
    )
    with pytest.raises(LibraryError) as found:
        check_mode(bad, ["de_bearing_temp"])
    message = str(found.value)
    for part in (
        "lower-case letters",
        "The name is required",
        "no role 'nope'",
        "used twice",
        "weight must be above 0",
        "A task cannot be empty",
    ):
        assert part in message
