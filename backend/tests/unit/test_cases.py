"""Case rules (plan 8.4, UCS §6.9, Figure 7): every transition allowed and refused."""

from __future__ import annotations

import pytest

from pmp.cases import (
    TRANSITIONS,
    CaseConflictError,
    CaseError,
    CaseStatus,
    Outcome,
    case_number,
    check_closure,
    check_transition,
    highest_priority,
    safe_filename,
)

S = CaseStatus
FIGURE_7 = {
    (S.OPEN, S.INVESTIGATING),
    (S.OPEN, S.CANCELLED),
    (S.INVESTIGATING, S.ACTION_REQUIRED),
    (S.INVESTIGATING, S.MONITORING),
    (S.INVESTIGATING, S.CANCELLED),
    (S.ACTION_REQUIRED, S.MONITORING),
    (S.ACTION_REQUIRED, S.CLOSED),
    (S.MONITORING, S.ACTION_REQUIRED),
    (S.MONITORING, S.CLOSED),
}


def test_the_transitions_are_figure_7_edge_for_edge() -> None:
    assert {(a, b) for a, targets in TRANSITIONS.items() for b in targets} == FIGURE_7


@pytest.mark.parametrize("current", list(S))
@pytest.mark.parametrize("target", [s for s in S if s is not S.CLOSED])
def test_every_state_change_is_allowed_or_refused(current: S, target: S) -> None:
    def attempt() -> None:
        check_transition(current, target, assigned=True, open_actions=0, reason="duplicate")

    if (current, target) in FIGURE_7:
        attempt()
    else:
        with pytest.raises(CaseConflictError):
            attempt()


def test_conditions_on_the_edges() -> None:
    with pytest.raises(CaseError, match="Assign"):
        check_transition(S.OPEN, S.INVESTIGATING, assigned=False, open_actions=0, reason=None)
    with pytest.raises(CaseError, match="reason"):
        check_transition(S.OPEN, S.CANCELLED, assigned=False, open_actions=0, reason=" ")
    with pytest.raises(CaseError, match="open actions"):
        check_transition(
            S.ACTION_REQUIRED, S.MONITORING, assigned=True, open_actions=2, reason=None
        )
    with pytest.raises(CaseError, match="Close a case with its outcome"):
        check_transition(S.MONITORING, S.CLOSED, assigned=True, open_actions=0, reason=None)


def test_closure_needs_an_outcome_and_a_mode_for_a_true_finding() -> None:
    with pytest.raises(CaseError, match="outcome"):
        check_closure(S.MONITORING, None, None)
    with pytest.raises(CaseError, match="confirmed failure mode"):
        check_closure(S.MONITORING, Outcome.TRUE_FINDING, None)
    for state in (S.OPEN, S.INVESTIGATING, S.CLOSED, S.CANCELLED):
        with pytest.raises(CaseConflictError):
            check_closure(state, Outcome.FALSE_ALERT, None)
    check_closure(S.ACTION_REQUIRED, Outcome.TRUE_FINDING, 3)
    check_closure(S.MONITORING, Outcome.SENSOR_ISSUE, None)


def test_priority_numbers_and_file_names() -> None:
    assert highest_priority(["P3", None, "P2"]) == "P2"
    assert highest_priority([None]) == "P4"  # every alert out of service
    assert case_number(14) == "C-0014"
    assert safe_filename("C:\\temp\\..\\oil sample.pdf") == "oil sample.pdf"
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename('a"<>|.txt') == "a.txt"
    assert safe_filename("..") == "attachment"
