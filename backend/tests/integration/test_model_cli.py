"""`pmp model` with the demo K-101 definition (plan 3.1 "Done when")."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from pmp import cli
from pmp.alerting import RuleKind, list_alert_rules
from pmp.core import Actor, Database, get_settings
from pmp.modelling import get_model
from pmp.registry import import_files

pytestmark = pytest.mark.integration
DATA = Path(__file__).resolve().parents[3] / "data" / "demo"
K101 = DATA / "models" / "k101.json"


@pytest.fixture
def demo_registry(
    clean_models: Database, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Database]:
    monkeypatch.setenv("PMP_DATABASE_URL", database_url)
    monkeypatch.setenv("PMP_SECRET_KEY", "k")
    monkeypatch.setenv("PMP_LOG_FORMAT", "text")
    get_settings.cache_clear()
    with clean_models.session() as s:
        import_files(s, Actor.system(), [DATA / "registry" / "registry.xlsx"])
    yield clean_models
    get_settings.cache_clear()


def run(*args: str) -> int:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["model", *args])
    return int(exit_info.value.code or 0)


def test_the_k101_model_is_defined_from_its_file(
    demo_registry: Database, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("create", str(K101)) == 0
    out = capsys.readouterr().out
    assert "Saved K-101 / main version 1 (Draft)" in out
    assert "sensors (18, 4 required)" in out
    assert "operating mode:     K101.II1001.PV > 120" in out

    with demo_registry.session() as s:
        model = get_model(s, "K-101", "main")
        rules = list_alert_rules(s, model.id)
    assert len(model.latest.sensors) == 18
    assert model.latest.mode_filters == ("K101.II1001.PV > 120",)
    assert len(model.latest.training_periods) == 1
    di = rules[0].spec
    assert (di.kind, di.warning, di.alert) == (RuleKind.DI, 15.0, 25.0)
    assert sorted(r.spec.warning for r in rules[1:]) == [3.0, 3.0, 3.0]

    assert run("create", str(K101)) == 0  # saving again updates the same draft
    assert run("list") == 0
    listing = capsys.readouterr().out
    assert "K-101" in listing
    assert "v1 Draft" in listing
    assert "18 sensors" in listing

    assert run("show", "K-101", "main") == 0
    assert "|z| K101.TI1012.PV" in capsys.readouterr().out


def test_problems_in_a_file_are_listed(
    demo_registry: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = json.loads(K101.read_text())
    data["sensors"].append({"tag": "K201.TI2041.PV"})
    data["mode_filters"] = ["K101.II1001.PV >"]
    data["validation_period"] = {"start": "-100d", "end": "-30d"}
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data))
    assert run("create", str(bad)) == 1
    err = capsys.readouterr().err
    assert "Not tags of K-101: K201.TI2041.PV" in err
    assert "overlaps the validation period" in err
    assert "Operating-mode filter 1" in err

    data = json.loads(K101.read_text())
    data["alert_rules"]["sensors"] = [{"tag": "K201.TI2041.PV"}]
    bad.write_text(json.dumps(data))
    assert run("create", str(bad)) == 1
    assert "not a model sensor" in capsys.readouterr().err

    assert run("create", str(tmp_path / "missing.json")) == 1
    assert "Cannot read" in capsys.readouterr().err
    assert run("show", "K-101", "nope") == 1
