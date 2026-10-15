"""Synthetic demo plant (plan 1.4): deterministic, realistic, and telling the wireframe story."""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pmp.demo import DemoTag, PlantSimulator, batches_for_minute, replay

ANCHOR = datetime(2026, 10, 15, tzinfo=UTC)
TAGS_CSV = Path(__file__).resolve().parents[3] / "data" / "demo" / "registry" / "tags.csv"


@cache
def all_tags() -> tuple[DemoTag, ...]:
    with TAGS_CSV.open() as handle:
        return tuple(
            DemoTag(
                r["source"],
                r["source_name"],
                r["asset"],
                r["role"],
                r["unit"],
                float(r["range_lo"]),
                float(r["range_hi"]),
            )
            for r in csv.DictReader(handle)
        )


def tags(*names: str) -> list[DemoTag]:
    chosen = [t for t in all_tags() if t.source_name in names]
    assert len(chosen) == len(names)
    return chosen


def series(frame: pd.DataFrame, name: str) -> pd.Series:
    rows = frame[frame["tag"] == name].set_index("ts")["value"]
    return rows.sort_index()


def between(sim: PlantSimulator, days_before: float, days_after: float = 0) -> pd.DataFrame:
    return sim.samples_between(
        ANCHOR - timedelta(days=days_before), ANCHOR + timedelta(days=days_after)
    )


def test_same_seed_gives_identical_data_and_another_seed_does_not() -> None:
    a = between(PlantSimulator(all_tags(), seed=42, anchor=ANCHOR), 1)
    b = between(PlantSimulator(all_tags(), seed=42, anchor=ANCHOR), 1)
    c = between(PlantSimulator(all_tags(), seed=7, anchor=ANCHOR), 1)
    pd.testing.assert_frame_equal(a, b)
    assert not a["value"].equals(c["value"])


def test_one_minute_equals_the_same_minute_inside_history() -> None:
    sim = PlantSimulator(all_tags(), anchor=ANCHOR)
    history = between(sim, 0.5, 0.5)
    for minute in (ANCHOR - timedelta(hours=7, minutes=13), ANCHOR + timedelta(hours=3)):
        alone = sim.samples_at(np.array([minute.timestamp()]))
        inside = history[history["ts"] == pd.Timestamp(minute)]
        pd.testing.assert_frame_equal(alone.reset_index(drop=True), inside.reset_index(drop=True))


def test_sensors_on_one_machine_move_together() -> None:
    sim = PlantSimulator(tags("K101.II1001.PV", "K101.PI1002.PV", "K101.FI1001.PV"), anchor=ANCHOR)
    frame = between(sim, 60, -3)
    current = series(frame, "K101.II1001.PV")
    assert current.corr(series(frame, "K101.PI1002.PV")) > 0.9
    assert current.corr(series(frame, "K101.FI1001.PV")) > 0.9
    assert (current < 1).any()  # a trip happened in these 57 days
    assert current.between(0, 400).all()


def test_thrust_bearing_degradation_builds_up() -> None:
    names = ("K101.TI1012.PV", "K101.ZI1015.PV")
    sim = PlantSimulator(tags(*names), anchor=ANCHOR)
    frame = between(sim, 35)
    for name, at_anchor in (("K101.TI1012.PV", 8.0), ("K101.ZI1015.PV", 45.0)):
        observed = series(frame, name)
        tag = tags(name)[0]
        t = np.array([ts.timestamp() for ts in observed.index])
        injected = observed.to_numpy() - sim._healthy(tag, t)
        assert abs(injected[t < (ANCHOR - timedelta(days=21)).timestamp()]).max() < 1e-3
        assert injected[-1] == pytest.approx(at_anchor, rel=0.02)  # accelerating to the anchor
        assert np.all(np.diff(injected[t >= (ANCHOR - timedelta(days=21)).timestamp()]) >= -1e-3)
    temperature = series(frame, "K101.TI1012.PV")
    rise = (
        temperature[ANCHOR - timedelta(hours=12) :].median()
        - temperature[: ANCHOR - timedelta(days=25)].median()
    )
    assert rise > 3  # visible in the raw signal despite seasonal cooling


