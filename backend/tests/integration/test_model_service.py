"""Model definitions and alert rules against PostgreSQL (UC-05, FR-MOD-03, FR-ALM-01)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from pmp.alerting import AlertRuleError, AlertRuleSpec, RuleKind, list_alert_rules, set_alert_rules
from pmp.core import Actor, AuditLog, Database
from pmp.modelling import (
    ModelDefinition,
    ModelError,
    Period,
    SensorChoice,
    VersionStatus,
    find_model,
    get_model,
    get_model_by_id,
    list_models,
    save_draft,
)
from pmp.registry import (
    AssetLevel,
    AssetSpec,
    Criticality,
    TagSpec,
    upsert_asset,
    upsert_tag,
)

pytestmark = pytest.mark.integration
ACTOR = Actor.system()
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def days(a: int, b: int) -> Period:
    return Period(T0 + timedelta(days=a), T0 + timedelta(days=b))


DEFINITION = ModelDefinition(
    asset_code="EQ-1",
    name="main",
    description="Pump 1",
    sensors=(SensorChoice("EQ1.T1", required=True), SensorChoice("EQ1.T2"), SensorChoice("EQ1.F1")),
    training_periods=(days(0, 60),),
    validation_period=days(60, 90),
    mode_filters=("EQ1.MOTOR >  120",),
    params={"seed": 3},
)


def _plant(db: Database) -> None:
    with db.session() as s:
        upsert_asset(s, ACTOR, AssetSpec("SITE-A", "Site A", AssetLevel.SITE))
        for code in ("EQ-1", "EQ-2"):
            upsert_asset(
                s, ACTOR, AssetSpec(code, code, AssetLevel.EQUIPMENT, "SITE-A", Criticality.A)
            )
        for name in ("EQ1.T1", "EQ1.T2", "EQ1.F1", "EQ1.MOTOR"):
            upsert_tag(s, ACTOR, TagSpec("gw-1", name, "EQ-1", "u", 0.0, 200.0, 60))
        upsert_tag(s, ACTOR, TagSpec("gw-1", "EQ2.T1", "EQ-2", "u", 0.0, 200.0, 60))


def _audits(db: Database, entity: str) -> list[AuditLog]:
    with db.session() as s:
        rows = s.scalars(select(AuditLog).where(AuditLog.entity == entity).order_by(AuditLog.id))
        result = list(rows.all())
        s.expunge_all()
    return result


def test_a_model_is_created_with_a_draft_version_one(clean_models: Database) -> None:
    _plant(clean_models)
    with clean_models.session() as s:
        model = save_draft(s, ACTOR, DEFINITION)
    assert (model.asset_code, model.name, model.description) == ("EQ-1", "main", "Pump 1")
    v1 = model.latest
    assert (v1.version, v1.status, v1.algorithm, v1.params) == (
        1,
        VersionStatus.DRAFT,
        "median",
        {"seed": 3},
    )
    assert [(s.source_name, s.required) for s in v1.sensors] == [
        ("EQ1.T1", True),
        ("EQ1.T2", False),
        ("EQ1.F1", False),
    ]
    assert v1.training_periods == (days(0, 60),)
    assert v1.validation_period == days(60, 90)
    assert v1.mode_filters == ("EQ1.MOTOR > 120",)  # stored in canonical form
    audit = _audits(clean_models, "model")[-1]
    assert audit.action == "create"
    assert audit.before_after["after"]["sensors"][0] == {"tag": "EQ1.T1", "required": True}


def test_saving_again_updates_the_draft_then_starts_a_new_version(clean_models: Database) -> None:
    _plant(clean_models)
    with clean_models.session() as s:
        save_draft(s, ACTOR, DEFINITION)
        changed = save_draft(s, ACTOR, replace(DEFINITION, sensors=DEFINITION.sensors[:2]))
    assert len(changed.versions) == 1
    assert len(changed.latest.sensors) == 2

    with clean_models.session() as s:  # training (3.2) will do this
        s.execute(text("UPDATE model_version SET status = 'Validated'"))
    with clean_models.session() as s:
        model = save_draft(s, ACTOR, DEFINITION)
    assert [(v.version, v.status) for v in model.versions] == [
        (1, VersionStatus.VALIDATED),
        (2, VersionStatus.DRAFT),
    ]
    assert len(model.versions[0].sensors) == 2  # the validated version is untouched
    assert len(model.latest.sensors) == 3
    actions = [a.action for a in _audits(clean_models, "model")]
    assert actions[-3:] == ["create", "update_draft", "new_version"]
    assert (
        _audits(clean_models, "model")[-2].before_after["before"]["sensors"][2]["tag"] == "EQ1.F1"
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"asset_code": "NOPE"}, "Asset 'NOPE' does not exist"),
        ({"sensors": (SensorChoice("EQ2.T1"),)}, "Not tags of EQ-1: EQ2.T1"),
        ({"validation_period": days(30, 70)}, "overlaps the validation period"),
        ({"mode_filters": ("EQ2.T1 > 1",)}, "names tags not on EQ-1"),
        ({"algorithm": "xgboost"}, "Unknown or refused algorithm"),
    ],
)
def test_invalid_definitions_save_nothing(
    clean_models: Database, change: dict[str, object], message: str
) -> None:
    _plant(clean_models)
    with pytest.raises(ModelError, match=message), clean_models.session() as s:
        save_draft(s, ACTOR, replace(DEFINITION, **change))  # type: ignore[arg-type]
    with clean_models.session() as s:
        assert s.scalar(select(func.count()).select_from(text("model"))) == 0


def test_models_are_found_and_listed(clean_models: Database) -> None:
    _plant(clean_models)
    with clean_models.session() as s:
        created = save_draft(s, ACTOR, DEFINITION)
        save_draft(s, ACTOR, replace(DEFINITION, name="bearings", sensors=DEFINITION.sensors[:1]))
    with clean_models.session() as s:
        assert get_model(s, "EQ-1", "main") == created
        assert get_model_by_id(s, created.id) == created
        assert find_model(s, "EQ-1", "other") is None
        assert find_model(s, "NOPE", "main") is None
        assert [m.name for m in list_models(s)] == ["main", "bearings"]
        assert [m.name for m in list_models(s, "EQ-2")] == []
        with pytest.raises(ModelError, match="No model 'other'"):
            get_model(s, "EQ-1", "other")
        with pytest.raises(ModelError, match="Asset 'NOPE'"):
            list_models(s, "NOPE")
        with pytest.raises(ModelError, match="Model 999"):
            get_model_by_id(s, 999)


# ------------------------------------------------------------------ alert rules


def test_alert_rules_are_created_changed_and_removed_with_audit(clean_models: Database) -> None:
    _plant(clean_models)
    with clean_models.session() as s:
        model = save_draft(s, ACTOR, DEFINITION)
    t1, t2 = model.latest.sensors[0].tag_id, model.latest.sensors[1].tag_id
    di = AlertRuleSpec(RuleKind.DI, 15, 25)
    with clean_models.session() as s:
        rules = set_alert_rules(
            s, ACTOR, model.id, [di, AlertRuleSpec(RuleKind.SENSOR, 3, 5, tag_id=t1)]
        )
    assert [r.spec.kind for r in rules] == [RuleKind.DI, RuleKind.SENSOR]

    with clean_models.session() as s:
        set_alert_rules(
            s,
            ACTOR,
            model.id,
            [
                replace(di, alert=30, persistence_n=2),
                AlertRuleSpec(RuleKind.SENSOR, 3, 5, tag_id=t2),
            ],
        )
    with clean_models.session() as s:
        rules = list_alert_rules(s, model.id)
    assert rules[0].spec == replace(di, alert=30, persistence_n=2)
    assert [r.spec.tag_id for r in rules[1:]] == [t2]

    actions = [(a.action, a.entity_id) for a in _audits(clean_models, "alert_rule")][-5:]
    assert actions == [
        ("create", f"{model.id}:di"),
        ("create", f"{model.id}:sensor:{t1}"),
        ("remove", f"{model.id}:sensor:{t1}"),
        ("update", f"{model.id}:di"),
        ("create", f"{model.id}:sensor:{t2}"),
    ]

    before = len(_audits(clean_models, "alert_rule"))
    with clean_models.session() as s:  # the same rules again change nothing
        set_alert_rules(s, ACTOR, model.id, [r.spec for r in rules])
    assert len(_audits(clean_models, "alert_rule")) == before


@pytest.mark.parametrize(
    ("rules", "message"),
    [
        (
            [AlertRuleSpec(RuleKind.DI, 15, 25), AlertRuleSpec(RuleKind.DI, 10, 20)],
            "at most one DI rule",
        ),
        ("twice", "same tag"),
        ("foreign", "not model sensors"),
    ],
)
def test_invalid_rule_sets_are_refused(clean_models: Database, rules: object, message: str) -> None:
    _plant(clean_models)
    with clean_models.session() as s:
        model = save_draft(s, ACTOR, DEFINITION)
        foreign = s.scalar(text("SELECT id FROM tag WHERE source_name = 'EQ2.T1'"))
    t1 = model.latest.sensors[0].tag_id
    if rules == "twice":
        rules = [AlertRuleSpec(RuleKind.SENSOR, 3, 5, tag_id=t1)] * 2
    elif rules == "foreign":
        rules = [AlertRuleSpec(RuleKind.SENSOR, 3, 5, tag_id=int(foreign or 0))]
    with pytest.raises(AlertRuleError, match=message), clean_models.session() as s:
        set_alert_rules(s, ACTOR, model.id, rules)  # type: ignore[arg-type]


def test_rules_for_an_unknown_model_are_refused(clean_models: Database) -> None:
    with pytest.raises(AlertRuleError, match="Model 42"), clean_models.session() as s:
        set_alert_rules(s, ACTOR, 42, [])


def test_the_database_enforces_one_di_rule_per_model(clean_models: Database) -> None:
    _plant(clean_models)
    with clean_models.session() as s:
        model = save_draft(s, ACTOR, DEFINITION)
    insert = text(
        "INSERT INTO alert_rule (model_id, kind, warning, alert) VALUES (:m, 'di', 15, 25)"
    )
    with clean_models.session() as s:
        s.execute(insert, {"m": model.id})
    with pytest.raises(Exception, match="ux_alert_rule_di"), clean_models.session() as s:
        s.execute(insert, {"m": model.id})
