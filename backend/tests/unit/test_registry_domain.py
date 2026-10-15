"""Registry rules that need no database (FR-REG-01, -02)."""

from __future__ import annotations

import math

import pytest

from pmp.registry import AssetLevel, Criticality, RegistryError, TagSpec
from pmp.registry.domain import (
    check_code,
    check_criticality,
    check_parent_level,
    check_role_code,
    is_descendant_path,
)


def _tag(**overrides: object) -> TagSpec:
    values: dict[str, object] = {
        "source": "gw-site-a-01",
        "source_name": "K101.TI1012.PV",
        "asset_code": "K-101",
        "unit": "°C",
        "range_lo": 0.0,
        "range_hi": 150.0,
        "interval_s": 60,
    }
    values.update(overrides)
    return TagSpec(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("level", "parent"),
    [
        (AssetLevel.SITE, AssetLevel.ENTERPRISE),
        (AssetLevel.UNIT, AssetLevel.SITE),  # skipping the area level is allowed
        (AssetLevel.EQUIPMENT, AssetLevel.UNIT),
        (AssetLevel.EQUIPMENT, AssetLevel.AREA),
        (AssetLevel.ENTERPRISE, None),
        (AssetLevel.SITE, None),
    ],
)
def test_valid_parent_levels(level: AssetLevel, parent: AssetLevel | None) -> None:
    check_parent_level(level, parent)


@pytest.mark.parametrize(
    ("level", "parent"),
    [
        (AssetLevel.UNIT, AssetLevel.UNIT),  # same level
        (AssetLevel.SITE, AssetLevel.UNIT),  # upside down
        (AssetLevel.EQUIPMENT, None),  # equipment cannot be at the top
        (AssetLevel.UNIT, None),
    ],
)
def test_invalid_parent_levels(level: AssetLevel, parent: AssetLevel | None) -> None:
    with pytest.raises(RegistryError):
        check_parent_level(level, parent)


def test_levels_and_criticality_parse_case_insensitively() -> None:
    assert AssetLevel.parse(" Equipment ") is AssetLevel.EQUIPMENT
    assert Criticality.parse("b") is Criticality.B
    with pytest.raises(RegistryError, match="Unknown level"):
        AssetLevel.parse("plant")
    with pytest.raises(RegistryError, match="Unknown criticality"):
        Criticality.parse("D")


def test_equipment_needs_criticality_but_units_do_not() -> None:
    with pytest.raises(RegistryError, match="criticality"):
        check_criticality(AssetLevel.EQUIPMENT, None)
    check_criticality(AssetLevel.UNIT, None)
    check_criticality(AssetLevel.EQUIPMENT, Criticality.A)


@pytest.mark.parametrize("code", ["K-101", "SITE-A", "P_104.A", "E110"])
def test_valid_codes(code: str) -> None:
    assert check_code(code) == code


@pytest.mark.parametrize("code", ["", "-K101", "K 101", "K/101", "x" * 65])
def test_invalid_codes(code: str) -> None:
    with pytest.raises(RegistryError):
        check_code(code)


def test_role_codes_are_snake_case() -> None:
    assert check_role_code("de_bearing_temp") == "de_bearing_temp"
    for bad in ("DE bearing", "1st_bearing", "de-bearing"):
        with pytest.raises(RegistryError):
            check_role_code(bad)


def test_valid_tag_is_trimmed() -> None:
    tag = _tag(source=" gw-site-a-01 ", unit=" °C ", description="  DE bearing ").validated()
    assert tag.source == "gw-site-a-01"
    assert tag.unit == "°C"
    assert tag.description == "DE bearing"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"range_lo": 150.0, "range_hi": 0.0}, "must be below"),
        ({"range_lo": 10.0, "range_hi": 10.0}, "must be below"),
        ({"range_hi": math.inf}, "finite"),
        ({"interval_s": 0}, "positive"),
        ({"unit": " "}, "unit is required"),
        ({"source": ""}, "source is required"),
        ({"source_name": ""}, "source name is required"),
    ],
)
def test_invalid_tags_are_rejected(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(RegistryError, match=message):
        _tag(**overrides).validated()


def test_descendant_paths() -> None:
    assert is_descendant_path("1.4.17", "1.4")
    assert is_descendant_path("1.4", "1.4")
    assert not is_descendant_path("1.40", "1.4")  # label boundary, not string prefix
    assert not is_descendant_path("1", "1.4")
