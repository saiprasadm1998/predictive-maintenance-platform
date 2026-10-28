"""Failure-mode signature matching (UCS §6.7.2, FR-DIA-02, -03): pure functions.

A failure mode has symptoms (role, expected direction d in up / down / any, weight w > 0).
For each symptom whose sensor is usable:

    g(z, d) = min(1, max(0, d·z / z_ref))   for d = up (+1) or down (-1)
    g(z, any) = min(1, |z| / z_ref)
    Match = 100 x Σ w·g / Σ w   over the symptoms with usable sensors

z_ref is the sensor's warning limit (default 3). Symptoms without a usable sensor are
"not evaluated" and left out of both sums; below half of the mode's total weight the
score is "insufficient evidence". The score ranks modes; it is not a probability.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

DEFAULT_Z_REF = 3.0
MATCH_AT, MAX_TASKS, MAX_SYMPTOMS = 0.5, 20, 30
_CODE = re.compile(r"[a-z0-9][a-z0-9_]{0,63}")


class LibraryError(ValueError):
    """A failure mode cannot be saved or used; the message is shown to the engineer."""


class Direction(StrEnum):
    UP = "up"
    DOWN = "down"
    ANY = "any"


class SymptomResult(StrEnum):
    MATCH = "match"  # g at least 0.5: the sensor moved as the mode expects
    PARTIAL = "partial"  # 0 < g < 0.5
    NO_MATCH = "no match"  # g = 0: no deviation, or the opposite direction
    NOT_EVALUATED = "not evaluated"  # no usable sensor for the role


@dataclass(frozen=True)
class Symptom:
    role: str
    direction: Direction
    weight: float


@dataclass(frozen=True)
class ModeSpec:
    """One version of a failure mode, as an engineer defines it (UC-16)."""

    code: str
    name: str
    symptoms: tuple[Symptom, ...]
    tasks: tuple[str, ...] = ()
    iso_code: str | None = None  # ISO 14224 failure mode, where one applies
    description: str = ""


def check_mode(spec: ModeSpec, roles: Sequence[str]) -> None:
    """Every problem at once (as the model definition checks do)."""
    problems: list[str] = []
    if not _CODE.fullmatch(spec.code):
        problems.append(
            "The code is lower-case letters, digits and underscores (at most 64), "
            "e.g. thrust_bearing_wear"
        )
    if not spec.name.strip():
        problems.append("The name is required")
    if not spec.symptoms:
        problems.append("Give at least one symptom")
    if len(spec.symptoms) > MAX_SYMPTOMS:
        problems.append(f"At most {MAX_SYMPTOMS} symptoms")
    seen: set[str] = set()
    for i, s in enumerate(spec.symptoms, start=1):
        if s.role not in roles:
            problems.append(f"Symptom {i}: the asset type has no role {s.role!r}")
        if s.role in seen:
            problems.append(f"Symptom {i}: role {s.role!r} is used twice")
        seen.add(s.role)
        if not s.weight > 0:
            problems.append(f"Symptom {i}: the weight must be above 0")
    if len(spec.tasks) > MAX_TASKS:
        problems.append(f"At most {MAX_TASKS} tasks")
    if any(not t.strip() for t in spec.tasks):
        problems.append("A task cannot be empty")
    if spec.iso_code is not None and len(spec.iso_code) > 32:
        problems.append("The ISO 14224 code has at most 32 characters")
    if problems:
        raise LibraryError("; ".join(problems))


def agreement(z: float, direction: Direction, z_ref: float = DEFAULT_Z_REF) -> float:
    """g(z, d) of UCS §6.7.2."""
    if direction is Direction.ANY:
        return min(1.0, abs(z) / z_ref)
    sign = 1.0 if direction is Direction.UP else -1.0
    return min(1.0, max(0.0, sign * z / z_ref))


@dataclass(frozen=True)
class Reading:
    """What a role's sensor shows at a cycle: z, whether it was usable, its z_ref."""

    z: float | None
    usable: bool
    z_ref: float = DEFAULT_Z_REF
    tag_id: int | None = None
    source_name: str | None = None


@dataclass(frozen=True)
class SymptomMatch:
    symptom: Symptom
    reading: Reading | None
    g: float | None
    result: SymptomResult


@dataclass(frozen=True)
class ModeMatch:
    spec: ModeSpec
    score: float | None  # 0 to 100; None when nothing could be evaluated
    insufficient: bool  # less than half the total weight evaluated
    evaluated_weight: float
    total_weight: float
    symptoms: tuple[SymptomMatch, ...]


def match_mode(spec: ModeSpec, readings: Mapping[str, Reading]) -> ModeMatch:
    """Match(f) of UCS §6.7.2 over the role readings of one cycle."""
    results = []
    weighted = evaluated = 0.0
    for s in spec.symptoms:
        reading = readings.get(s.role)
        if reading is None or not reading.usable or reading.z is None:
            results.append(SymptomMatch(s, reading, None, SymptomResult.NOT_EVALUATED))
            continue
        g = agreement(reading.z, s.direction, reading.z_ref)
        weighted += s.weight * g
        evaluated += s.weight
        result = (
            SymptomResult.MATCH
            if g >= MATCH_AT
            else SymptomResult.PARTIAL
            if g > 0
            else SymptomResult.NO_MATCH
        )
        results.append(SymptomMatch(s, reading, g, result))
    total = sum(s.weight for s in spec.symptoms)
    score = 100.0 * weighted / evaluated if evaluated > 0 else None
    return ModeMatch(spec, score, evaluated < total / 2, evaluated, total, tuple(results))


def rank(matches: Sequence[ModeMatch]) -> list[ModeMatch]:
    """Highest score first; insufficient evidence and unscored modes after the rest."""
    return sorted(
        matches,
        key=lambda m: (m.insufficient or m.score is None, -(m.score or 0.0), m.spec.name),
    )
