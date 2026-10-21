"""Build the demo plant registry used for development and demos (plan sub-phase 1.1).

Assets, tags and roles follow the PMP-PDS-001 wireframes (Site A > Ammonia unit >
Syngas compressor K-101 with 18 sensors, BFW pumps P-104A/B, Urea unit with K-201,
P-202 and P-205, Utilities with E-110, and Site B with cooling-tower fan F-3).
Tag names marked "wireframe" appear in the wireframes; the rest are typical sensors
for that kind of equipment, chosen for the demo.

Writes data/demo/registry/{asset_types,roles,assets,tags}.csv and registry.xlsx.
Run:  cd backend && uv run python tools/build_demo_registry.py
"""

from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).resolve().parents[2] / "data" / "demo" / "registry"

ASSET_TYPES = [
    ("centrifugal_compressor", "Centrifugal compressor", "Single-shaft centrifugal compressor"),
    ("reciprocating_compressor", "Reciprocating compressor", "Crosshead reciprocating compressor"),
    ("centrifugal_pump", "Centrifugal pump", "Motor-driven centrifugal pump"),
    ("plunger_pump", "Plunger pump", "High-pressure plunger pump"),
    ("waste_heat_boiler", "Waste-heat boiler", "Waste-heat boiler with steam drum"),
    ("fan", "Fan", "Motor-driven fan with gearbox"),
]

# role code, role name, unit, instrument range (lo, hi)
ROLES: dict[str, list[tuple[str, str, str, float, float]]] = {
    "centrifugal_compressor": [
        ("motor_current", "Motor current", "A", 0, 400),
        ("discharge_pressure", "Discharge pressure", "barg", 0, 250),
        ("suction_pressure", "Suction pressure", "barg", 0, 100),
        ("suction_temp", "Suction temperature", "°C", 0, 100),
        ("discharge_temp", "Discharge temperature", "°C", 0, 250),
        ("suction_flow", "Suction flow", "kNm³/h", 0, 200),
        ("speed", "Shaft speed", "rpm", 0, 15000),
        ("de_bearing_temp", "Drive-end bearing temperature", "°C", 0, 150),
        ("nde_bearing_temp", "Non-drive-end bearing temperature", "°C", 0, 150),
        ("thrust_pad_temp", "Thrust pad temperature", "°C", 0, 150),
        ("axial_displacement", "Axial displacement", "µm", 0, 1000),
        ("de_vibration_x", "Drive-end shaft vibration X", "µm", 0, 200),
        ("de_vibration_y", "Drive-end shaft vibration Y", "µm", 0, 200),
        ("nde_vibration_x", "Non-drive-end shaft vibration X", "µm", 0, 200),
        ("nde_vibration_y", "Non-drive-end shaft vibration Y", "µm", 0, 200),
        ("lube_oil_supply_temp", "Lube oil supply temperature", "°C", 0, 100),
        ("lube_oil_pressure", "Lube oil supply pressure", "barg", 0, 10),
        ("seal_gas_dp", "Seal gas differential pressure", "bar", 0, 10),
    ],
    "reciprocating_compressor": [
        ("motor_current", "Motor current", "A", 0, 600),
        ("suction_pressure", "Suction pressure", "barg", 0, 50),
        ("discharge_pressure", "Discharge pressure", "barg", 0, 200),
        ("suction_flow", "Suction flow", "t/h", 0, 120),
        ("discharge_temp", "Discharge temperature", "°C", 0, 250),
        ("crosshead_vibration", "Crosshead vibration", "mm/s", 0, 50),
        ("rod_drop", "Rod drop", "µm", 0, 1000),
        ("main_bearing_temp", "Main bearing temperature", "°C", 0, 150),
    ],
    "centrifugal_pump": [
        ("motor_current", "Motor current", "A", 0, 300),
        ("suction_pressure", "Suction pressure", "barg", 0, 40),
        ("discharge_pressure", "Discharge pressure", "barg", 0, 160),
        ("flow", "Flow", "m³/h", 0, 400),
        ("de_bearing_temp", "Drive-end bearing temperature", "°C", 0, 150),
        ("nde_bearing_temp", "Non-drive-end bearing temperature", "°C", 0, 150),
        ("de_vibration", "Drive-end bearing vibration", "mm/s", 0, 25),
        ("nde_vibration", "Non-drive-end bearing vibration", "mm/s", 0, 25),
    ],
    "plunger_pump": [
        ("motor_current", "Motor current", "A", 0, 300),
        ("suction_pressure", "Suction pressure", "barg", 0, 40),
        ("discharge_pressure", "Discharge pressure", "barg", 0, 250),
        ("flow", "Flow", "m³/h", 0, 100),
        ("crankcase_temp", "Crankcase oil temperature", "°C", 0, 120),
        ("frame_vibration", "Frame vibration", "mm/s", 0, 50),
    ],
    "waste_heat_boiler": [
        ("gas_inlet_temp", "Flue gas inlet temperature", "°C", 0, 1200),
        ("gas_outlet_temp", "Flue gas outlet temperature", "°C", 0, 600),
        ("steam_pressure", "Steam drum pressure", "barg", 0, 150),
        ("steam_flow", "Steam flow", "t/h", 0, 200),
        ("drum_level", "Steam drum level", "%", 0, 100),
    ],
    "fan": [
        ("motor_current", "Motor current", "A", 0, 200),
        ("gearbox_vibration", "Gearbox vibration", "mm/s", 0, 25),
        ("speed", "Fan speed", "rpm", 0, 300),
    ],
}

