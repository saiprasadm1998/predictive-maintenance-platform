"""Build the AC-03 scoring reference data set: tests/reference_data/scoring_reference.json.

The expected outputs are computed here with exact decimal arithmetic (50 significant
digits), written independently of pmp.scoring, so the reference test compares two
separate implementations of the UCS §6.2 and §6.5 formulas. Predictions are given, so
the data set does not depend on any detector (PMP-ARC-001 §8.3).

    uv run python tools/build_scoring_reference.py
"""

from __future__ import annotations

import json
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any

getcontext().prec = 50
OUT = Path(__file__).resolve().parents[1] / "tests" / "reference_data" / "scoring_reference.json"
D = Decimal
FLOOR = D("0.01")

# Sensor rows: tag, actual, predicted, usable, training range, residual sigma, instrument
# range. Actual "" means no value.
Row = tuple[str, str, str, bool, str, str, str]

K101: list[Row] = [
    ("TI-1012", "78.4", "71.2", True, "14.0", "2.3226", "150"),
    ("ZI-1015", "412", "376", True, "120", "18.0", "1000"),
    ("TI-1030", "47.9", "45.6", True, "9.5", "1.6429", "100"),
    ("PI-1002", "148.2", "150.1", True, "22", "1.9", "250"),
    ("II-1001", "312.5", "309.1", True, "80", "4.25", "400"),
    ("PI-1001", "41.3", "41.0", True, "12", "0.8", "100"),
    ("TI-1001", "38.2", "37.9", True, "10", "0.6", "150"),
    ("TI-1002", "121.4", "120.2", True, "25", "1.4", "200"),
    ("FI-1001", "18250", "18310", True, "4000", "210", "30000"),
    ("SI-1001", "9810", "9805", True, "0", "0", "15000"),  # constant in training: floors
    ("VI-1011X", "21.0", "18.4", True, "30", "2.1", "150"),
    ("VI-1011Y", "19.6", "17.9", True, "30", "2.0", "150"),
    ("VI-1017X", "15.2", "15.0", True, "25", "1.8", "150"),
    ("VI-1017Y", "14.8", "15.1", True, "25", "1.7", "150"),
    ("TI-1016", "64.1", "62.8", True, "11", "1.1", "150"),
    ("PDI-1040", "1.82", "1.79", True, "0.6", "0.05", "5"),
    ("PI-1031", "2.41", "2.38", True, "0.9", "0.07", "10"),
    ("TI-1018", "69.0", "69.3", False, "12", "1.5", "150"),  # flatline: excluded
]

CASES: list[dict[str, Any]] = [
    {
        "name": "UCS worked example: DI 29.5 % with alert limit 25 % gives Health 41, Alert",
        "limits": {"di_warning": "15", "di_alert": "25"},
        "sensors": [
            ("A", "105.9", "100", True, "20", "2", "200"),
            ("B", "40", "45.9", True, "20", "2", "200"),
            ("C", "11.475", "10", True, "5", "0.5", "50"),
            ("D", "0", "29.5", True, "100", "10", "500"),
        ],
    },
    {
        "name": "UCS worked example: DI 15 % (the warning limit) gives Health 70, Watch",
        "limits": {"di_warning": "15", "di_alert": "25"},
        "sensors": [("A", "13", "10", True, "20", "2", "200")],
    },
    {
        "name": "DI exactly at the alert limit: Health 50, Alert",
        "limits": {"di_warning": "15", "di_alert": "25"},
        "sensors": [
            ("A", "5", "10", True, "20", "2", "200"),
            ("B", "1", "0", True, "4", "1", "40"),
        ],
    },
    {
        "name": "Healthy model with an explicit DIref",
        "limits": {"di_warning": "12", "di_alert": "20", "di_ref": "30"},
        "sensors": [
            ("A", "50.4", "50", True, "10", "0.5", "100"),
            ("B", "21", "20.2", True, "8", "0.4", "100"),
            ("C", "7.7", "8", True, "6", "0.3", "100"),
        ],
    },
    {
        "name": "DI above DIref: Health clamped at 0",
        "limits": {"di_warning": "15", "di_alert": "25"},
        "sensors": [("A", "80", "10", True, "100", "5", "500")],
    },
    {
        "name": "K-101 style: 18 sensors, one excluded (flatline), one with floored scale",
        "limits": {
            "di_warning": "15",
            "di_alert": "25",
            "sensors": {"TI-1012": ["3", "5"], "ZI-1015": ["3", "5"]},
        },
        "sensors": K101,
    },
    {
        "name": "Low DI but a sensor |z| above its warning limit: Watch",
        "limits": {"di_warning": "15", "di_alert": "25", "sensors": {"A": ["3", "5"]}},
        "sensors": [
            ("A", "12", "10", True, "40", "0.625", "200"),
            ("B", "5", "5", True, "10", "1", "50"),
        ],
    },
    {
        "name": "Low DI but a sensor |z| above its alert limit: Alert",
        "limits": {"di_warning": "15", "di_alert": "25", "sensors": {"A": ["3", "5"]}},
        "sensors": [
            ("A", "7", "10", True, "40", "0.5", "200"),
            ("B", "5", "5", True, "10", "1", "50"),
        ],
    },
    {
        "name": "An excluded sensor's |z| does not raise the band",
        "limits": {"di_warning": "15", "di_alert": "25", "sensors": {"A": ["3", "5"]}},
        "sensors": [
            ("A", "20", "10", False, "40", "0.5", "200"),
            ("B", "5.2", "5", True, "10", "1", "50"),
        ],
    },
    {
        "name": "Excluded sensor without a value: predicted only",
        "limits": {"di_warning": "15", "di_alert": "25"},
        "sensors": [
            ("A", "", "10", False, "40", "1", "200"),
            ("B", "6", "5", True, "10", "1", "50"),
        ],
    },
]


