"""Property-based tests of the scoring outputs (UCS §6.2, §6.5)."""

from __future__ import annotations

import math

from hypothesis import given
from hypothesis import strategies as st

from pmp.scoring import Band, Limits, SensorInput, SensorScale, compute_outputs, health_score

values = st.floats(min_value=-1e4, max_value=1e4, allow_nan=False)
scales = st.builds(
    SensorScale,
    range=st.floats(min_value=1e-3, max_value=1e4),
    sigma=st.floats(min_value=1e-3, max_value=1e4),
)
limit_pairs = st.tuples(
    st.floats(min_value=1, max_value=50), st.floats(min_value=1.01, max_value=3)
).map(lambda p: Limits(di_warning=p[0], di_alert=p[0] * p[1]))
sensor_rows = st.lists(st.tuples(values, values, scales, st.booleans()), min_size=1, max_size=25)


@given(rows=sensor_rows, limits=limit_pairs)
def test_outputs_hold_their_invariants(
    rows: list[tuple[float, float, SensorScale, bool]], limits: Limits
) -> None:
    rows[0] = (*rows[0][:3], True)  # at least one usable sensor
    sensors = [SensorInput(f"s{i}", a, p, u) for i, (a, p, _, u) in enumerate(rows)]
    result = compute_outputs(sensors, {f"s{i}": r[2] for i, r in enumerate(rows)}, limits)
    assert result.di is not None
    assert result.health is not None

    assert result.di >= 0
    assert 0 <= result.health <= 100
    contributions = [s.contribution for s in result.sensors if s.usable]
    if any(c for c in contributions):
        assert math.isclose(math.fsum(c or 0 for c in contributions), 1.0, rel_tol=1e-9)
    assert result.coverage == sum(u for *_, u in rows) / len(rows)
    if result.di >= limits.di_alert:
        assert result.band is Band.ALERT
    elif result.di >= limits.di_warning:
        assert result.band is Band.WATCH
    else:
        assert result.band is Band.HEALTHY  # no sensor rules configured
    for s in result.sensors:
        assert s.q is not None
        assert s.residual is not None
        assert s.z is not None
        assert math.isclose(s.q * scale_of(rows, s.tag).range, abs(s.residual), rel_tol=1e-9)


def scale_of(rows: list[tuple[float, float, SensorScale, bool]], tag: str) -> SensorScale:
    return rows[int(tag[1:])][2]


@given(
    a=st.floats(min_value=0, max_value=500),
    b=st.floats(min_value=0, max_value=500),
    alert=st.floats(min_value=1, max_value=100),
)
def test_health_never_rises_as_di_rises(a: float, b: float, alert: float) -> None:
    ref = 2 * alert
    low, high = sorted((a, b))
    assert health_score(low, ref) >= health_score(high, ref)
    assert math.isclose(health_score(alert, ref), 50.0)


@given(scale=st.floats(min_value=0.1, max_value=1e3), rows=sensor_rows)
def test_di_does_not_depend_on_engineering_units(
    scale: float, rows: list[tuple[float, float, SensorScale, bool]]
) -> None:
    """Rescaling a sensor's values and its range together leaves q and DI unchanged."""
    limits = Limits(15, 25)
    base = [SensorInput(f"s{i}", a, p, True) for i, (a, p, _, _) in enumerate(rows)]
    scaled = [
        SensorInput(s.tag, (s.actual or 0) * scale, (s.predicted or 0) * scale, True) for s in base
    ]
    scales_1 = {f"s{i}": r[2] for i, r in enumerate(rows)}
    scales_k = {t: SensorScale(s.range * scale, s.sigma * scale) for t, s in scales_1.items()}
    di_1 = compute_outputs(base, scales_1, limits).di
    di_k = compute_outputs(scaled, scales_k, limits).di
    assert di_1 is not None
    assert di_k is not None
    assert math.isclose(di_1, di_k, rel_tol=1e-9, abs_tol=1e-9)
