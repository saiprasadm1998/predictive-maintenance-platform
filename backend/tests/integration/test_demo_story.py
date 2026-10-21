"""`pmp demo models` and `pmp demo score` (plan 6.0): the story reaches the screens."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from pmp import cli
from pmp.alerting import AlertState, list_alerts
from pmp.core import Actor, Database, get_settings
from pmp.demo import PlantSimulator, demo_tags, load_history, scenarios
from pmp.demo_story import back_score
from pmp.modelling import find_model
from pmp.registry import import_files

pytestmark = pytest.mark.integration
DATA = Path(__file__).resolve().parents[3] / "data" / "demo"
ANCHOR = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


@pytest.fixture
def models_folder(
    clean_models: Database,
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    """K-101 and P-205 with five days of history and shortened training periods."""
    monkeypatch.setenv("PMP_DATABASE_URL", database_url)
    monkeypatch.setenv("PMP_SECRET_KEY", "k")
    monkeypatch.setenv("PMP_LOG_FORMAT", "text")
    monkeypatch.setenv("PMP_ARTEFACT_DIR", str(tmp_path / "artefacts"))
    get_settings.cache_clear()
    with clean_models.session() as s:
        s.execute(text("TRUNCATE sample, alert, alert_event, alert_rule_state CASCADE"))
        import_files(s, Actor.system(), [DATA / "registry" / "registry.xlsx"])
    with clean_models.session() as s:
        tags = [t for t in demo_tags(s) if t.asset_code in {"K-101", "P-205"}]
    # Five days train a much rougher model than the demo's 110, so the excursion is made
    # big enough to stand out from its wider residual spread.
    monkeypatch.setattr(scenarios, "P205_EXCURSION", 60.0)
    simulator = PlantSimulator(tags, anchor=ANCHOR)
    load_history(clean_models, simulator, days=5, work_dir=tmp_path / "work")
    folder = tmp_path / "models"
    folder.mkdir()
    for name in ("k101", "p205"):
        data = json.loads((DATA / "models" / f"{name}.json").read_text())
        data["training_periods"] = [{"start": "-5d", "end": "-2d"}]
        data["validation_period"] = {"start": "-2d", "end": "-1d"}
        (folder / f"{name}.json").write_text(json.dumps(data))
    yield folder
    get_settings.cache_clear()


def run(*args: str) -> int:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["demo", *args])
    return int(exit_info.value.code or 0)


def test_models_then_back_scoring(
    models_folder: Path, clean_models: Database, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("models", str(models_folder)) == 0
    out = capsys.readouterr().out
    assert out.count("trained and deployed") == 2

    assert run("models", str(models_folder)) == 0  # safe to run again
    assert capsys.readouterr().out.count("already in service") == 2

    assert run("score", "--hours", "12") == 0
    out = capsys.readouterr().out
    assert "Done: 721 cycles" in out
    with clean_models.session() as s:
        scored = s.execute(text("SELECT count(*), max(ts) FROM score")).one()
        p205_model = find_model(s, "P-205", "main")
        assert p205_model is not None
        p205 = list_alerts(s, open_only=False, model_id=p205_model.id)
    assert scored[0] == 2 * 721
    assert scored[1] == ANCHOR - timedelta(minutes=1)  # the newest sample's cycle

    # P-205's bearing temperature excursion (10 h to 7 h before the anchor) raised an
    # alert that has returned to normal without being acknowledged.
    assert any(a.state is AlertState.RTN_UNACK for a in p205)

    # Cycles already scored are skipped, so a second run writes nothing.
    again = back_score(clean_models, 12, say=lambda _: None)
    assert again.cycles == 721
    assert again.scored == 0


def test_nothing_to_score_without_models(
    models_folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("score") == 1
    assert "Nothing to score" in capsys.readouterr().out
    assert run("models", str(models_folder / "missing")) == 1
    assert "no .json model definitions" in capsys.readouterr().err