def test_flatlines() -> None:
    sim = PlantSimulator(tags("K101.TI1018.PV", "K201.TI2041.PV"), anchor=ANCHOR)
    frame = between(sim, 1, 0.25)
    for name, hours in (("K101.TI1018.PV", 6), ("K201.TI2041.PV", 5)):
        values = series(frame, name)
        assert values[ANCHOR - timedelta(hours=hours) :].nunique() == 1
        assert values[: ANCHOR - timedelta(hours=hours + 1)].std() > 0


def test_stale_tag_and_lost_gateway_link_send_nothing() -> None:
    p202 = [t for t in all_tags() if t.asset_code == "P-202"]
    sim = PlantSimulator([*tags("K201.FI2203.PV"), *p202], anchor=ANCHOR)
    frame = between(sim, 3, 0.1)
    stale = series(frame, "K201.FI2203.PV")
    assert stale.index.max() < pd.Timestamp(ANCHOR - timedelta(hours=3))
    p202_rows = frame[frame["tag"].str.startswith("P202.")]
    assert p202_rows["ts"].max() < pd.Timestamp(ANCHOR - timedelta(days=2))


def test_out_of_range_and_spikes() -> None:
    sim = PlantSimulator(tags("P104A.PI1040.PV", "E110.TI3005.PV"), anchor=ANCHOR)
    frame = between(sim, 1)
    pressure = series(frame, "P104A.PI1040.PV")
    assert (pressure[ANCHOR - timedelta(hours=2) :] > 160).all()
    assert (pressure[: ANCHOR - timedelta(hours=3)] <= 160).all()

    outlet = series(frame, "E110.TI3005.PV")
    jumps = outlet.diff().abs() > 0.25 * 600  # spike rule: > 25 % of range
    recent = int(jumps[ANCHOR - timedelta(hours=12) :].sum())
    assert 2 * 50 <= recent <= 2 * 120  # about 7 spikes an hour, each a jump up and down
    assert int(jumps[: ANCHOR - timedelta(hours=13)].sum()) == 0


def test_bad_quality_is_rare_and_healthy_values_stay_in_range() -> None:
    sim = PlantSimulator(all_tags(), anchor=ANCHOR)
    frame = between(sim, 10, -4)  # before any scenario window opens near the anchor
    rate = (frame["quality"] == "Bad").mean()
    assert 0.0002 < rate < 0.001
    ranges = {t.source_name: (t.range_lo, t.range_hi) for t in all_tags()}
    lo = frame["tag"].map(lambda n: ranges[n][0])
    hi = frame["tag"].map(lambda n: ranges[n][1])
    healthy = frame[~frame["tag"].isin(["P104A.PI1040.PV", "E110.TI3005.PV"])]
    assert healthy["value"].between(lo[healthy.index], hi[healthy.index]).all()


def test_batches_group_one_minute_by_gateway_source() -> None:
    sim = PlantSimulator(all_tags(), anchor=ANCHOR)
    minute = sim.samples_at(np.array([(ANCHOR - timedelta(days=5)).timestamp()]))
    batches = list(batches_for_minute(minute))
    assert [b["source"] for b in batches] == ["gw-site-a-01", "gw-site-b-01"]
    first = batches[0]["samples"][0]  # type: ignore[index]
    assert set(first) == {"tag", "ts", "v", "q"}
    assert first["ts"].endswith("+00:00")


def test_replay_catches_up_then_runs_in_real_time() -> None:
    now = [(ANCHOR + timedelta(hours=1)).timestamp()]
    posted: list[dict[str, object]] = []
    sleeps: list[float] = []

    def fake_post(url: str, key: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
        posted.append(payload)
        return 202, {"accepted": len(payload["samples"]), "rejected": []}  # type: ignore[arg-type]

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    stats = replay(
        PlantSimulator(all_tags(), anchor=ANCHOR),
        url="http://x/api/v1/ingest/samples",
        key="k",
        start=ANCHOR + timedelta(minutes=58),
        speed=60,
        minutes=4,
        post=fake_post,
        clock=lambda: now[0],
        sleep=fake_sleep,
        log=lambda _: None,
    )
    assert stats.minutes == 4
    assert stats.failed_batches == 0
    assert len(posted) == 4 * 2  # two gateway sources
    assert sleeps[0] == pytest.approx(1.0)  # catching up: one simulated minute per second
    assert any(s > 50 for s in sleeps)  # then waiting for real time
    assert stats.accepted == sum(len(p["samples"]) for p in posted)  # type: ignore[arg-type,misc]
