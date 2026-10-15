"""Registry services against PostgreSQL: hierarchy, moves, tags, roles, audit (UC-03)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from pmp.core import Actor, AuditLog, Database
from pmp.registry import (
    AssetLevel,
    AssetSpec,
    Change,
    Criticality,
    RegistryError,
    RoleSpec,
    TagSpec,
    find_tag,
    get_asset,
    list_ancestors,
    list_subtree,
    list_tags,
    move_asset,
    role_gaps,
    upsert_asset,
    upsert_asset_type,
    upsert_role,
    upsert_tag,
)

pytestmark = pytest.mark.integration
ACTOR = Actor.system()


def _plant(db: Database) -> None:
    """SITE-A > AREA-1 > UNIT-1 > EQ-1, plus SITE-B."""
    with db.session() as s:
        upsert_asset(s, ACTOR, AssetSpec("SITE-A", "Site A", AssetLevel.SITE))
        upsert_asset(s, ACTOR, AssetSpec("AREA-1", "Area 1", AssetLevel.AREA, "SITE-A"))
        upsert_asset(s, ACTOR, AssetSpec("UNIT-1", "Unit 1", AssetLevel.UNIT, "AREA-1"))
        upsert_asset(
            s,
            ACTOR,
            AssetSpec("EQ-1", "Pump 1", AssetLevel.EQUIPMENT, "UNIT-1", Criticality.A),
        )
        upsert_asset(s, ACTOR, AssetSpec("SITE-B", "Site B", AssetLevel.SITE))


def _tag(source_name: str, asset: str = "EQ-1", **overrides: object) -> TagSpec:
    values: dict[str, object] = {
        "source": "gw-1",
        "source_name": source_name,
        "asset_code": asset,
        "unit": "°C",
        "range_lo": 0.0,
        "range_hi": 150.0,
        "interval_s": 60,
    }
    values.update(overrides)
    return TagSpec(**values)  # type: ignore[arg-type]


def test_paths_follow_the_hierarchy(clean_registry: Database) -> None:
    _plant(clean_registry)
    with clean_registry.session() as s:
        site, area, unit, eq = (get_asset(s, c) for c in ("SITE-A", "AREA-1", "UNIT-1", "EQ-1"))
    assert eq.path == f"{site.id}.{area.id}.{unit.id}.{eq.id}"
    assert eq.depth == 4
    assert eq.parent_id == unit.id
    assert eq.criticality is Criticality.A


def test_subtree_and_ancestor_queries(clean_registry: Database) -> None:
    _plant(clean_registry)
    with clean_registry.session() as s:
        assert [a.code for a in list_subtree(s, "AREA-1")] == ["AREA-1", "UNIT-1", "EQ-1"]
        assert [a.code for a in list_ancestors(s, "EQ-1")] == ["SITE-A", "AREA-1", "UNIT-1"]
        assert len(list_subtree(s)) == 5


def test_move_rewrites_the_whole_subtree(clean_registry: Database) -> None:
    _plant(clean_registry)
    with clean_registry.session() as s:
        move_asset(s, ACTOR, "AREA-1", "SITE-B")
    with clean_registry.session() as s:
        site_b = get_asset(s, "SITE-B")
        assert [a.code for a in list_subtree(s, "SITE-A")] == ["SITE-A"]
        assert [a.code for a in list_subtree(s, "SITE-B")] == [
            "SITE-B",
            "AREA-1",
            "UNIT-1",
            "EQ-1",
        ]
        eq = get_asset(s, "EQ-1")
        assert eq.path.startswith(f"{site_b.id}.")
        assert get_asset(s, "AREA-1").parent_id == site_b.id


def test_cannot_move_an_asset_under_its_own_descendant(clean_registry: Database) -> None:
    _plant(clean_registry)
    with pytest.raises(RegistryError, match="descendants"), clean_registry.session() as s:
        move_asset(s, ACTOR, "AREA-1", "UNIT-1")


def test_level_rules_are_enforced(clean_registry: Database) -> None:
    _plant(clean_registry)
    with pytest.raises(RegistryError, match="cannot sit under"), clean_registry.session() as s:
        upsert_asset(s, ACTOR, AssetSpec("U-2", "Unit 2", AssetLevel.UNIT, "EQ-1"))
    with pytest.raises(RegistryError, match="needs a parent"), clean_registry.session() as s:
        upsert_asset(
            s, ACTOR, AssetSpec("EQ-9", "Loose", AssetLevel.EQUIPMENT, None, Criticality.C)
        )


def test_upsert_updates_instead_of_duplicating(clean_registry: Database) -> None:
    _plant(clean_registry)
    with clean_registry.session() as s:
        assert (
            upsert_asset(s, ACTOR, AssetSpec("UNIT-1", "Unit 1", AssetLevel.UNIT, "AREA-1"))
            is Change.UNCHANGED
        )
        assert (
            upsert_asset(s, ACTOR, AssetSpec("UNIT-1", "Unit One", AssetLevel.UNIT, "AREA-1"))
            is Change.UPDATED
        )
        assert get_asset(s, "UNIT-1").name == "Unit One"


def test_tag_is_unique_on_source_and_source_name(clean_registry: Database) -> None:
    _plant(clean_registry)
    with clean_registry.session() as s:
        assert upsert_tag(s, ACTOR, _tag("EQ1.TI1.PV")) is Change.CREATED
        assert upsert_tag(s, ACTOR, _tag("EQ1.TI1.PV", unit="degC")) is Change.UPDATED
        assert upsert_tag(s, ACTOR, _tag("EQ1.TI1.PV", source="gw-2")) is Change.CREATED
    with clean_registry.session() as s:
        assert len(list_tags(s, "EQ-1")) == 2
        tag = find_tag(s, "gw-1", "EQ1.TI1.PV")
        assert tag is not None
        assert tag.unit == "degC"
        assert tag.asset_code == "EQ-1"


def test_roles_are_mapped_and_gaps_reported(clean_registry: Database) -> None:
    with clean_registry.session() as s:
        upsert_asset_type(s, ACTOR, code="pump", name="Pump")
        upsert_role(s, ACTOR, "pump", RoleSpec("de_bearing_temp", "DE bearing temperature", "°C"))
        upsert_role(s, ACTOR, "pump", RoleSpec("flow", "Flow", "m³/h"))
        upsert_asset(s, ACTOR, AssetSpec("SITE-A", "Site A", AssetLevel.SITE))
        upsert_asset(
            s,
            ACTOR,
            AssetSpec("EQ-1", "Pump", AssetLevel.EQUIPMENT, "SITE-A", Criticality.B, "pump"),
        )
        upsert_tag(s, ACTOR, _tag("EQ1.TI1.PV"), role_code="de_bearing_temp")
    with clean_registry.session() as s:
        tag = find_tag(s, "gw-1", "EQ1.TI1.PV")
        assert tag is not None
        assert tag.role_code == "de_bearing_temp"
        assert list(role_gaps(s, "EQ-1")) == ["flow"]
    with pytest.raises(RegistryError, match="already filled"), clean_registry.session() as s:
        upsert_tag(s, ACTOR, _tag("EQ1.TI2.PV"), role_code="de_bearing_temp")
    with pytest.raises(RegistryError, match="has no role"), clean_registry.session() as s:
        upsert_tag(s, ACTOR, _tag("EQ1.TI3.PV"), role_code="speed")


def test_every_change_is_audited(clean_registry: Database) -> None:
    _plant(clean_registry)
    with clean_registry.session() as s:
        upsert_asset(s, ACTOR, AssetSpec("UNIT-1", "Unit One", AssetLevel.UNIT, "AREA-1"))
        move_asset(s, ACTOR, "UNIT-1", "SITE-B")
        upsert_asset(s, ACTOR, AssetSpec("UNIT-1", "Unit One", AssetLevel.UNIT, "SITE-B"))
        unit_id = str(get_asset(s, "UNIT-1").id)
    with clean_registry.session() as s:
        entries = s.scalars(
            select(AuditLog)
            .where(AuditLog.entity == "asset", AuditLog.entity_id == unit_id)
            .order_by(AuditLog.id)
        ).all()
        actions = [e.action for e in entries]
        assert actions[-3:] == ["create", "update", "move"]  # the unchanged upsert adds nothing
        update = entries[-2]
        assert update.before_after["before"]["name"] == "Unit 1"
        assert update.before_after["after"]["name"] == "Unit One"
        assert update.actor_type == "system"
