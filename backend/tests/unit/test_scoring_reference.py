"""AC-03 scoring reference test: every output checked to 1e-6 (UCS §6.2, §6.5, ARC §8.3).

The expected values in tests/reference_data/scoring_reference.json were computed with
exact decimal arithmetic by tools/build_scoring_reference.py, separately from
pmp.scoring. Predictions are supplied, so the test does not depend on any detector.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pmp.scoring import (
    Band,
    Limits,
    SensorInput,
    SensorLimits,
    compute_outputs,
    scale_with_floors,
)

REFERENCE = Path(__file__).resolve().parents[1] / "reference_data" / "scoring_reference.json"
DOCUMENT = json.loads(REFERENCE.read_text(encoding="utf-8"))
TOLERANCE = DOCUMENT["tolerance"]


def _limits(raw: dict[str, Any]) -> Limits:
    return Limits(
        di_warning=float(raw["di_warning"]),
        di_alert=float(raw["di_alert"]),
        di_ref=float(raw["di_ref"]) if "di_ref" in raw else None,
        sensors={
            t: SensorLimits(float(w), float(a)) for t, (w, a) in raw.get("sensors", {}).items()
        },
    )


def _close(actual: float | None, expected: float | None) -> bool:
    if expected is None:
        return actual is None
    return actual is not None and abs(actual - expected) <= TOLERANCE


def test_the_reference_set_meets_the_ac03_tolerance() -> None:
    assert TOLERANCE == 1e-6
    assert len(DOCUMENT["cases"]) >= 10


@pytest.mark.parametrize("case", DOCUMENT["cases"], ids=lambda c: c["name"])
def test_outputs_match_the_reference(case: dict[str, Any]) -> None:
    sensors = [
        SensorInput(s["tag"], s["actual"], s["predicted"], s["usable"]) for s in case["sensors"]
    ]
    scales = {
        s["tag"]: scale_with_floors(s["training_range"], s["residual_sigma"], s["instrument_range"])
        for s in case["sensors"]
    }
    result = compute_outputs(sensors, scales, _limits(case["limits"]))
    expected = case["expected"]

    assert _close(result.di, expected["di"]), (result.di, expected["di"])
    assert _close(result.health, expected["health"]), (result.health, expected["health"])
    assert result.band is Band(expected["band"])
    assert _close(result.coverage, expected["coverage"])
    for output in result.sensors:
        want = expected["sensors"][output.tag]
        for name in ("residual", "q", "z", "contribution"):
            assert _close(getattr(output, name), want[name]), (output.tag, name)


def test_the_worked_example_values() -> None:
    worked = {c["name"]: c["expected"] for c in DOCUMENT["cases"] if "worked example" in c["name"]}
    alert, warning = worked.values()
    assert (round(alert["health"]), alert["band"]) == (41, "Alert")
    assert (round(warning["health"]), warning["band"]) == (70, "Watch")
