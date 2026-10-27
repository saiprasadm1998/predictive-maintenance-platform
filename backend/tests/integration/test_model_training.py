"""Baseline training on the demo plant (plan 3.2 "Done when"; UC-05 steps 3, 7, 8, 6a, 7a).

Six days of synthetic K-101 history: training on days 6 to 2 before the anchor,
validation on the last 2 days.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text

from pmp.core import Actor, AuditLog, Database, JobRegistry, Worker
from pmp.demo import PlantSimulator, demo_tags, load_history
from pmp.modelling import (
    TRAIN_JOB,
    ModelDefinition,
    ModelError,
    Period,
    SensorChoice,
    VersionStatus,
    get_model,
    make_training_failure_handler,
    make_training_handler,
    run_training,
    save_draft,
    start_training,
)
from pmp.modelling.artefacts import folder_digest
from pmp.registry import import_files

pytestmark = pytest.mark.integration
ACTOR = Actor.system()
DATA = Path(__file__).resolve().parents[3] / "data" / "demo"
ANCHOR = datetime(2026, 9, 1, tzinfo=UTC)
K101 = json.loads((DATA / "models" / "k101.json").read_text())


def days_before(a: int, b: int) -> Period:
    return Period(ANCHOR - timedelta(days=a), ANCHOR - timedelta(days=b))


DEFINITION = ModelDefinition(
    algorithm="median",  # pipeline mechanics: the fixed, predictable placeholder
    asset_code="K-101",
    name="main",
    sensors=tuple(SensorChoice(s["tag"], bool(s.get("required", False))) for s in K101["sensors"]),
    training_periods=(days_before(6, 2),),
    validation_period=days_before(2, 0),
    mode_filters=tuple(K101["mode_filters"]),
)


@pytest.fixture(scope="module")
def plant(database: Database, tmp_path_factory: pytest.TempPathFactory) -> Database:
    """The demo registry and 6 days of history, loaded once for this module."""
    with database.session() as s:
        s.execute(text("TRUNCATE tag_role_map, tag, asset, type_role, asset_type CASCADE"))
        s.execute(text("TRUNCATE sample"))
        import_files(s, ACTOR, [DATA / "registry" / "registry.xlsx"])
    with database.session() as s:
        tags = [t for t in demo_tags(s) if t.source_name.startswith("K101.")]
    load_history(
        database,
        PlantSimulator(tags, anchor=ANCHOR),
        days=6,
        work_dir=tmp_path_factory.mktemp("history"),
    )
    return database


@pytest.fixture
def models(plant: Database, tmp_path: Path) -> tuple[Database, Path]:
    with plant.session() as s:
        s.execute(text("TRUNCATE model RESTART IDENTITY CASCADE"))
        s.execute(text("TRUNCATE job RESTART IDENTITY"))
    return plant, tmp_path / "artefacts"


def _audit_actions(db: Database) -> list[str]:
    with db.session() as s:
        return list(
            s.scalars(
                select(AuditLog.action)
                .where(AuditLog.entity == "model_version")
                .order_by(AuditLog.id)
            ).all()
        )[-2:]


def test_k101_trains_on_demo_history_and_reaches_validated(
    models: tuple[Database, Path],
) -> None:
    db, artefacts = models
    with db.session() as s:
        save_draft(s, ACTOR, DEFINITION)
        view, job_id = start_training(s, ACTOR, "K-101", "main")
    assert view.status is VersionStatus.TRAINING
    assert view.params == {"seed": 42, "cycle_s": 60}
    assert job_id is not None

    registry = JobRegistry()
    registry.register(TRAIN_JOB, make_training_handler(db, artefacts))
    assert Worker(db, registry).run_once()

    with db.session() as s:
        model = get_model(s, "K-101", "main")
    v1 = model.latest
    assert v1.status is VersionStatus.VALIDATED, v1.error
    assert v1.metrics is not None
    assert v1.metrics["training_cycles"] == 4 * 1440
    assert v1.metrics["training_retained"] >= 2000
    assert v1.metrics["validation_retained"] > 0
    folder = Path(v1.artefact_path or "")
    assert folder == artefacts / "models" / str(model.id) / "1"
    assert v1.artefact_sha256 == folder_digest(folder)

    scaling = json.loads((folder / "scaling.json").read_text())
    assert len(scaling["sensor_order"]) == 18
    for stats in scaling["sensors"].values():  # what q and z need
        assert stats["range"] > 0
        assert stats["sigma"] > 0
    manifest = json.loads((folder / "manifest.json").read_text())
    assert (manifest["algorithm"], manifest["seed"], manifest["cycle_s"]) == ("median", 42, 60)
    assert len(manifest["definition_sha256"]) == 64
    assert _audit_actions(db) == ["train_start", "train_validated"]


def test_training_is_reproducible_with_the_same_seed(models: tuple[Database, Path]) -> None:
    db, artefacts = models
    folders = []
    for _ in range(2):  # v1, then v2 from the same definition
        with db.session() as s:
            save_draft(s, ACTOR, DEFINITION)
            view, _ = start_training(s, ACTOR, "K-101", "main", queue=False)
        assert run_training(db, view.id, artefacts)["status"] == "Validated"
        with db.session() as s:
            folders.append(Path(get_model(s, "K-101", "main").latest.artefact_path or ""))
    assert folders[0] != folders[1]
    for name in ("scaling.json", "validation.json", "algorithm/median.json"):
        assert (folders[0] / name).read_text() == (folders[1] / name).read_text()


def test_too_little_data_fails_with_the_reason_then_can_be_fixed(
    models: tuple[Database, Path],
) -> None:
    db, artefacts = models
    short = replace(DEFINITION, training_periods=(days_before(4, 3),))  # 1,440 cycles
    with db.session() as s:
        save_draft(s, ACTOR, short)
        view, _ = start_training(s, ACTOR, "K-101", "main", queue=False)
    result = run_training(db, view.id, artefacts)
    assert result["status"] == "Failed"
    with db.session() as s:
        failed = get_model(s, "K-101", "main").latest
    assert failed.status is VersionStatus.FAILED
    assert "at least 2,000 are needed" in (failed.error or "")
    assert _audit_actions(db) == ["train_start", "train_failed"]
    assert not (artefacts / "models").exists()

    with db.session() as s:  # Failed -> Draft: fix the configuration and train again
        fixed = save_draft(s, ACTOR, DEFINITION)
    assert [(v.version, v.status) for v in fixed.versions] == [(1, VersionStatus.DRAFT)]
    assert fixed.latest.error is None


def test_only_a_draft_can_be_trained_and_reruns_are_skipped(
    models: tuple[Database, Path],
) -> None:
    db, artefacts = models
    with db.session() as s:
        save_draft(s, ACTOR, DEFINITION)
        view, _ = start_training(s, ACTOR, "K-101", "main", queue=False)
    with pytest.raises(ModelError, match="is Training; only a Draft"), db.session() as s:
        start_training(s, ACTOR, "K-101", "main")
    run_training(db, view.id, artefacts)
    assert run_training(db, view.id, artefacts) == {"skipped": "version is Validated"}
    assert "does not exist" in run_training(db, 999, artefacts)["skipped"]


def test_k101_is_scored_live_after_deployment(models: tuple[Database, Path]) -> None:
    """Plan 4.1 "Done when" on the demo plant: K-101 scores, and the TI-1018 flatline
    planted 6 hours before the anchor is excluded without stopping the model."""
    from pmp.alerting import AlertRuleSpec, RuleKind, set_alert_rules
    from pmp.modelling import Action, ModelCache, change_status, list_active_versions
    from pmp.scoring import Band, RuntimeStatus, score_models

    db, artefacts = models
    with db.session() as s:
        model = save_draft(s, ACTOR, DEFINITION)
        set_alert_rules(s, ACTOR, model.id, [AlertRuleSpec(RuleKind.DI, 15, 25)])
        view, _ = start_training(s, ACTOR, "K-101", "main", queue=False)
    assert run_training(db, view.id, artefacts)["status"] == "Validated"
    with db.session() as s:
        change_status(s, ACTOR, "K-101", "main", Action.DEPLOY)
        active = list_active_versions(s)

    result = score_models(db, ANCHOR - timedelta(hours=1), active, ModelCache())[0]
    assert result.status is RuntimeStatus.RUNNING, result.reason
    assert result.output is not None
    assert result.output.band in (Band.HEALTHY, Band.WATCH, Band.ALERT)
    excluded = [s.tag for s in result.output.sensors if not s.usable]
    assert "K101.TI1018.PV" in excluded
    assert result.output.coverage >= 0.7


def test_a_training_job_lost_for_good_leaves_the_version_failed(
    models: tuple[Database, Path],
) -> None:
    """ARC Figure 7: Training ends Validated or Failed, even if the worker keeps dying."""
    db, _ = models
    with db.session() as s:
        save_draft(s, ACTOR, DEFINITION)
        view, _ = start_training(s, ACTOR, "K-101", "main", queue=False)
    make_training_failure_handler(db)({"version_id": view.id}, "worker lost: lock expired")
    with db.session() as s:
        version = get_model(s, "K-101", "main").latest
    assert version.status is VersionStatus.FAILED
    assert version.error == "Training job failed: worker lost: lock expired"


def _validation_nrmse(folder: Path) -> float:
    report = json.loads((folder / "validation.json").read_text())
    values = [float(s["nrmse"]) for s in report["sensors"].values()]
    return sum(values) / len(values)


def test_aakr_trains_calibrates_and_beats_the_placeholder(models: tuple[Database, Path]) -> None:
    """Plan 7.1: the same K-101 definition trained with AAKR is validated, calibrated on the
    validation period, and predicts the hold-out clearly better than the training medians."""
    db, artefacts = models
    registry = JobRegistry()
    registry.register(TRAIN_JOB, make_training_handler(db, artefacts))
    for name, algorithm in (("placeholder", "median"), ("aakr", "aakr")):
        with db.session() as s:
            save_draft(s, ACTOR, replace(DEFINITION, name=name, algorithm=algorithm))
            start_training(s, ACTOR, "K-101", name)
        assert Worker(db, registry).run_once()
    with db.session() as s:
        median = get_model(s, "K-101", "placeholder").latest
        aakr = get_model(s, "K-101", "aakr").latest
    assert aakr.status is VersionStatus.VALIDATED, aakr.error
    assert aakr.metrics is not None
    learnt = aakr.metrics["detector"]
    assert learnt["calibrated"]
    assert 200 <= learnt["memory_vectors"] <= 1000
    report = aakr.metrics["validation"]  # plan 7.3, kept with the version
    assert set(report["di_percentiles"]) == {"P50", "P95", "P99", "P99.9"}
    proposed = report["proposed"]
    assert proposed["di_alert"] >= max(10.0, proposed["di_warning"])  # UCS §6.4 minimum
    assert 0 <= report["outside_envelope"] <= 0.05  # the hold-out is normal operation
    assert report["alerts_per_week"] >= 0
    assert len(report["sensors"]) == 18  # every K-101 sensor
    assert all(v["nrmse"] >= 0 for v in report["sensors"].values())
    folder = Path(aakr.artefact_path or "")
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["algorithm"] == "aakr"
    # The demo plant adds independent noise per sensor, which no model can predict: AAKR
    # still removes well over a third of the error the medians leave.
    assert _validation_nrmse(folder) < 0.7 * _validation_nrmse(Path(median.artefact_path or ""))
