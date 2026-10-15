"""Synthetic plant behaviour for development and demos (plan sub-phase 1.4).

SYNTHETIC DATA. It proves the software works end to end; it does not prove that PMP
detects real equipment failures. That is acceptance criterion AC-04 and needs the
client's history and event records (PMP-PRD-001 R-02).

Every value is a pure function of (seed, tag, time): no hidden state. History and live
replay therefore produce identical values for the same minute, and re-running anything
is harmless.

How a sensor value is built (all in fractions of the tag's instrument range):

    value = idle + (full - idle) * load(asset, t)      operating point
          + ambient sensitivity * (ambient(t) - 15 °C)  for temperatures
          + slow wander (three sine waves, random phase) so signals drift like real ones
          + white noise
          + scenario effects (degradation, flatline, spikes, ...; see scenarios.py)

Sensors on one asset share its load profile, so they move together the way a real
machine's do: that shared structure is what the normal-behaviour model learns later.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
MINUTE = 60.0
DAY = 86_400.0


@dataclass(frozen=True)
class RoleProfile:
    full: float  # fraction of range at full load
    idle: float  # fraction of range when stopped
    ambient: float = 0.0  # engineering units per °C of ambient deviation
    noise: float = 0.003  # white noise, fraction of range
    wander: float = 0.008  # slow wander amplitude, fraction of range


_TEMP = 0.5
PROFILES: dict[str, RoleProfile] = {
    "motor_current": RoleProfile(0.75, 0.0),
    "discharge_pressure": RoleProfile(0.62, 0.15),
    "suction_pressure": RoleProfile(0.30, 0.26),
    "suction_temp": RoleProfile(0.40, 0.20, _TEMP),
    "discharge_temp": RoleProfile(0.55, 0.15, _TEMP),
    "suction_flow": RoleProfile(0.70, 0.0),
    "flow": RoleProfile(0.70, 0.0),
    "speed": RoleProfile(0.75, 0.0, noise=0.0005),
    "de_bearing_temp": RoleProfile(0.475, 0.20, _TEMP),
    "nde_bearing_temp": RoleProfile(0.46, 0.20, _TEMP),
    "thrust_pad_temp": RoleProfile(0.50, 0.20, _TEMP),
    "main_bearing_temp": RoleProfile(0.45, 0.20, _TEMP),
    "axial_displacement": RoleProfile(0.375, 0.30),
    "de_vibration_x": RoleProfile(0.18, 0.02),
    "de_vibration_y": RoleProfile(0.17, 0.02),
    "nde_vibration_x": RoleProfile(0.15, 0.02),
    "nde_vibration_y": RoleProfile(0.14, 0.02),
    "de_vibration": RoleProfile(0.12, 0.01),
    "nde_vibration": RoleProfile(0.10, 0.01),
    "crosshead_vibration": RoleProfile(0.15, 0.01),
    "frame_vibration": RoleProfile(0.10, 0.01),
    "gearbox_vibration": RoleProfile(0.12, 0.01),
    "rod_drop": RoleProfile(0.30, 0.30, noise=0.001),
    "lube_oil_supply_temp": RoleProfile(0.455, 0.30, _TEMP),
    "lube_oil_pressure": RoleProfile(0.25, 0.24),
    "seal_gas_dp": RoleProfile(0.30, 0.25),
    "crankcase_temp": RoleProfile(0.50, 0.25, _TEMP),
    "gas_inlet_temp": RoleProfile(0.75, 0.10),
    "gas_outlet_temp": RoleProfile(0.35, 0.08),
    "steam_pressure": RoleProfile(0.60, 0.10),
    "steam_flow": RoleProfile(0.65, 0.0),
    "drum_level": RoleProfile(0.50, 0.50),
}
DEFAULT_PROFILE = RoleProfile(0.5, 0.2)


@dataclass(frozen=True)
class DemoTag:
    source: str
    source_name: str
    asset_code: str
    role: str | None
    unit: str
    range_lo: float
    range_hi: float

    @property
    def span(self) -> float:
        return self.range_hi - self.range_lo


def stable_hash(*parts: object) -> int:
    return zlib.crc32("|".join(str(p) for p in parts).encode())


def _rng(seed: int, *parts: object) -> np.random.Generator:
    return np.random.default_rng([seed, stable_hash(*parts)])


def epoch_seconds(ts: datetime) -> float:
    return ts.timestamp()


def minute_grid(start: datetime, end: datetime) -> FloatArray:
    """Epoch seconds of every whole minute in [start, end)."""
    first = np.ceil(epoch_seconds(start) / MINUTE) * MINUTE
    return np.arange(first, epoch_seconds(end), MINUTE, dtype=np.float64)


def ambient(t: FloatArray) -> FloatArray:
    """Outdoor temperature (°C): yearly and daily cycles, warmest mid-afternoon."""
    year = 365.25 * DAY
    return (
        15.0
        + 8.0 * np.sin(2 * np.pi * (t / year - 0.30))
        + 5.0 * np.sin(2 * np.pi * (t / DAY - 0.375))
    )


def load_profile(seed: int, asset: str, t: FloatArray, quiet_from: float) -> FloatArray:
    """Operating point 0..1 of one asset.

    Daily base load between 85 % and 100 % (smoothly interpolated), turndown to about 65 %
    on roughly one day in ten for 6 to 18 hours, and one trip a month (stopped for 2 to 6
    hours, then a 30-minute restart ramp). No trips after `quiet_from`, so the scenarios
    near the end of the history stay readable.
    """
    if t.size == 0:
        return t.copy()
    day_index = np.floor(t / DAY).astype(np.int64)
    days = np.arange(day_index.min() - 1, day_index.max() + 2)
    base_by_day = np.array([_rng(seed, asset, "base", d).uniform(0.85, 1.0) for d in days])
    centres = (days + 0.5) * DAY
    load = np.interp(t, centres, base_by_day)

    # Include the day before: a turndown can run past midnight.
    for d in range(int(day_index.min()) - 1, int(day_index.max()) + 1):
        rng = _rng(seed, asset, "turndown", d)
        if rng.random() < 0.1:
            begin = d * DAY + rng.uniform(0, 18) * 3600
            length = rng.uniform(6, 18) * 3600
            load *= 1 - 0.35 * _window(t, begin, begin + length, ramp=20 * MINUTE)

    period = 30 * DAY
    periods = np.floor(t / period).astype(np.int64)
    # Include the previous period: a trip near its end can run into this one.
    for p in range(int(periods.min()) - 1, int(periods.max()) + 1):
        rng = _rng(seed, asset, "trip", p)
        stop = p * period + rng.uniform(0, period)
        if stop >= quiet_from:
            continue
        restart = stop + rng.uniform(2, 6) * 3600
        stopped = (t >= stop) & (t < restart)
        ramp = (t >= restart) & (t < restart + 30 * MINUTE)
        load = np.where(stopped, 0.0, load)
        load = np.where(ramp, load * (t - restart) / (30 * MINUTE), load)
    clipped: FloatArray = np.clip(load, 0.0, 1.0)
    return clipped


def _window(t: FloatArray, begin: float, end: float, ramp: float) -> FloatArray:
    """1 inside [begin, end] with linear ramps of `ramp` seconds at both ends, else 0."""
    rise = np.clip((t - begin) / ramp, 0, 1)
    fall = np.clip((end - t) / ramp, 0, 1)
    out: FloatArray = np.minimum(rise, fall)
    return out


def wander(seed: int, tag: str, t: FloatArray) -> FloatArray:
    """Slow, smooth drift: three sine waves with periods of hours to days."""
    rng = _rng(seed, tag, "wander")
    out = np.zeros_like(t)
    for period_h in (3.1, 11.3, 37.7):
        out += rng.uniform(0.3, 1.0) * np.sin(
            2 * np.pi * t / (period_h * 3600) + rng.uniform(0, 6.3)
        )
    return out / 2.0


def daily_uniform(seed: int, tag: str, purpose: str, t: FloatArray) -> FloatArray:
    """A deterministic uniform(0, 1) number per (tag, minute), drawn per day."""
    out = np.empty_like(t)
    day_index = np.floor(t / DAY).astype(np.int64)
    minute_of_day = ((t - day_index * DAY) // MINUTE).astype(np.int64)
    for d in np.unique(day_index):
        draws = _rng(seed, tag, purpose, int(d)).random(1440)
        mask = day_index == d
        out[mask] = draws[minute_of_day[mask]]
    return out


def daily_normal(seed: int, tag: str, purpose: str, t: FloatArray) -> FloatArray:
    out = np.empty_like(t)
    day_index = np.floor(t / DAY).astype(np.int64)
    minute_of_day = ((t - day_index * DAY) // MINUTE).astype(np.int64)
    for d in np.unique(day_index):
        draws = _rng(seed, tag, purpose, int(d)).standard_normal(1440)
        mask = day_index == d
        out[mask] = draws[minute_of_day[mask]]
    return out


def base_signal(seed: int, tag: DemoTag, t: FloatArray, load: FloatArray) -> FloatArray:
    """Healthy value of one tag (engineering units) before any scenario."""
    profile = PROFILES.get(tag.role or "", DEFAULT_PROFILE)
    fraction = profile.idle + (profile.full - profile.idle) * load
    value = tag.range_lo + tag.span * fraction
    if profile.ambient:
        value = value + profile.ambient * (ambient(t) - 15.0)
    value = value + tag.span * profile.wander * wander(seed, tag.source_name, t) * np.maximum(
        load, 0.2
    )
    value = value + tag.span * profile.noise * daily_normal(seed, tag.source_name, "noise", t)
    out: FloatArray = np.clip(value, tag.range_lo, tag.range_hi)
    return out


def anchor_seconds(anchor: datetime) -> float:
    return epoch_seconds(anchor)


def quiet_period_start(anchor: datetime) -> float:
    return epoch_seconds(anchor - timedelta(days=3))
