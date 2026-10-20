"""Alert evaluation and the alert state model (UCS §6.6 and Figure 6, FR-ALM-01, -02).

Pure logic, no database. Each cycle a rule's value (DI in %, or a sensor's |z|) is
classed as below the warning limit, at warning or at alert level, and kept in the rule's
memory for its last m evaluated cycles.

- Raise: the condition (warning level or above) holds in n of the last m evaluated cycles
  (default 3 of 5), now, and for at least the on-delay (default 0 s). The new alert's
  severity is Alert if the alert level itself holds in n of the last m, else Warning.
- Escalate: an active Warning alert becomes Alert when the alert level holds in n of m.
  It is the same alert (UCS §6.6). Severity never drops while the alert is active
  (implementation plan, decision for 4.2).
- Clear: the value stays below the warning limit x (1 - deadband) for k consecutive
  evaluated cycles (default 10 % for 5).

Cycles where the rule is not evaluated (insufficient data, not in the operating mode, an
excluded sensor) leave the memory unchanged: they neither count for nor against.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from pmp.alerting.domain import AlertRuleSpec


class AlertError(ValueError):
    """An alert action that is not allowed in the alert's state."""


class AlertState(StrEnum):
    NORMAL = "Normal"
    ACTIVE_UNACK = "Active-Unacknowledged"
    ACTIVE_ACK = "Active-Acknowledged"
    RTN_UNACK = "RTN-Unacknowledged"
    SHELVED = "Shelved"
    OUT_OF_SERVICE = "Out of service"


class Severity(StrEnum):
    WARNING = "Warning"
    ALERT = "Alert"


class Trigger(StrEnum):
    RAISE = "raise"  # condition persistent (also re-activates an RTN-unacknowledged alert)
    ESCALATE = "escalate"  # Warning -> Alert on the same alert: to be acknowledged again
    CLEAR = "clear"  # condition returned to normal
    ACK = "acknowledge"
    SHELVE = "shelve"
    EXPIRE_ACTIVE = "unshelve_active"  # shelf ended (expiry or unshelve), condition true
    EXPIRE_NORMAL = "unshelve_normal"  # shelf ended, condition false
    OUT_OF_SERVICE = "out_of_service"  # model paused or retired
    RETURN_TO_SERVICE = "return_to_service"  # model resumed or redeployed


S = AlertState
_ANY_OPEN = (S.ACTIVE_UNACK, S.ACTIVE_ACK, S.RTN_UNACK, S.SHELVED)
TRANSITIONS: dict[tuple[AlertState, Trigger], AlertState] = {
    (S.NORMAL, Trigger.RAISE): S.ACTIVE_UNACK,
    (S.RTN_UNACK, Trigger.RAISE): S.ACTIVE_UNACK,
    (S.ACTIVE_UNACK, Trigger.ACK): S.ACTIVE_ACK,
    (S.ACTIVE_UNACK, Trigger.CLEAR): S.RTN_UNACK,
    (S.RTN_UNACK, Trigger.ACK): S.NORMAL,
    (S.ACTIVE_ACK, Trigger.CLEAR): S.NORMAL,
    (S.ACTIVE_UNACK, Trigger.SHELVE): S.SHELVED,
    (S.ACTIVE_ACK, Trigger.SHELVE): S.SHELVED,
    (S.SHELVED, Trigger.EXPIRE_ACTIVE): S.ACTIVE_UNACK,
    (S.SHELVED, Trigger.EXPIRE_NORMAL): S.NORMAL,
    (S.ACTIVE_UNACK, Trigger.ESCALATE): S.ACTIVE_UNACK,
    (S.ACTIVE_ACK, Trigger.ESCALATE): S.ACTIVE_UNACK,
    (S.SHELVED, Trigger.ESCALATE): S.SHELVED,
    # Figure 6: "Normal --> OutOfService: model paused"; any state moves there
    **{(state, Trigger.OUT_OF_SERVICE): S.OUT_OF_SERVICE for state in (S.NORMAL, *_ANY_OPEN)},
    (S.OUT_OF_SERVICE, Trigger.RETURN_TO_SERVICE): S.NORMAL,
}


