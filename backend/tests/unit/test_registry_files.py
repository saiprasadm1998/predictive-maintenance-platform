"""Reading registry files: CSV quirks and Excel workbooks (FR-REG-03)."""

from __future__ import annotations

import io
from pathlib import Path

from openpyxl import Workbook

from pmp.registry.importer import read_csv, read_files, read_workbook


def test_csv_lines_are_numbered_as_the_user_sees_them() -> None:
    rows = read_csv("assets", b"code,name,level\nSITE-A,Site A,site\n\nSA-AMM,Ammonia,unit\n")
    assert [(r.line, r.get("code")) for r in rows] == [(2, "SITE-A"), (4, "SA-AMM")]


def test_csv_from_excel_with_bom_and_semicolons() -> None:
    data = "﻿Code;Name;Level\nSITE-A;Site A;site\n".encode()
    rows = read_csv("assets", data)
    assert rows[0].get("code") == "SITE-A"
    assert rows[0].get("name") == "Site A"


def test_headers_are_normalised() -> None:
    rows = read_csv("tags", b"Source Name,Range Lo\nK101.TI1012.PV,0\n")
    assert set(rows[0].values) == {"source_name", "range_lo"}


def _workbook(sheets: dict[str, list[list[object]]]) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)  # type: ignore[arg-type]
    for name, rows in sheets.items():
        worksheet = workbook.create_sheet(name)
        for row in rows:
            worksheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_workbook_sheets_are_read_and_unknown_sheets_ignored() -> None:
    data = _workbook(
        {
            "assets": [["code", "name", "level"], ["SITE-A", "Site A", "site"]],
            "notes": [["anything"]],
        }
    )
    sheets = read_workbook(data)
    assert list(sheets) == ["assets"]
    assert sheets["assets"][0].get("code") == "SITE-A"


def test_whole_numbers_from_excel_are_not_written_as_floats() -> None:
    data = _workbook({"tags": [["interval_s", "range_hi"], [60, 150.5]]})
    row = read_workbook(data)["tags"][0]
    assert row.get("interval_s") == "60"
    assert row.get("range_hi") == "150.5"


def test_unknown_file_types_and_names_are_reported(tmp_path: Path) -> None:
    (tmp_path / "assets.txt").write_text("x")
    (tmp_path / "plants.csv").write_text("code\n")
    _, problems = read_files([tmp_path / "assets.txt", tmp_path / "plants.csv"])
    messages = [str(p) for p in problems]
    assert any("only .csv and .xlsx" in m for m in messages)
    assert any("unknown sheet" in m for m in messages)