# code, name, level, parent, criticality, asset type, description
ASSETS = [
    ("DEMO", "Demo enterprise", "enterprise", "", "", "", "Demonstration plant for PMP"),
    ("SITE-A", "Site A", "site", "DEMO", "", "", "Ammonia and urea complex"),
    ("SA-AMM", "Ammonia unit", "unit", "SITE-A", "", "", ""),
    ("K-101", "Syngas compressor K-101", "equipment", "SA-AMM", "A", "centrifugal_compressor", ""),
    (
        "P-104A",
        "BFW pump P-104A",
        "equipment",
        "SA-AMM",
        "B",
        "centrifugal_pump",
        "Boiler feed water",
    ),
    (
        "P-104B",
        "BFW pump P-104B",
        "equipment",
        "SA-AMM",
        "B",
        "centrifugal_pump",
        "Boiler feed water",
    ),
    ("SA-UREA", "Urea unit", "unit", "SITE-A", "", "", ""),
    ("K-201", "CO₂ compressor K-201", "equipment", "SA-UREA", "B", "reciprocating_compressor", ""),
    ("P-202", "Carbamate pump P-202", "equipment", "SA-UREA", "B", "plunger_pump", ""),
    ("P-205", "Condensate pump P-205", "equipment", "SA-UREA", "C", "centrifugal_pump", ""),
    ("SA-UTIL", "Utilities", "unit", "SITE-A", "", "", ""),
    ("E-110", "Waste-heat boiler E-110", "equipment", "SA-UTIL", "B", "waste_heat_boiler", ""),
    ("SITE-B", "Site B", "site", "DEMO", "", "", ""),
    ("SB-NORTH", "North area", "area", "SITE-B", "", "", ""),
    ("SB-UTIL", "Utilities", "unit", "SB-NORTH", "", "", ""),
    ("F-3", "Cooling-tower fan F-3", "equipment", "SB-UTIL", "B", "fan", ""),
]

