"""Registry import against PostgreSQL (FR-REG-03, plan 1.1 "Done when")."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from pmp.core import Actor, AuditLog, Database
from pmp.registry import (
    ImportReport,
    count_assets,
    get_asset,
    import_files,
    list_ancestors,
    list_tags,
    role_gaps,
)

pytestmark = pytest.mark.integration
ACTOR = Actor.system()
DEMO = Path(__file__).resolve().parents[3] / "data" / "demo" / "registry"
DEMO_CSVS = [DEMO / f"{name}.csv" for name in ("asset_types", "roles", "assets", "tags")]


def _import(db: Database, paths: list[Path], *, dry_run: bool = False) -> ImportReport:
    with db.session() as session:
        return import_files(session, ACTOR, paths, dry_run=dry_run)


def _audit_count(db: Database) -> int:
    with db.session() as session:
        return session.scalar(select(func.count()).select_from(AuditLog)) or 0


def test_demo_hierarchy_imports_from_csv(clean_registry: Database) -> None:
    report = _import(clean_registry, DEMO_CSVS)

    assert report.ok, report.summary()
    assert report.committed
    assert report.counts["assets"]["created"] == 16
    assert report.counts["tags"]["created"] == 60
    assert report.counts["asset_types"]["created"] == 6
    with clean_registry.session() as s:
        k101 = get_asset(s, "K-101")
        assert k101.asset_type_code == "centrifugal_compressor"
        assert [a.code for a in list_ancestors(s, "K-101")] == ["DEMO", "SITE-A", "SA-AMM"]
        assert len(list_tags(s, "K-101")) == 18
        assert list(role_gaps(s, "K-101")) == []  # all 18 roles filled
        assert "speed" not in role_gaps(s, "P-104A")
        assert len(role_gaps(s, "P-205")) == 4  # a small pump with only 4 of 8 sensors


def test_demo_hierarchy_imports_from_the_workbook(clean_registry: Database) -> None:
    report = _import(clean_registry, [DEMO / "registry.xlsx"])
    assert report.ok, report.summary()
    with clean_registry.session() as s:
        assert count_assets(s) == 16
        assert len(list_tags(s)) == 60


def test_reimporting_the_same_file_changes_nothing(clean_registry: Database) -> None:
    _import(clean_registry, DEMO_CSVS)
    audit_before = _audit_count(clean_registry)

    report = _import(clean_registry, [DEMO / "registry.xlsx"])

    assert report.ok, report.summary()
    assert report.counts["assets"]["unchanged"] == 16
    assert report.counts["tags"]["unchanged"] == 60
    assert _audit_count(clean_registry) == audit_before


def test_dry_run_validates_without_writing(clean_registry: Database) -> None:
    report = _import(clean_registry, DEMO_CSVS, dry_run=True)
    assert report.ok
    assert not report.committed
    with clean_registry.session() as s:
        assert count_assets(s) == 0


def test_bad_file_is_rejected_with_line_numbers_and_nothing_is_written(
    clean_registry: Database, tmp_path: Path
) -> None:
    (tmp_path / "assets.csv").write_text(
        "code,name,level,parent,criticality\n"
        "SITE-A,Site A,site,,\n"  # line 2: fine
        "U-1,Unit 1,plant,SITE-A,\n"  # line 3: unknown level
        "P-1,Pump 1,equipment,U-9,B\n"  # line 4: parent missing
        "P-2,Pump 2,equipment,SITE-A,\n"  # line 5: equipment without criticality
        "SITE-A,Again,site,,\n"  # line 6: duplicate code
    )
    (tmp_path / "tags.csv").write_text(
        "source,source_name,asset,unit,range_lo,range_hi,interval_s\n"
        "gw,T1,SITE-A,°C,150,0,60\n"  # line 2: range upside down
        "gw,T2,NOPE,°C,0,10,60\n"  # line 3: unknown asset
        "gw,T3,SITE-A,°C,zero,10,60\n"  # line 4: not a number
    )

    report = _import(clean_registry, [tmp_path / "assets.csv", tmp_path / "tags.csv"])

    assert not report.ok
    assert not report.committed
    found = {(p.sheet, p.line) for p in report.problems}
    assert {("assets", 3), ("assets", 4), ("assets", 5), ("assets", 6)} <= found
    assert {("tags", 2), ("tags", 3), ("tags", 4)} <= found
    assert ("assets", 2) not in found
    assert "line 3" in report.summary()
    with clean_registry.session() as s:
        assert count_assets(s) == 0  # SITE-A on line 2 was valid but nothing was written


def test_circular_parents_in_a_file_are_reported(clean_registry: Database, tmp_path: Path) -> None:
    (tmp_path / "assets.csv").write_text(
        "code,name,level,parent\nSITE-A,Site A,site,\nA-1,Area 1,area,A-2\nA-2,Area 2,area,A-1\n"
    )
    report = _import(clean_registry, [tmp_path / "assets.csv"])
    assert not report.ok


def test_five_hundred_assets_import(clean_registry: Database, tmp_path: Path) -> None:
    lines = ["code,name,level,parent,criticality", "SITE-X,Site X,site,,"]
    for u in range(20):
        lines.append(f"U-{u},Unit {u},unit,SITE-X,")
        lines += [f"E-{u}-{e},Equipment {u}-{e},equipment,U-{u},C" for e in range(24)]
    lines.append("E-EXTRA,Extra,equipment,U-0,A")
    (tmp_path / "assets.csv").write_text("\n".join(lines) + "\n")

    report = _import(clean_registry, [tmp_path / "assets.csv"])

    assert report.ok, report.summary()
    assert report.counts["assets"]["created"] == 502
    with clean_registry.session() as s:
        assert count_assets(s) == 502
        assert len(list_ancestors(s, "E-19-23")) == 2
