"""The failure-mode library and diagnostics on the demo plant (plan 8.2, UC-09, UC-16).

"Done when": K-101's seeded thrust-bearing degradation (from 21 days before the anchor)
ranks thrust-bearing degradation first, for a model trained on healthy data before it; and
(plan 8.4c, AC-06 rehearsal) its alert is worked through a case to a true finding.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from pmp.alerting import AlertRuleSpec, RuleKind, list_alerts, set_alert_rules
from pmp.cases import (
    CaseStatus,
    Outcome,
    add_action,
    close_case,
    complete_action,
    create_case,
    update_case,
)
from pmp.core import Actor, AuditLog, Database, Role, RoleAssignment, create_user
from pmp.demo import PlantSimulator, demo_tags, load_history
from pmp.diagnostics import (
    Direction,
    LibraryError,
    ModeSpec,
    Symptom,
    diagnose,
    import_library,
    list_modes,
    mode_history,
    retire_mode,
    save_mode,
)
from pmp.modelling import (
    Action,
    ModelCache,
    ModelDefinition,
    Period,
    SensorChoice,
    change_status,
    list_active_versions,
    run_training,
    save_draft,
    start_training,
)
from pmp.registry import import_files
from pmp.scoring import score_models

pytestmark = pytest.mark.integration
ACTOR = Actor.system()
DATA = Path(__file__).resolve().parents[3] / "data" / "demo"
ANCHOR = datetime(2026, 9, 1, tzinfo=UTC)
LIBRARY = json.loads((DATA / "library.json").read_text(encoding="utf-8"))


def days_before(a: int, b: int) -> Period:
    return Period(ANCHOR - timedelta(days=a), ANCHOR - timedelta(days=b))


@pytest.fixture(scope="module")
def plant(database: Database, tmp_path_factory: pytest.TempPathFactory) -> Database:
    """The demo registry and 30 days of K-101 history: 9 healthy, then the drift."""
    with database.session() as s:
        s.execute(text("TRUNCATE tag_role_map, tag, asset, type_role, asset_type CASCADE"))
        s.execute(text("TRUNCATE sample"))
        import_files(s, ACTOR, [DATA / "registry" / "registry.xlsx"])
    with database.session() as s:
        tags = [t for t in demo_tags(s) if t.source_name.startswith("K101.")]
    load_history(
        database,
        PlantSimulator(tags, anchor=ANCHOR),
        days=30,
        work_dir=tmp_path_factory.mktemp("history"),
    )
    return database


@pytest.fixture
def library(plant: Database) -> Database:
    with plant.session() as s:
        s.execute(text("TRUNCATE failure_mode RESTART IDENTITY CASCADE"))
        s.execute(text("TRUNCATE model RESTART IDENTITY CASCADE"))
        s.execute(text("TRUNCATE score, sensor_output"))  # version IDs restart: no stale rows
        import_library(s, ACTOR, LIBRARY)
    return plant


def test_the_library_versions_only_real_changes_and_keeps_history(library: Database) -> None:
    with library.session() as s:
        before = int(s.scalar(select(func.count()).select_from(AuditLog)) or 0)
        modes = {m.spec.code: m for m in list_modes(s, "centrifugal_compressor")}
        assert len(modes) == 4
        thrust = modes["thrust_bearing_degradation"]
        assert (thrust.version, thrust.spec.iso_code) == (1, "BRD")
        assert len(thrust.spec.tasks) == 4

        again = import_library(s, ACTOR, LIBRARY)  # nothing changed: no new versions
        assert {m.version for m in again} == {1}
        changed = ModeSpec(
            thrust.spec.code,
            thrust.spec.name,
            (*thrust.spec.symptoms, Symptom("de_vibration_x", Direction.UP, 1)),
            thrust.spec.tasks,
            thrust.spec.iso_code,
        )
        v2 = save_mode(s, ACTOR, "centrifugal_compressor", changed, "add vibration")
        assert v2.version == 2
        assert [v.version for v in mode_history(s, thrust.id)] == [2, 1]
        retire_mode(s, ACTOR, thrust.id, ANCHOR)
        assert "thrust_bearing_degradation" not in {
            m.spec.code for m in list_modes(s, "centrifugal_compressor")
        }
        assert len(list_modes(s, "centrifugal_compressor", include_retired=True)) == 4
        actions = s.scalars(
            select(AuditLog.action)
            .where(AuditLog.entity == "failure_mode", AuditLog.id > before)
            .order_by(AuditLog.id)
        ).all()
    assert list(actions) == ["new_version", "retire"]


def test_a_mode_must_use_the_asset_types_roles(library: Database) -> None:
    spec = ModeSpec("x", "X", (Symptom("rod_drop", Direction.UP, 1),))
    with library.session() as s, pytest.raises(LibraryError, match="no role 'rod_drop'"):
        save_mode(s, ACTOR, "centrifugal_compressor", spec)


def test_the_seeded_thrust_bearing_drift_ranks_its_failure_mode_first(
    library: Database, tmp_path: Path
) -> None:
    k101 = json.loads((DATA / "models" / "k101.json").read_text())
    sensors = tuple(SensorChoice(x["tag"], bool(x.get("required", False))) for x in k101["sensors"])
    definition = ModelDefinition(
        asset_code="K-101",
        name="main",
        sensors=sensors,
        training_periods=(days_before(30, 23),),  # healthy: the drift starts 21 days before
        validation_period=days_before(23, 21),
        mode_filters=("K101.II1001.PV > 120",),
    )
    with library.session() as s:
        model = save_draft(s, ACTOR, definition)
        # low DI limits raised at once, so the drift raises an alert for the case below
        rules = [AlertRuleSpec(RuleKind.DI, 1, 2, persistence_n=1, persistence_m=1)]
        set_alert_rules(s, ACTOR, model.id, rules)
        view, _ = start_training(s, ACTOR, "K-101", "main", queue=False)
    assert run_training(library, view.id, tmp_path)["status"] == "Validated"
    with library.session() as s:
        change_status(s, ACTOR, "K-101", "main", Action.DEPLOY)
        active = list_active_versions(s)
    cache = ModelCache()
    for minutes in range(180, 0, -60):  # three hourly cycles before the anchor
        score_models(library, ANCHOR - timedelta(minutes=minutes), active, cache)

    with library.session() as s:
        found = diagnose(s, model.id)
    ranked = [(d.mode.spec.code, round(d.match.score or 0)) for d in found.modes]
    assert ranked[0][0] == "thrust_bearing_degradation", ranked
    top = found.modes[0]
    assert not top.match.insufficient
    assert {s.symptom.role: s.result.value for s in top.match.symptoms}["axial_displacement"] == (
        "match"
    )
    assert len(top.trend) == 3  # the hourly cycles scored

    # AC-06 rehearsal (plan 8.4c): the alert becomes a case, which is worked and closed
    # as a true finding with the failure mode diagnostics ranked first.
    with library.session() as s:
        s.execute(text("TRUNCATE app_user RESTART IDENTITY CASCADE"))
        create_user(
            s,
            ACTOR,
            username="rel",
            display_name="Reliability engineer",
            password="correct horse battery",
            assignments=[RoleAssignment(Role.ANALYST)],
        )
        engineer = s.execute(text("SELECT id FROM app_user WHERE username = 'rel'")).scalar_one()
        (alert, *_) = list_alerts(s, open_only=True, model_id=model.id)
        case = create_case(s, ACTOR, [alert.id], "K-101 thrust bearing", ANCHOR)
    (snapshot,) = case.snapshot["models"]
    assert snapshot["diagnosis"][0]["code"] == "thrust_bearing_degradation"
    with library.session() as s:
        update_case(s, ACTOR, case.id, assignee_id=engineer, now=ANCHOR)
        acting = add_action(s, ACTOR, case.id, "Inspect the thrust bearing", now=ANCHOR)
        complete_action(s, ACTOR, case.id, acting.actions[0].id, now=ANCHOR)
        closed = close_case(
            s, ACTOR, case.id, Outcome.TRUE_FINDING, top.mode.id, lessons="Axial drift", now=ANCHOR
        )
    assert closed.status is CaseStatus.CLOSED
    assert closed.confirmed_mode_id == top.mode.id
    assert [a.data.get("to") for a in closed.activities if a.type.value == "state_change"] == [
        "Investigating",
        "Action required",
        "Monitoring",
        "Closed",
    ]