def transition(state: AlertState, trigger: Trigger) -> AlertState:
    """The next state, or AlertError naming the state the alert is in."""
    target = TRANSITIONS.get((state, trigger))
    if target is None:
        raise AlertError(f"Cannot {trigger.value.replace('_', ' ')} an alert that is {state.value}")
    return target


# ------------------------------------------------------------------ evaluation


@dataclass(frozen=True)
class RuleMemory:
    """What a rule remembers between cycles (stored per rule, survives restarts)."""

    levels: tuple[int, ...] = ()  # last m evaluated cycles: 0 normal, 1 warning, 2 alert
    clear_count: int = 0  # consecutive evaluated cycles below the clearing threshold
    condition_since: datetime | None = None  # start of the current run at warning or above


@dataclass(frozen=True)
class StepResult:
    memory: RuleMemory
    level: int  # this cycle: 0, 1 or 2
    raise_to: Severity | None  # raise (if inactive) or escalate (if active) to this severity
    cleared: bool  # an active condition returned to normal


def level_of(spec: AlertRuleSpec, value: float) -> int:
    if value >= spec.alert:
        return 2
    if value >= spec.warning:
        return 1
    return 0


def step(
    spec: AlertRuleSpec,
    memory: RuleMemory,
    value: float,
    ts: datetime,
    active: Severity | None,
) -> StepResult:
    """One evaluated cycle. `active` is the severity of the rule's alert while its
    condition is active (also while shelved), or None."""
    level = level_of(spec, value)
    levels = (*memory.levels, level)[-spec.persistence_m :]
    since = (memory.condition_since or ts) if level > 0 else None

    def persistent(at_least: int) -> bool:
        return sum(1 for x in levels if x >= at_least) >= spec.persistence_n

    delay_ok = since is not None and ts - since >= timedelta(seconds=spec.on_delay_s)

    if active is None:
        raise_to = None
        if level > 0 and delay_ok and persistent(1):
            raise_to = Severity.ALERT if persistent(2) else Severity.WARNING
        return StepResult(RuleMemory(levels, 0, since), level, raise_to, False)

    escalate = Severity.ALERT if active is Severity.WARNING and persistent(2) and delay_ok else None
    below = value < spec.warning * (1 - spec.deadband)
    clear_count = memory.clear_count + 1 if below else 0
    if clear_count >= spec.clear_cycles:
        return StepResult(RuleMemory(), level, None, True)
    return StepResult(RuleMemory(levels, clear_count, since), level, escalate, False)


# ------------------------------------------------------------------ replay (tests, 9.2)


@dataclass(frozen=True)
class ReplayStep:
    state: AlertState
    severity: Severity | None


def replay(
    spec: AlertRuleSpec,
    values: Sequence[float | None],
    start: datetime,
    cycle_s: int = 60,
    acknowledge_at: Sequence[int] = (),
) -> list[ReplayStep]:
    """Run one rule over a value sequence (None: not evaluated that cycle) with no shelving
    or out-of-service, acknowledging after the cycles listed. Returns the alert's state and
    severity after each cycle."""
    memory = RuleMemory()
    state, severity, condition_active = AlertState.NORMAL, None, False
    out: list[ReplayStep] = []
    for i, value in enumerate(values):
        ts = start + timedelta(seconds=cycle_s * i)
        if value is not None:
            result = step(spec, memory, value, ts, severity if condition_active else None)
            memory = result.memory
            if result.raise_to is not None:
                if not condition_active:
                    state = transition(state, Trigger.RAISE)
                    condition_active = True
                elif result.raise_to is not severity:
                    state = transition(state, Trigger.ESCALATE)
                severity = result.raise_to
            elif result.cleared:
                state = transition(state, Trigger.CLEAR)
                condition_active = False
        if i in acknowledge_at and state in (AlertState.ACTIVE_UNACK, AlertState.RTN_UNACK):
            state = transition(state, Trigger.ACK)
        if state is AlertState.NORMAL:
            severity = None
        out.append(ReplayStep(state, severity))
    return out
