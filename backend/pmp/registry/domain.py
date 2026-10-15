"""Registry domain rules (UC-03, FR-REG-01 to -04). No database or framework imports.

The asset hierarchy follows ISA-95 / IEC 62264: Enterprise > Site > Area > Unit >
Equipment. Depth is variable: a child must sit at a lower level than its parent, but
levels may be skipped (the wireframes go Site > Unit > Equipment).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import IntEnum, StrEnum


class RegistryError(Exception):
    """A registry rule was broken. The message is written for the end user."""


class AssetLevel(IntEnum):
    ENTERPRISE = 1
    SITE = 2
    AREA = 3
    UNIT = 4
    EQUIPMENT = 5

    @property
    def label(self) -> str:
        return self.name.lower()

    @classmethod
    def parse(cls, value: str) -> AssetLevel:
        try:
            return cls[value.strip().upper()]
        except KeyError:
            allowed = ", ".join(level.label for level in cls)
            raise RegistryError(f"Unknown level {value!r}; use one of: {allowed}") from None


ROOT_LEVELS = frozenset({AssetLevel.ENTERPRISE, AssetLevel.SITE})


class Criticality(StrEnum):
    """Asset criticality class; drives alert priority from Phase 4 (UCS §6.6)."""

    A = "A"  # critical
    B = "B"  # important
    C = "C"  # other

    @classmethod
    def parse(cls, value: str) -> Criticality:
        try:
            return cls(value.strip().upper())
        except ValueError:
            raise RegistryError(f"Unknown criticality {value!r}; use A, B or C") from None


_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ROLE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def check_code(code: str, what: str = "Code") -> str:
    """Asset and asset-type codes: letters, digits, '.', '_' and '-', up to 64 characters."""
    code = code.strip()
    if not _CODE.match(code):
        raise RegistryError(
            f"{what} {code!r} is invalid: use letters, digits, '.', '_' or '-' "
            "(up to 64 characters, starting with a letter or digit)"
        )
    return code


def check_role_code(code: str) -> str:
    """Role codes are snake_case, e.g. de_bearing_temp."""
    code = code.strip()
    if not _ROLE_CODE.match(code):
        raise RegistryError(
            f"Role code {code!r} is invalid: use lower-case letters, digits and '_', "
            "starting with a letter"
        )
    return code


def check_name(name: str, what: str = "Name") -> str:
    name = name.strip()
    if not name:
        raise RegistryError(f"{what} is required")
    if len(name) > 200:
        raise RegistryError(f"{what} is longer than 200 characters")
    return name


def check_parent_level(level: AssetLevel, parent_level: AssetLevel | None) -> None:
    """A child sits below its parent; a root must be an enterprise or a site."""
    if parent_level is None:
        if level not in ROOT_LEVELS:
            raise RegistryError(
                f"A {level.label} needs a parent; only an enterprise or a site can be at the top"
            )
        return
    if level <= parent_level:
        raise RegistryError(
            f"A {level.label} cannot sit under a {parent_level.label}; "
            "the child must be at a lower level (enterprise > site > area > unit > equipment)"
        )


def check_criticality(level: AssetLevel, criticality: Criticality | None) -> None:
    """Equipment must have a criticality class (FR-REG-01); higher levels may omit it."""
    if level is AssetLevel.EQUIPMENT and criticality is None:
        raise RegistryError("Equipment needs a criticality class (A, B or C)")


@dataclass(frozen=True)
class TagSpec:
    """The editable fields of a tag (FR-REG-02)."""

    source: str
    source_name: str
    asset_code: str
    unit: str
    range_lo: float
    range_hi: float
    interval_s: int
    description: str = ""

    def validated(self) -> TagSpec:
        source = self.source.strip()
        source_name = self.source_name.strip()
        unit = self.unit.strip()
        if not source:
            raise RegistryError("Tag source is required")
        if not source_name:
            raise RegistryError("Tag source name is required")
        if len(source) > 100 or len(source_name) > 200:
            raise RegistryError("Tag source (100) or source name (200) is too long")
        if not unit:
            raise RegistryError("Tag unit is required")
        for name, value in (("range_lo", self.range_lo), ("range_hi", self.range_hi)):
            if not math.isfinite(value):
                raise RegistryError(f"Tag {name} must be a finite number")
        if self.range_lo >= self.range_hi:
            raise RegistryError(
                f"Tag range_lo ({self.range_lo:g}) must be below range_hi ({self.range_hi:g})"
            )
        if self.interval_s <= 0:
            raise RegistryError("Tag sampling interval must be a positive number of seconds")
        return TagSpec(
            source=source,
            source_name=source_name,
            asset_code=self.asset_code.strip(),
            unit=unit,
            range_lo=self.range_lo,
            range_hi=self.range_hi,
            interval_s=self.interval_s,
            description=self.description.strip(),
        )


def is_descendant_path(candidate: str, ancestor: str) -> bool:
    """True if ltree path `candidate` equals `ancestor` or lies beneath it."""
    return candidate == ancestor or candidate.startswith(ancestor + ".")
