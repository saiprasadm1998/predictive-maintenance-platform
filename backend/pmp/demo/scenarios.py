"""The demo story: faults injected into the synthetic plant (plan sub-phase 1.4).

Times are relative to the anchor (default: today 00:00 UTC) and keep developing after
it, so a live replay continues the story. Each scenario matches something shown in the
PMP-PDS-001 wireframes, so screens built in Phase 6 have the right things to show.

- K-101 TI-1012, ZI-1015, TI-1016, TI-1030, VI-1011X/Y: thrust-bearing degradation,
  a slow accelerating rise from 21 days before the anchor. Should raise the Deviation
  Index and an alert (Phase 4), match the failure mode (8.2) and give a forecast (8.3).
- K-101 TI-1018: flatline from 6 h before the anchor (flatline rule, 2.1).
- P-104A TI-1044: DE bearing temperature creeping up over 3 days (sensor Warning, Watch).
- P-104A PI-1040: above its instrument range from 2 h before (out-of-range rule).
- K-201 TI-2041: flatline from 5 h before (flatline rule).
- K-201 FI-2203: stops reporting 3 h before (stale rule).
- K-201 ZI-2011: rod drop rising over 4 days, rider-band wear (Deviation Index).
- P-202, every tag: gateway link lost 2 days before, no data (insufficient data).
- E-110 TI-3005: spikes, about 7 an hour, from 12 h before (spike rule).
- P-205 TI-2054: a bearing temperature excursion from 10 h to 7 h before, then back to
  normal (an alert that returned to normal unacknowledged; plan 6.0).
- F-3 VI-4002: gearbox vibration rising from 20 h before, then holding (a Warning; 6.0).
- Every tag: about 1 sample in 2,000 has quality Bad (bad-quality rule).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from pmp.demo.model import DAY, DemoTag, FloatArray, daily_uniform

HOUR = 3600.0
BAD_QUALITY_RATE = 0.0005


def _ramp(t: FloatArray, start: float, length: float, power: float = 2.0) -> FloatArray:
    """0 before start, then (elapsed / length) ** power: 1.0 at start + length, growing after."""
    out: FloatArray = np.clip((t - start) / length, 0.0, None) ** power
    return out


def _hump(t: FloatArray, start: float, length: float) -> FloatArray:
    """A smooth bump: 0 outside [start, start + length], 1 at its middle."""
    phase = np.clip((t - start) / length, 0.0, 1.0)
    out: FloatArray = np.sin(np.pi * phase) ** 2
    return out


@dataclass(frozen=True)
class Effects:
    value: FloatArray  # adjusted values
    sent: np.ndarray  # bool: False where the gateway sends nothing (stale, link lost)
    bad: np.ndarray  # bool: quality Bad


# Degradation added at the anchor (engineering units); it keeps growing afterwards.
THRUST_BEARING = {
    "K101.TI1012.PV": 8.0,  # DE bearing temperature, °C
    "K101.ZI1015.PV": 45.0,  # axial displacement, µm
    "K101.TI1016.PV": 10.0,  # thrust pad temperature, °C
    "K101.TI1030.PV": 2.0,  # lube oil supply temperature, °C
    "K101.VI1011X.PV": 6.0,  # DE shaft vibration, µm
    "K101.VI1011Y.PV": 5.0,
}

# Sized against the demo models' residual spread (sigma about 2.7 °C, 0.15 mm/s and 2.7 °C)
# so each lands in the band the wireframes show (decision 6.0).
P205_EXCURSION = 22.0  # °C at the peak: |z| about 8, an Alert
F3_RISE = 0.45  # mm/s, reached at the anchor and then held: |z| about 3.5, a Warning
P104A_CREEP = 15.0  # °C over 3 days to the anchor, then held: |z| 3.5 to 4.5, a Warning


def apply(
    seed: int,
    tag: DemoTag,
    t: FloatArray,
    value: FloatArray,
    anchor: float,
    healthy: Callable[[FloatArray], FloatArray],
) -> Effects:
    """Apply the scenarios to one tag. `healthy(t)` gives the tag's value before any
    scenario at any time, so effects never depend on which times are in `t`."""
    name = tag.source_name
    value = value.copy()
    sent = np.ones(t.shape, dtype=bool)

    if name in THRUST_BEARING:
        value += THRUST_BEARING[name] * _ramp(t, anchor - 21 * DAY, 21 * DAY)
    if name == "P104A.TI1044.PV":
        value += P104A_CREEP * np.minimum(_ramp(t, anchor - 3 * DAY, 3 * DAY, power=1.0), 1.0)
    if name == "P205.TI2054.PV":
        value += P205_EXCURSION * _hump(t, anchor - 10 * HOUR, 3 * HOUR)
    if name == "F3.VI4002.PV":
        value += F3_RISE * np.minimum(_ramp(t, anchor - 20 * HOUR, 20 * HOUR, power=1.0), 1.0)
    if name == "K201.ZI2011.PV":
        value += 0.08 * tag.span * _ramp(t, anchor - 4 * DAY, 4 * DAY, power=1.5)

    for flat_name, hours in (("K101.TI1018.PV", 6), ("K201.TI2041.PV", 5)):
        if name == flat_name:
            begin = anchor - hours * HOUR
            frozen = t >= begin
            if frozen.any():
                value[frozen] = healthy(np.array([begin]))[0]  # stuck at the value it had

    if name == "P104A.PI1040.PV":
        value = np.where(t >= anchor - 2 * HOUR, tag.range_hi + 0.05 * tag.span, value)

    if name == "E110.TI3005.PV":
        window = t >= anchor - 12 * HOUR
        spikes = window & (daily_uniform(seed, name, "spike", t) < 7 / 60)
        value = np.where(spikes, value + 0.3 * tag.span, value)

    if name == "K201.FI2203.PV":
        sent &= t < anchor - 3 * HOUR
    if tag.asset_code == "P-202":
        sent &= t < anchor - 2 * DAY

    bad = daily_uniform(seed, name, "quality", t) < BAD_QUALITY_RATE
    return Effects(value=value, sent=sent, bad=bad)
