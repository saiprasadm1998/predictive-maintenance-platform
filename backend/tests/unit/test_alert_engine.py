"""The alert state machine and rule evaluation (UCS §6.6, Figure 6; ISA-18.2)."""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pmp.alerting.domain import AlertRuleSpec, RuleKind
from pmp.alerting.engine import (
    TRANSITIONS,
    AlertError,
    AlertState,
    RuleMemory,
    Severity,
    Trigger,
    level_of,
    replay,
    step,
    transition,
)

S = AlertState
START = datetime(2026, 10, 1, tzinfo=UTC)
REFERENCE = Path(__file__).parents[1] / "reference_data" / "alert_reference.json"
CODES = {"N": S.NORMAL, "AU": S.ACTIVE_UNACK, "AA": S.ACTIVE_ACK, "RU": S.RTN_UNACK}


def di_rule(**overrides: Any) -> AlertRuleSpec:
    return AlertRuleSpec(kind=RuleKind.DI, **{"warning": 15.0, "alert": 25.0, **overrides})


# ------------------------------------------------------------------ transitions


@pytest.mark.parametrize(
    ("state", "trigger", "target"),
    [
        (S.NORMAL, Trigger.RAISE, S.ACTIVE_UNACK),
        (S.ACTIVE_UNACK, Trigger.ACK, S.ACTIVE_ACK),
        (S.ACTIVE_UNACK, Trigger.CLEAR, S.RTN_UNACK),
        (S.ACTIVE_ACK, Trigger.CLEAR, S.NORMAL),
        (S.RTN_UNACK, Trigger.ACK, S.NORMAL),
        (S.RTN_UNACK, Trigger.RAISE, S.ACTIVE_UNACK),
        (S.ACTIVE_UNACK, Trigger.SHELVE, S.SHELVED),
        (S.ACTIVE_ACK, Trigger.SHELVE, S.SHELVED),
        (S.SHELVED, Trigger.EXPIRE_ACTIVE, S.ACTIVE_UNACK),
        (S.SHELVED, Trigger.EXPIRE_NORMAL, S.NORMAL),
        (S.OUT_OF_SERVICE, Trigger.RETURN_TO_SERVICE, S.NORMAL),
    ],
)
def test_figure_6_transitions(state: AlertState, trigger: Trigger, target: AlertState) -> None:
    assert transition(state, trigger) is target


@pytest.mark.parametrize("state", [S.NORMAL, S.ACTIVE_UNACK, S.ACTIVE_ACK, S.RTN_UNACK, S.SHELVED])
def test_any_state_goes_out_of_service(state: AlertState) -> None:
    assert transition(state, Trigger.OUT_OF_SERVICE) is S.OUT_OF_SERVICE


@pytest.mark.parametrize(
    ("state", "trigger"),
    [
        (S.NORMAL, Trigger.ACK),
        (S.ACTIVE_ACK, Trigger.ACK),
        (S.NORMAL, Trigger.SHELVE),
        (S.RTN_UNACK, Trigger.SHELVE),
        (S.SHELVED, Trigger.ACK),
        (S.OUT_OF_SERVICE, Trigger.ACK),
        (S.ACTIVE_ACK, Trigger.RAISE),
    ],
)
def test_other_transitions_are_refused(state: AlertState, trigger: Trigger) -> None:
    with pytest.raises(AlertError, match=state.value):
        transition(state, trigger)


def test_every_transition_lands_on_a_known_state() -> None:
    assert set(TRANSITIONS.values()) <= set(AlertState)
    assert all(
        target is not S.SHELVED for (_, t), target in TRANSITIONS.items() if t is Trigger.ACK
    )


# ------------------------------------------------------------------ evaluation


def test_levels() -> None:
    rule = di_rule()
    assert [level_of(rule, v) for v in (14.9, 15, 24.9, 25)] == [0, 1, 1, 2]


def _decode(code: str) -> tuple[AlertState, Severity | None]:
    state, _, severity = code.partition(":")
    return CODES[state], {"W": Severity.WARNING, "A": Severity.ALERT, "": None}[severity]


@pytest.mark.parametrize(
    "case", json.loads(REFERENCE.read_text())["cases"], ids=lambda c: c["name"]
)
def test_reference_sequences(case: dict[str, Any]) -> None:
    steps = replay(
        di_rule(**case["rule"]),
        case["values"],
        START,
        acknowledge_at=case.get("acknowledge_at", ()),
    )
    expected = [_decode(code) for code in case["expect"]]
    # a code without a severity ("RU") checks the state only
    got = [
        (s.state, s.severity if code_severity is not None else None)
        for s, (_, code_severity) in zip(steps, expected, strict=True)
    ]
    assert got == expected


def test_memory_keeps_only_the_last_m_cycles() -> None:
    rule = di_rule()
    memory = RuleMemory()
    for i, value in enumerate([20, 20, 5, 5, 5, 5, 5]):
        memory = step(rule, memory, value, START + timedelta(minutes=i), None).memory
    assert memory.levels == (0, 0, 0, 0, 0)


# ------------------------------------------------------------------ properties


values = st.lists(st.floats(min_value=0, max_value=60, allow_nan=False), max_size=40)


@settings(max_examples=200, deadline=None)
@given(values, st.integers(1, 5), st.integers(0, 3))
def test_never_raises_with_fewer_than_n_exceedances_in_any_window(
    data: list[float], n: int, extra: int
) -> None:
    rule = di_rule(persistence_n=n, persistence_m=n + extra)
    steps = replay(rule, data, START)
    for i, s in enumerate(steps):
        if s.state is S.ACTIVE_UNACK and (i == 0 or steps[i - 1].state is S.NORMAL):
            window = data[max(0, i - rule.persistence_m + 1) : i + 1]
            assert sum(v >= rule.warning for v in window) >= n
            assert data[i] >= rule.warning


@settings(max_examples=200, deadline=None)
@given(values, st.floats(min_value=0, max_value=0.5))
def test_clears_only_after_enough_cycles_below_the_deadband(
    data: list[float], deadband: float
) -> None:
    rule = di_rule(deadband=deadband)
    threshold = rule.warning * (1 - deadband)
    steps = replay(rule, data, START)
    for i in range(1, len(steps)):
        if steps[i - 1].state is S.ACTIVE_UNACK and steps[i].state is S.RTN_UNACK:
            last = data[i - rule.clear_cycles + 1 : i + 1]
            assert len(last) == rule.clear_cycles
            assert all(v < threshold for v in last)


@settings(max_examples=200, deadline=None)
@given(values)
def test_severity_never_drops_while_active(data: list[float]) -> None:
    steps = replay(di_rule(), data, START)
    for before, after in itertools.pairwise(steps):
        if before.state is S.ACTIVE_UNACK and after.state is S.ACTIVE_UNACK:
            assert not (before.severity is Severity.ALERT and after.severity is Severity.WARNING)


def test_escalation_needs_a_new_acknowledgement() -> None:
    """An escalation from Warning to Alert returns an acknowledged alert to
    Active-Unacknowledged (decision 4.4, ISA-18.2)."""
    steps = replay(di_rule(), [20, 20, 20, 30, 30, 30], START, acknowledge_at=[3])
    assert [(s.state, s.severity) for s in steps[2:]] == [
        (S.ACTIVE_UNACK, Severity.WARNING),
        (S.ACTIVE_ACK, Severity.WARNING),
        (S.ACTIVE_ACK, Severity.WARNING),
        (S.ACTIVE_UNACK, Severity.ALERT),
    ]