def floored(
    training_range: Decimal, sigma: Decimal, instrument: Decimal
) -> tuple[Decimal, Decimal]:
    value_range = max(training_range, FLOOR * instrument)
    return value_range, max(sigma, FLOOR * value_range)


def expected(case: dict[str, Any]) -> dict[str, Any]:
    limits = case["limits"]
    warning, alert = D(limits["di_warning"]), D(limits["di_alert"])
    di_ref = D(limits["di_ref"]) if "di_ref" in limits else 2 * alert
    sensor_limits = {t: (D(w), D(a)) for t, (w, a) in limits.get("sensors", {}).items()}

    rows = []
    for tag, actual, predicted, usable, r_train, sigma, instrument in case["sensors"]:
        value_range, sig = floored(D(r_train), D(sigma), D(instrument))
        if actual == "":
            rows.append({"tag": tag, "residual": None, "q": None, "z": None, "usable": usable})
            continue
        residual = D(actual) - D(predicted)
        rows.append(
            {
                "tag": tag,
                "usable": usable,
                "residual": residual,
                "q": abs(residual) / value_range,
                "z": residual / sig,
            }
        )
    used = [r for r in rows if r["usable"]]
    sum_q2 = sum((r["q"] ** 2 for r in used), D(0))
    di = 100 * (sum_q2 / len(used)).sqrt()
    health = 100 * max(D(0), 1 - di / di_ref)

    severities = set()
    for r in used:
        if r["tag"] in sensor_limits:
            w, a = sensor_limits[r["tag"]]
            if abs(r["z"]) >= a:
                severities.add("Alert")
            elif abs(r["z"]) >= w:
                severities.add("Warning")
    if di >= alert or "Alert" in severities:
        band = "Alert"
    elif di >= warning or "Warning" in severities:
        band = "Watch"
    else:
        band = "Healthy"

    def num(value: Decimal | None) -> float | None:
        return None if value is None else float(value)

    return {
        "di": num(di),
        "health": num(health),
        "band": band,
        "coverage": num(D(len(used)) / len(rows)),
        "sensors": {
            r["tag"]: {
                "residual": num(r["residual"]),
                "q": num(r["q"]),
                "z": num(r["z"]),
                "contribution": num(r["q"] ** 2 / sum_q2) if r["usable"] and sum_q2 else None,
            }
            for r in rows
        },
    }


def main() -> None:
    cases = []
    for case in CASES:
        cases.append(
            {
                "name": case["name"],
                "limits": case["limits"],
                "sensors": [
                    {
                        "tag": tag,
                        "actual": float(actual) if actual else None,
                        "predicted": float(predicted),
                        "usable": usable,
                        "training_range": float(r_train),
                        "residual_sigma": float(sigma),
                        "instrument_range": float(instrument),
                    }
                    for tag, actual, predicted, usable, r_train, sigma, instrument in case[
                        "sensors"
                    ]
                ],
                "expected": expected(case),
            }
        )
    document = {
        "description": "AC-03 scoring reference (UCS §6.2, §6.5). Generated by "
        "tools/build_scoring_reference.py with exact decimal arithmetic; do not edit by hand.",
        "tolerance": 1e-6,
        "cases": cases,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(cases)} cases to {OUT}")


if __name__ == "__main__":
    main()
