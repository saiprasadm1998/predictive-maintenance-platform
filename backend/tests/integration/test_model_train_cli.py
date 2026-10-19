"""`pmp model train --now` end to end with the demo registry and a short history."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text

from pmp import cli
from pmp.core import Actor, Database, get_settings
from pmp.demo import PlantSimulator, demo_tags, load_history
from pmp.registry import import_files

pytestmark = pytest.mark.integration
DATA = Path(__file__).resolve().parents[3] / "data" / "demo"


@pytest.fixture
def k101_file(
    clean_models: Database,
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    monkeypatch.setenv("PMP_DATABASE_URL", database_url)
    monkeypatch.setenv("PMP_SECRET_KEY", "k")
    monkeypatch.setenv("PMP_LOG_FORMAT", "text")
    monkeypatch.setenv("PMP_ARTEFACT_DIR", str(tmp_path / "artefacts"))
    get_settings.cache_clear()
    with clean_models.session() as s:
        s.execute(text("TRUNCATE sample"))
        import_files(s, Actor.system(), [DATA / "registry" / "registry.xlsx"])
    with clean_models.session() as s:
        tags = [t for t in demo_tags(s) if t.source_name.startswith("K101.")]
    load_history(clean_models, PlantSimulator(tags), days=5, work_dir=tmp_path / "work")
    data = json.loads((DATA / "models" / "k101.json").read_text())
    data["training_periods"] = [{"start": "-5d", "end": "-1d"}]
    data["validation_period"] = {"start": "-1d", "end": "-0d"}
    path = tmp_path / "k101.json"
    path.write_text(json.dumps(data))
    yield path
    get_settings.cache_clear()


def run(*args: str) -> int:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["model", *args])
    return int(exit_info.value.code or 0)


def test_train_now_and_queued(k101_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("create", str(k101_file)) == 0
    assert run("train", "K-101", "main", "--now") == 0
    out = capsys.readouterr().out
    assert "v1  Validated" in out
    assert "Artefact:" in out
    assert "trained on" in out

    assert run("train", "K-101", "main") == 1  # v1 is no longer a Draft
    assert "only a Draft can be trained" in capsys.readouterr().err

    assert run("create", str(k101_file)) == 0  # starts Draft v2
    assert run("train", "K-101", "main") == 0
    assert "queued. The worker runs it" in capsys.readouterr().out
