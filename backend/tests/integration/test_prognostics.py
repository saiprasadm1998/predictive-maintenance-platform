"""Forecasts against PostgreSQL (plan 8.3, UC-11, FR-PRG-01, -02).

The model is the scoring tests' EQ-1 / main; its scores are replaced by a DI ramp so the
crossing time is known.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pytest
from sqlalchemy import text

from pmp import cli
from pmp.core import Database, get_settings
from pmp.modelling import get_model
from pmp.prognostics import (
    ForecastError,
    ForecastRequest,
    Target,
    ThresholdKind,
    latest_for_alerts,
    list_forecasts,
    run_forecast,
)
from tests.integration.test_alerts import _raise_one
from tests.integration.test_scoring_cycle import (  # noqa: F401  (deployed is a fixture)
    ACTOR,
    LIVE,
    deployed,
)

pytestmark = pytest.mark.integration


def seed_di_ramp(db: Database, days: float = 3, start: float = 20, per_day: float = 2) -> int:
    """Replace EQ-1 / main's scores with a noisy DI ramp every 5 minutes, ending at its
    newest cycle (or LIVE): DI = start + per_day · t, t in days up to 0. Returns the model."""
    with db.session() as s:
        model = get_model(s, "EQ-1", "main")
        version_id = model.latest.id
        end = (
            s.execute(
                text("SELECT max(ts) FROM score WHERE version_id = :v"), {"v": version_id}
            ).scalar_one()
            or LIVE
        )
        s.execute(text("DELETE FROM score WHERE version_id = :v"), {"v": version_id})
        steps = int(days * 24 * 12)
        noise = np.random.default_rng(3).normal(0, 0.3, steps + 1)
        rows = [
            {
                "v": version_id,
                "m": model.id,
                "ts": end - timedelta(minutes=5 * i),
                "di": start - per_day * (5 * i) / 1440 + float(noise[i]),
            }
            for i in range(steps + 1)
        ]
        s.execute(
            text(
                "INSERT INTO score (version_id, ts, model_id, status, band, di, health, coverage)"
                " VALUES (:v, :ts, :m, 'Running', 'Healthy', :di, 90, 1)"
            ),
            rows,
        )
        return model.id


def test_a_di_ramp_forecast_is_stored_with_the_open_di_alert(
    deployed: Database,  # noqa: F811
) -> None:
    alert_id = _raise_one(deployed)  # DI warning 10, alert 200
    model_id = seed_di_ramp(deployed)
    with deployed.session() as s:
        custom = run_forecast(
            s,
            ACTOR,
            ForecastRequest(model_id, Target.DI, None, ThresholdKind.CUSTOM, 30.0),
        )
        alert_limit = run_forecast(s, ACTOR, ForecastRequest(model_id))
    assert custom.valid
    assert custom.method == "linear"
    assert custom.direction == 1
    assert custom.median_h == pytest.approx(5 * 24, rel=0.05)  # 20 -> 30 at 2 per day
    assert custom.urgency == "High"  # its lower bound is within 7 days
    assert custom.alert_id == alert_id  # the open DI alert
    assert custom.points >= 96
    assert len(custom.series) == custom.points
    assert alert_limit.threshold == 200
    assert alert_limit.urgency == "Low"
    with deployed.session() as s:
        assert [f.id for f in list_forecasts(s, model_id=model_id)] == [
            alert_limit.id,
            custom.id,
        ]
        assert latest_for_alerts(s, [alert_id])[alert_id].id == alert_limit.id


def test_what_a_forecast_refuses(deployed: Database) -> None:  # noqa: F811
    model_id = seed_di_ramp(deployed, days=0.5)
    with deployed.session() as s:
        tag_id = get_model(s, "EQ-1", "main").latest.sensors[0].tag_id
        with pytest.raises(ForecastError, match="24 h"):
            run_forecast(s, ACTOR, ForecastRequest(model_id, threshold_kind=ThresholdKind.WARNING))
        with pytest.raises(ForecastError, match="custom threshold"):
            run_forecast(s, ACTOR, ForecastRequest(model_id, Target.ACTUAL, tag_id))
        with pytest.raises(ForecastError, match="sensor of the model"):
            run_forecast(s, ACTOR, ForecastRequest(model_id, Target.ACTUAL, 999_999))
        with pytest.raises(ForecastError, match="does not exist"):
            run_forecast(s, ACTOR, ForecastRequest(999_999))


def test_the_forecast_command(
    deployed: Database,  # noqa: F811
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_di_ramp(deployed)
    monkeypatch.setenv("PMP_DATABASE_URL", database_url)
    monkeypatch.setenv("PMP_SECRET_KEY", "k")
    monkeypatch.setenv("PMP_LOG_FORMAT", "text")
    get_settings.cache_clear()

    def run(*argv: str) -> int:
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["forecast", "EQ-1", *argv])
        return int(exit_info.value.code or 0)

    try:
        assert run("--threshold", "30", "--window", "3") == 0
        out = capsys.readouterr().out
        assert "Fit: linear" in out
        assert "Reaches 30 in" in out
        assert "Urgency: High" in out
        assert run("--threshold", "lots") == 1
        assert run("--target", "actual", "--tag", "NOPE", "--threshold", "5") == 1
    finally:
        get_settings.cache_clear()
