"""Case rules (UCS §6.9, Figure 7; UC-12, UC-13). Pure: no database."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # UCS §6.9: up to 20 MB each
MAX_TITLE = 200
MAX_TEXT = 10_000
PRIORITIES = ("P1", "P2", "P3", "P4")
DEFAULT_PRIORITY = "P4"  # no linked alert has a priority (all out of service)


class CaseError(ValueError):
    pass


class CaseConflictError(CaseError):
    """The request conflicts with the current state (HTTP 409)."""


class CaseStatus(StrEnum):
    OPEN = "Open"
    INVESTIGATING = "Investigating"
    ACTION_REQUIRED = "Action required"
    MONITORING = "Monitoring"
    CLOSED = "Closed"
    CANCELLED = "Cancelled"

    @property
    def is_open(self) -> bool:
        return self not in (CaseStatus.CLOSED, CaseStatus.CANCELLED)


S = CaseStatus
# UCS Figure 7, edge for edge. Closing is its own operation (an outcome is needed).
TRANSITIONS: dict[CaseStatus, frozenset[CaseStatus]] = {
    S.OPEN: frozenset({S.INVESTIGATING, S.CANCELLED}),
    S.INVESTIGATING: frozenset({S.ACTION_REQUIRED, S.MONITORING, S.CANCELLED}),
    S.ACTION_REQUIRED: frozenset({S.MONITORING, S.CLOSED}),
    S.MONITORING: frozenset({S.ACTION_REQUIRED, S.CLOSED}),
    S.CLOSED: frozenset(),
    S.CANCELLED: frozenset(),
}
CLOSABLE = frozenset({S.ACTION_REQUIRED, S.MONITORING})  # UC-13 precondition


class Outcome(StrEnum):
    TRUE_FINDING = "true_finding"
    FALSE_ALERT = "false_alert"
    SENSOR_ISSUE = "sensor_issue"
    KNOWN_CONDITION = "known_condition"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").capitalize()


class ActivityType(StrEnum):
    CREATED = "created"
    COMMENT = "comment"
    ATTACHMENT = "attachment"
    ACTION = "action"
    STATE_CHANGE = "state_change"
    ASSIGNMENT = "assignment"
    UPDATE = "update"  # title, priority or due date
    LINK = "link"  # alerts added to the case
    CLOSURE = "closure"


class ActionStatus(StrEnum):
    OPEN = "open"
    DONE = "done"


def check_transition(
    current: CaseStatus,
    target: CaseStatus,
    *,
    assigned: bool,
    open_actions: int,
    reason: str | None,
) -> None:
    """Refuse a state change Figure 7 does not allow, or whose condition is not met."""
    if target is S.CLOSED:
        raise CaseError("Close a case with its outcome (Close case)")
    if target not in TRANSITIONS[current]:
        raise CaseConflictError(f"A case cannot go from {current} to {target}")
    if target is S.INVESTIGATING and not assigned:
        raise CaseError("Assign the case before investigating it")
    if target is S.CANCELLED and not (reason or "").strip():
        raise CaseError("Give the reason for cancelling (duplicate or invalid)")
    if current is S.ACTION_REQUIRED and target is S.MONITORING and open_actions:
        raise CaseError(f"Complete the open actions first ({open_actions} open)")


def check_closure(current: CaseStatus, outcome: Outcome | None, confirmed_mode: int | None) -> None:
    """UC-13 and UCS §6.9: outcome mandatory, a confirmed mode for a true finding."""
    if current not in CLOSABLE:
        raise CaseConflictError(
            f"Only a case in Action required or Monitoring can be closed (this one is {current})"
        )
    if outcome is None:
        raise CaseError("Record the outcome to close the case")
    if outcome is Outcome.TRUE_FINDING and confirmed_mode is None:
        raise CaseError("Choose the confirmed failure mode for a true finding")


def highest_priority(priorities: Iterable[str | None]) -> str:
    """The highest linked-alert priority (P1 highest); out-of-service alerts have none."""
    known = sorted(p for p in priorities if p in PRIORITIES)
    return known[0] if known else DEFAULT_PRIORITY


def case_number(case_id: int) -> str:
    return f"C-{case_id:04d}"


def clean_text(text: str | None, what: str, limit: int = MAX_TEXT, required: bool = True) -> str:
    value = (text or "").strip()
    if required and not value:
        raise CaseError(f"Give the {what}")
    if len(value) > limit:
        raise CaseError(f"The {what} may have at most {limit} characters")
    return value