# asset, gateway source, [(instrument tag, role)]
TAGS: list[tuple[str, str, list[tuple[str, str]]]] = [
    (
        "K-101",
        "gw-site-a-01",
        [
            ("II-1001", "motor_current"),  # wireframe (operating-mode filter)
            ("PI-1002", "discharge_pressure"),  # wireframe
            ("PI-1001", "suction_pressure"),
            ("TI-1001", "suction_temp"),
            ("TI-1002", "discharge_temp"),
            ("FI-1001", "suction_flow"),
            ("SI-1001", "speed"),
            ("TI-1012", "de_bearing_temp"),  # wireframe
            ("TI-1018", "nde_bearing_temp"),  # wireframe (flatline)
            ("TI-1016", "thrust_pad_temp"),  # wireframe 04 symptom
            ("ZI-1015", "axial_displacement"),  # wireframe
            ("VI-1011X", "de_vibration_x"),
            ("VI-1011Y", "de_vibration_y"),
            ("VI-1017X", "nde_vibration_x"),
            ("VI-1017Y", "nde_vibration_y"),
            ("TI-1030", "lube_oil_supply_temp"),  # wireframe
            ("PI-1031", "lube_oil_pressure"),
            ("PDI-1040", "seal_gas_dp"),
        ],
    ),
    (
        "P-104A",
        "gw-site-a-01",
        [
            ("II-1043", "motor_current"),
            ("PI-1041", "suction_pressure"),
            ("PI-1040", "discharge_pressure"),  # wireframe 07 (above range)
            ("FI-1042", "flow"),
            ("TI-1044", "de_bearing_temp"),
            ("TI-1045", "nde_bearing_temp"),
            ("VI-1046", "de_vibration"),
            ("VI-1047", "nde_vibration"),
        ],
    ),
    (
        "P-104B",
        "gw-site-a-01",
        [
            ("II-1053", "motor_current"),
            ("PI-1051", "suction_pressure"),
            ("PI-1050", "discharge_pressure"),
            ("FI-1052", "flow"),
            ("TI-1054", "de_bearing_temp"),
            ("TI-1055", "nde_bearing_temp"),
            ("VI-1056", "de_vibration"),
            ("VI-1057", "nde_vibration"),
        ],
    ),
    (
        "K-201",
        "gw-site-a-01",
        [
            ("II-2001", "motor_current"),
            ("PI-2001", "suction_pressure"),
            ("PI-2002", "discharge_pressure"),
            ("FI-2203", "suction_flow"),  # wireframe 07 (stale)
            ("TI-2041", "discharge_temp"),  # wireframe 01 (flatline)
            ("VI-2010", "crosshead_vibration"),  # wireframe 07 (manual exclusion)
            ("ZI-2011", "rod_drop"),
            ("TI-2012", "main_bearing_temp"),
        ],
    ),
    (
        "P-202",
        "gw-site-a-01",
        [
            ("II-2023", "motor_current"),
            ("PI-2026", "suction_pressure"),
            ("PI-2021", "discharge_pressure"),
            ("FI-2022", "flow"),
            ("TI-2024", "crankcase_temp"),
            ("VI-2025", "frame_vibration"),
        ],
    ),
    (
        "P-205",
        "gw-site-a-01",
        [
            ("II-2053", "motor_current"),
            ("PI-2051", "discharge_pressure"),
            ("FI-2052", "flow"),
            ("TI-2054", "de_bearing_temp"),
        ],
    ),
    (
        "E-110",
        "gw-site-a-01",
        [
            ("TI-3004", "gas_inlet_temp"),
            ("TI-3005", "gas_outlet_temp"),  # wireframe 07 (spikes)
            ("PI-3006", "steam_pressure"),
            ("FI-3007", "steam_flow"),
            ("LI-3008", "drum_level"),
        ],
    ),
    (
        "F-3",
        "gw-site-b-01",
        [
            ("II-4001", "motor_current"),
            ("VI-4002", "gearbox_vibration"),
            ("SI-4003", "speed"),
        ],
    ),
]


def _source_name(asset: str, tag: str) -> str:
    """Gateway naming convention, e.g. K-101 + TI-1012 -> K101.TI1012.PV."""
    return f"{asset.replace('-', '')}.{tag.replace('-', '')}.PV"


def build() -> dict[str, list[list[str]]]:
    asset_type_of = {a[0]: a[5] for a in ASSETS}
    sheets: dict[str, list[list[str]]] = {
        "asset_types": [["code", "name", "description"], *[list(t) for t in ASSET_TYPES]],
        "roles": [["asset_type", "code", "name", "unit"]],
        "assets": [
            ["code", "name", "level", "parent", "criticality", "asset_type", "description"],
            *[list(a) for a in ASSETS],
        ],
        "tags": [
            [
                "source",
                "source_name",
                "asset",
                "description",
                "unit",
                "range_lo",
                "range_hi",
                "interval_s",
                "role",
            ]
        ],
    }
    for type_code, roles in ROLES.items():
        for code, name, unit, _lo, _hi in roles:
            sheets["roles"].append([type_code, code, name, unit])
    for asset, source, tags in TAGS:
        role_table = {r[0]: r for r in ROLES[asset_type_of[asset]]}
        for tag, role in tags:
            _, name, unit, lo, hi = role_table[role]
            sheets["tags"].append(
                [
                    source,
                    _source_name(asset, tag),
                    asset,
                    f"{tag} {name}",
                    unit,
                    f"{lo:g}",
                    f"{hi:g}",
                    "60",
                    role,
                ]
            )
    return sheets


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sheets = build()
    workbook = Workbook()
    workbook.remove(workbook.active)  # type: ignore[arg-type]
    for name, rows in sheets.items():
        with (OUT / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(rows)
        worksheet = workbook.create_sheet(name)
        for row in rows:
            worksheet.append(row)
    workbook.save(OUT / "registry.xlsx")
    counts = {name: len(rows) - 1 for name, rows in sheets.items()}
    print(f"Wrote {OUT}: {counts}")


if __name__ == "__main__":
    main()
