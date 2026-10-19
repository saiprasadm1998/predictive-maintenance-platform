"""One model's cycle without a database (UCS §6.2 Figure 5, FR-RUN-04)."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from pmp.dataquality import DEFAULTS, Rule, SensorReading
from pmp.dataquality.domain import state_for
from pmp.modelling import LoadedModel, MedianDetector, SensorScale
from pmp.scoring import (
    Band,
    Limits,
    RuntimeStatus,
    SensorLimits,
    evaluate,
    latest_due_cycle,
    references_for,
)

GOOD = state_for(Rule.NONE, DEFAULTS)
STALE = state_for(Rule.STALE, DEFAULTS)
UNCERTAIN = state_for(Rule.UNCERTAIN_QUALITY, DEFAULTS)
LIMITS = Limits(15, 25, sensors={"T1": SensorLimits()})


def _model(filters: tuple[str, ...] = ("MOTOR > 120",)) -> LoadedModel:
    names = ["T1", "T2", "T3", "T4"]
    detector = MedianDetector()
    detector.fit(pd.DataFrame(np.zeros((5, 4)), columns=names), {})  # scaled medians are 0
    return LoadedModel(
        model_id=1,
        version_id=10,
        version=1,
        detector=detector,
        sensors=tuple(names),
        tag_ids={"T1": 1, "T2": 2, "T3": 3, "T4": 4},
        required=frozenset({"T1"}),
        medians={"T1": 50.0, "T2": 20.0, "T3": 100.0, "T4": 0.0},
        scales={n: SensorScale(range=10.0, sigma=1.0) for n in names},
        training_std={"T1": 2.0, "T2": None, "T3": 1.0, "T4": 1.0},
        mode_filters=filters,
        filter_tag_ids={"MOTOR": 9},
        cycle_s=60,
        sha256="x" * 64,
    )


def readings(**values: tuple[float | None, object]) -> dict[int, SensorReading]:
    ids = {"T1": 1, "T2": 2, "T3": 3, "T4": 4, "MOTOR": 9}
    return {ids[n]: SensorReading(v, s) for n, (v, s) in values.items()}  # type: ignore[arg-type]


def test_a_healthy_cycle_runs_and_predicts_every_sensor() -> None:
    status, reason, out = evaluate(
        _model(),
        readings(
            T1=(51.0, GOOD),
            T2=(20.5, GOOD),
            T3=(99.0, UNCERTAIN),
            T4=(0.0, GOOD),
            MOTOR=(150.0, GOOD),
        ),
        LIMITS,
    )
    assert (status, reason) == (RuntimeStatus.RUNNING, None)
    assert out.band is Band.HEALTHY
    assert [s.predicted for s in out.sensors] == [50.0, 20.0, 100.0, 0.0]
    assert out.sensors[0].residual == pytest.approx(1.0)
    assert out.coverage == 1.0  # uncertain counts as usable


def test_an_excluded_sensor_is_still_predicted_but_not_counted() -> None:
    status, _, out = evaluate(
        _model(),
        readings(
            T1=(51.0, GOOD), T2=(80.0, STALE), T3=(100.0, GOOD), T4=(0.0, GOOD), MOTOR=(150.0, GOOD)
        ),
        LIMITS,
    )
    assert status is RuntimeStatus.RUNNING
    t2 = out.sensors[1]
    assert (t2.usable, t2.predicted, t2.actual, t2.contribution) == (False, 20.0, 80.0, None)
    assert t2.residual == pytest.approx(60.0)  # shown, like TI-1018 on wireframe 03
    assert out.coverage == pytest.approx(3 / 4)
    assert out.di == pytest.approx(100 * np.sqrt(0.1**2 / 3))


def test_a_sensor_z_above_its_limit_raises_the_band() -> None:
    _, _, out = evaluate(
        _model(),
        readings(
            T1=(54.0, GOOD), T2=(20.0, GOOD), T3=(100.0, GOOD), T4=(0.0, GOOD), MOTOR=(150.0, GOOD)
        ),
        LIMITS,
    )
    assert out.band is Band.WATCH  # z = 4 on T1, DI below the warning limit


@pytest.mark.parametrize(
    ("values", "status", "reason"),
    [
        (
            {
                "T1": (51.0, GOOD),
                "T2": (20.0, GOOD),
                "T3": (100.0, GOOD),
                "T4": (0.0, GOOD),
                "MOTOR": (10.0, GOOD),
            },
            RuntimeStatus.NOT_IN_OPERATING_MODE,
            "operating-mode",
        ),
        (
            {
                "T1": (51.0, GOOD),
                "T2": (20.0, GOOD),
                "T3": (100.0, GOOD),
                "T4": (0.0, GOOD),
                "MOTOR": (150.0, STALE),
            },
            RuntimeStatus.NOT_IN_OPERATING_MODE,
            "operating-mode",
        ),
        (
            {
                "T1": (51.0, STALE),
                "T2": (20.0, GOOD),
                "T3": (100.0, GOOD),
                "T4": (0.0, GOOD),
                "MOTOR": (150.0, GOOD),
            },
            RuntimeStatus.INSUFFICIENT_DATA,
            "Required sensor not usable: T1",
        ),
        (
            {"T1": (51.0, GOOD), "T2": (None, GOOD), "T3": (100.0, STALE), "MOTOR": (150.0, GOOD)},
            RuntimeStatus.INSUFFICIENT_DATA,
            "Coverage 25% (needs 70%)",
        ),
    ],
)
def test_unknown_statuses(
    values: dict[str, tuple[float | None, object]], status: RuntimeStatus, reason: str
) -> None:
    got, why, out = evaluate(_model(), readings(**values), LIMITS)
    assert got is status
    assert reason in (why or "")
    assert (out.band, out.di, out.health) == (Band.UNKNOWN, None, None)


def test_a_model_without_filters_is_always_in_mode() -> None:
    status, _, _ = evaluate(
        _model(filters=()),
        readings(T1=(51.0, GOOD), T2=(20.0, GOOD), T3=(100.0, GOOD), T4=(0.0, GOOD)),
        LIMITS,
    )
    assert status is RuntimeStatus.RUNNING


def test_cycles_fall_on_the_clock_after_the_grace_period() -> None:
    now = datetime(2026, 10, 20, 9, 0, 19, tzinfo=UTC)
    assert latest_due_cycle(now, 60, 20) == datetime(2026, 10, 20, 8, 59, tzinfo=UTC)
    later = datetime(2026, 10, 20, 9, 0, 20, tzinfo=UTC)
    assert latest_due_cycle(later, 60, 20) == datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    assert latest_due_cycle(later, 5, 0).second % 10 == 0  # minimum cycle 10 s


def test_training_statistics_become_data_quality_references() -> None:
    first, second = _model(), _model()
    second = LoadedModel(
        **{**second.__dict__, "scales": {n: SensorScale(4.0, 1.0) for n in second.sensors}}
    )
    refs = references_for([first, second])
    assert refs[1].range == 4.0  # the later deployment wins
    assert refs[1].std == 2.0
    assert refs[2].std is None
