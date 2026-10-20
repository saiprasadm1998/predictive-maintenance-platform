"""Version lifecycle and artefact loading against PostgreSQL (plan 3.3, UC-06, FR-MOD-07,
ARC §8.2)."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from pmp.alerting import AlertRuleSpec, RuleKind, require_di_rule, set_alert_rules
from pmp.core import Actor, AuditLog, Database, EventBus
from pmp.ingestion import Quality, SampleRow, write_samples
from pmp.modelling import (
    Action,
    ArtefactError,
    ModelCache,
    ModelDefinition,
    ModelDeployed,
    ModelError,
    ModelStatusChanged,
    Period,
    SensorChoice,
    VersionStatus,
    change_status,
    get_model,
    load_version,
    run_training,
    save_draft,
    start_training,
)
from pmp.registry import (
    AssetLevel,
    AssetSpec,
    Criticality,
    TagSpec,
    find_tag,
    upsert_asset,
    upsert_tag,
)

pytestmark = pytest.mark.integration
ACTOR = Actor.system()
T0 = datetime(2026, 6, 1, tzinfo=UTC)
DEFINITION = ModelDefinition(
    asset_code="EQ-1",
    name="main",
    sensors=(SensorChoice("EQ1.T1", required=True), SensorChoice("EQ1.T2")),
    training_periods=(Period(T0, T0 + timedelta(days=3)),),
    validation_period=Period(T0 + timedelta(days=3), T0 + timedelta(days=4)),
)


@pytest.fixture
def plant(clean_models: Database) -> Database:
    with clean_models.session() as s:
        s.execute(text("TRUNCATE sample"))
        upsert_asset(s, ACTOR, AssetSpec("SITE-A", "Site A", AssetLevel.SITE))
        upsert_asset(
            s, ACTOR, AssetSpec("EQ-1", "Pump", AssetLevel.EQUIPMENT, "SITE-A", Criticality.A)
        )
        for name in ("EQ1.T1", "EQ1.T2"):
            upsert_tag(s, ACTOR, TagSpec("gw-1", name, "EQ-1", "u", 0.0, 200.0, 60))
    with clean_models.session() as s:
        rows = []
        for k, name in enumerate(("EQ1.T1", "EQ1.T2")):
            tag = find_tag(s, "gw-1", name)
            assert tag is not None
            rows += [
                SampleRow(
                    tag.id,
                    T0 + timedelta(minutes=i),
                    100 + 10 * math.sin(i / 30 + k),
                    Quality.GOOD,
                    None,
                )
                for i in range(4 * 1440)
            ]
        write_samples(s, rows)
    return clean_models


def _trained(db: Database, artefacts: Path, *, di_rule: bool = True) -> int:
    """Save the definition (new Draft), train it to Validated; returns the version number."""
    with db.session() as s:
        model = save_draft(s, ACTOR, DEFINITION)
        if di_rule:
            set_alert_rules(s, ACTOR, model.id, [AlertRuleSpec(RuleKind.DI, 15, 25)])
        view, _ = start_training(s, ACTOR, "EQ-1", "main", queue=False)
    assert run_training(db, view.id, artefacts)["status"] == "Validated"
    return view.version


def _act(db: Database, action: Action, **kwargs: object) -> list[tuple[int, VersionStatus]]:
    with db.session() as s:
        model = change_status(
            s,
            ACTOR,
            "EQ-1",
            "main",
            action,
            deploy_checks=(require_di_rule,),
            **kwargs,  # type: ignore[arg-type]
        )
    return [(v.version, v.status) for v in model.versions]


def test_deploy_pause_resume_supersede_and_retire(plant: Database, tmp_path: Path) -> None:
    _trained(plant, tmp_path)
    bus = EventBus()
    seen: list[object] = []
    bus.subscribe(ModelStatusChanged, seen.append)
    bus.subscribe(ModelDeployed, seen.append)
    with plant.session() as s:  # the audit log is shared with other tests: count from here
        first_audit = s.scalar(select(func.coalesce(func.max(AuditLog.id), 0)))

    with plant.session() as s:
        change_status(s, ACTOR, "EQ-1", "main", Action.DEPLOY, bus=bus)
    assert [type(e).__name__ for e in seen] == ["ModelStatusChanged", "ModelDeployed"]
    assert _act(plant, Action.PAUSE) == [(1, VersionStatus.PAUSED)]
    assert _act(plant, Action.RESUME) == [(1, VersionStatus.DEPLOYED)]

    _trained(plant, tmp_path)  # v2
    seen.clear()
    with plant.session() as s:
        model = change_status(s, ACTOR, "EQ-1", "main", Action.DEPLOY, bus=bus)
    assert [(v.version, v.status) for v in model.versions] == [
        (1, VersionStatus.SUPERSEDED),
        (2, VersionStatus.DEPLOYED),
    ]
    deployed = next(e for e in seen if isinstance(e, ModelDeployed))
    assert deployed.superseded_version_id == model.versions[0].id
    assert [e.action for e in seen if isinstance(e, ModelStatusChanged)] == ["supersede", "deploy"]

    assert _act(plant, Action.PAUSE) == [(1, VersionStatus.SUPERSEDED), (2, VersionStatus.PAUSED)]
    assert _act(plant, Action.RETIRE) == [
        (1, VersionStatus.SUPERSEDED),
        (2, VersionStatus.RETIRED),
    ]
    with plant.session() as s:
        actions = s.scalars(
            select(AuditLog.action)
            .where(AuditLog.entity == "model_version", AuditLog.id > first_audit)
            .order_by(AuditLog.id)
        ).all()
    assert [a for a in actions if a not in ("train_start", "train_validated")] == [
        "deploy",
        "pause",
        "resume",
        "supersede",
        "deploy",
        "pause",
        "retire",
    ]


def test_invalid_transitions_are_refused(plant: Database, tmp_path: Path) -> None:
    with plant.session() as s:
        save_draft(s, ACTOR, DEFINITION)
    with pytest.raises(ModelError, match="only a Validated version can be deployed"):
        _act(plant, Action.DEPLOY)
    with pytest.raises(ModelError, match="no version in service"):
        _act(plant, Action.PAUSE)
    with pytest.raises(ModelError, match="has no version 7"):
        _act(plant, Action.DEPLOY, version=7)
    _trained(plant, tmp_path)
    _act(plant, Action.DEPLOY)
    with pytest.raises(ModelError, match="only a Paused version can be resumed"):
        _act(plant, Action.RESUME)
    with pytest.raises(ModelError, match="only a Validated version can be deployed"):
        _act(plant, Action.DEPLOY, version=1)


def test_deploy_needs_the_di_alert_rule(plant: Database, tmp_path: Path) -> None:
    _trained(plant, tmp_path, di_rule=False)
    with pytest.raises(ModelError, match="Set the DI alert rule first"):
        _act(plant, Action.DEPLOY)
    with plant.session() as s:
        assert get_model(s, "EQ-1", "main").latest.status is VersionStatus.VALIDATED


def test_reject_returns_to_draft_and_clears_the_artefact(plant: Database, tmp_path: Path) -> None:
    _trained(plant, tmp_path)
    with plant.session() as s:
        folder = Path(get_model(s, "EQ-1", "main").latest.artefact_path or "")
    assert folder.is_dir()
    assert _act(plant, Action.REJECT) == [(1, VersionStatus.DRAFT)]
    with plant.session() as s:
        v1 = get_model(s, "EQ-1", "main").latest
    assert (v1.artefact_path, v1.artefact_sha256, v1.metrics) == (None, None, None)
    assert not folder.exists()
    with plant.session() as s:  # the Draft can be changed and trained again
        save_draft(s, ACTOR, replace(DEFINITION, description="retry"))


def test_the_database_allows_one_version_in_service(plant: Database, tmp_path: Path) -> None:
    _trained(plant, tmp_path)
    _act(plant, Action.DEPLOY)
    _trained(plant, tmp_path)
    with pytest.raises(IntegrityError, match="ux_model_version_active"), plant.session() as s:
        s.execute(text("UPDATE model_version SET status = 'Paused' WHERE version = 2"))


def test_a_verified_artefact_loads_with_what_scoring_needs(plant: Database, tmp_path: Path) -> None:
    _trained(plant, tmp_path)
    with plant.session() as s:
        version = get_model(s, "EQ-1", "main").latest
        loaded = load_version(s, version.id)
    assert loaded.sensors == ("EQ1.T1", "EQ1.T2")
    assert loaded.required == {"EQ1.T1"}
    assert loaded.cycle_s == 60
    assert all(loaded.scales[n].range > 0 and loaded.scales[n].sigma > 0 for n in loaded.sensors)
    frame = pd.DataFrame({"EQ1.T1": [0.0], "EQ1.T2": [float("nan")]})
    assert list(loaded.detector.predict(frame).columns) == ["EQ1.T1", "EQ1.T2"]


def test_a_tampered_or_missing_artefact_is_refused(plant: Database, tmp_path: Path) -> None:
    _trained(plant, tmp_path)
    with plant.session() as s:
        version = get_model(s, "EQ-1", "main").latest
    folder = Path(version.artefact_path or "")
    scaling = json.loads((folder / "scaling.json").read_text())
    scaling["sensors"]["EQ1.T1"]["sigma"] *= 10
    (folder / "scaling.json").write_text(json.dumps(scaling))
    with pytest.raises(ArtefactError, match="does not match its checksum"), plant.session() as s:
        load_version(s, version.id)
    (folder / "scaling.json").rename(folder / "moved.json")
    with pytest.raises(ArtefactError, match="does not match"), plant.session() as s:
        load_version(s, version.id)
    folder.rename(folder.with_name("gone"))
    with pytest.raises(ArtefactError, match="is missing"), plant.session() as s:
        load_version(s, version.id)


def test_an_untrained_version_has_nothing_to_load(plant: Database) -> None:
    with plant.session() as s:
        draft = save_draft(s, ACTOR, DEFINITION).latest
    with pytest.raises(ArtefactError, match="no trained artefact"), plant.session() as s:
        load_version(s, draft.id)
    with pytest.raises(ModelError, match="does not exist"), plant.session() as s:
        load_version(s, 999)


def test_the_cache_loads_once_and_reloads_after_a_status_change(
    plant: Database, tmp_path: Path
) -> None:
    _trained(plant, tmp_path)
    bus = EventBus()
    cache = ModelCache(bus)
    with plant.session() as s:
        version_id = get_model(s, "EQ-1", "main").latest.id
        first = cache.get(s, version_id)
        assert cache.get(s, version_id) is first
        assert cache.loads == 1
        change_status(s, ACTOR, "EQ-1", "main", Action.DEPLOY, bus=bus)
        assert len(cache) == 0  # dropped on the status change
        assert cache.get(s, version_id) is not first
    assert cache.loads == 2
