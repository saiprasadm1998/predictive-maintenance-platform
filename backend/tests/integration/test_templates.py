"""Asset-type model templates (plan 8.6, UC-07, FR-MOD-08).

"Done when": applying a template to 10 assets creates 10 draft models and a gap report.
Twelve pumps: eight fully mapped, two without their (optional) vibration tag, two without
the required bearing temperature.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from pmp import cli
from pmp.alerting import RuleKind, list_alert_rules, template_rules_setter
from pmp.core import Actor, Database, get_settings
from pmp.modelling import (
    ModelError,
    TemplateOutcome,
    VersionStatus,
    apply_template,
    find_model,
    list_templates,
    save_template,
)
from pmp.registry import (
    AssetLevel,
    AssetSpec,
    Criticality,
    RoleSpec,
    TagSpec,
    upsert_asset,
    upsert_asset_type,
    upsert_role,
    upsert_tag,
)

pytestmark = pytest.mark.integration
ACTOR = Actor.system()
NOW = datetime(2026, 10, 29, tzinfo=UTC)
DATA = Path(__file__).resolve().parents[3] / "data" / "demo"
ROLES = ("motor_current", "de_bearing_temp", "flow", "de_vibration")
TEMPLATE = {
    "algorithm": "median",  # the template is under test, not the algorithm
    "sensors": [
        {"role": "motor_current", "required": True},
        {"role": "de_bearing_temp", "required": True},
        {"role": "flow"},
        {"role": "de_vibration"},
    ],
    "training_periods": [{"start": "-90d", "end": "-30d"}],
    "validation_period": {"start": "-30d", "end": "-10d"},
    "mode_filters": ["{motor_current} > 90"],
    "alert_rules": {
        "di": {"warning": 20, "alert": 35},
        "sensors": [{"role": "de_bearing_temp", "warning": 3, "alert": 5}],
    },
}


@pytest.fixture
def pumps(clean_models: Database) -> Database:
    with clean_models.session() as s:
        s.execute(text("TRUNCATE model_template RESTART IDENTITY CASCADE"))
        s.execute(text("TRUNCATE job RESTART IDENTITY"))
        upsert_asset_type(s, ACTOR, code="pump", name="Pump")
        for role in ROLES:
            upsert_role(s, ACTOR, "pump", RoleSpec(role, role.replace("_", " ")))
        upsert_asset(s, ACTOR, AssetSpec("SITE", "Site", AssetLevel.SITE))
        for i in range(1, 13):
            code = f"P-{i:02d}"
            upsert_asset(
                s,
                ACTOR,
                AssetSpec(code, f"Pump {i}", AssetLevel.EQUIPMENT, "SITE", Criticality.B, "pump"),
            )
            for role in ROLES:
                if role == "de_vibration" and i in (9, 10):
                    continue  # optional role unmapped: a gap
                if role == "de_bearing_temp" and i in (11, 12):
                    continue  # required role unmapped: skipped
                spec = TagSpec("gw", f"P{i:02d}.{role}", code, "u", 0.0, 100.0, 60)
                upsert_tag(s, ACTOR, spec, role_code=role)
    return clean_models


def test_a_template_creates_a_model_per_eligible_asset_and_reports_gaps(pumps: Database) -> None:
    with pumps.session() as s:
        template = save_template(s, ACTOR, "pump", "standard", TEMPLATE, model_name="tpl")
        assert template.required_roles == ["motor_current", "de_bearing_temp"]
        preview = apply_template(s, ACTOR, template.id, now=NOW, preview=True)
        assert [r.outcome for r in preview].count(TemplateOutcome.READY) == 10
        results = apply_template(
            s, ACTOR, template.id, now=NOW, on_created=template_rules_setter(ACTOR)
        )
    created = [r for r in results if r.outcome is TemplateOutcome.CREATED]
    skipped = {r.asset_code: r for r in results if r.outcome is TemplateOutcome.SKIPPED}
    assert len(created) == 10
    assert all(r.job_id is not None for r in created)  # training queued
    assert set(skipped) == {"P-11", "P-12"}
    assert skipped["P-11"].missing_required == ("de_bearing_temp",)
    assert skipped["P-11"].reason == "required roles not mapped: de_bearing_temp"
    gaps = {r.asset_code: r.missing_optional for r in created if r.missing_optional}
    assert gaps == {"P-09": ("de_vibration",), "P-10": ("de_vibration",)}
    with pumps.session() as s:
        p09 = find_model(s, "P-09", "tpl")
        assert p09 is not None
        assert p09.latest.status is VersionStatus.TRAINING
        assert [x.source_name for x in p09.latest.sensors] == [
            "P09.motor_current",
            "P09.de_bearing_temp",
            "P09.flow",
        ]
        assert p09.latest.mode_filters == ("P09.motor_current > 90",)
        rules = {r.spec.kind: r.spec for r in list_alert_rules(s, p09.id)}
        assert (rules[RuleKind.DI].warning, rules[RuleKind.SENSOR].alert) == (20, 5)
        again = apply_template(s, ACTOR, template.id, ["P-01"], now=NOW)
    assert again[0].reason == "already has a model named 'tpl'"


def test_a_template_must_use_the_types_roles(pumps: Database) -> None:
    bad = {**TEMPLATE, "sensors": [{"role": "rod_drop", "required": True}]}
    with pumps.session() as s, pytest.raises(ModelError, match="no role 'rod_drop'"):
        save_template(s, ACTOR, "pump", "bad", bad)
    bad_filter = {**TEMPLATE, "mode_filters": ["{speed} > 1"]}
    with pumps.session() as s, pytest.raises(ModelError, match="no role 'speed'"):
        save_template(s, ACTOR, "pump", "bad", bad_filter)
    no_period = {k: v for k, v in TEMPLATE.items() if k != "validation_period"}
    with pumps.session() as s, pytest.raises(ModelError):
        save_template(s, ACTOR, "pump", "bad", no_period)


def test_the_demo_template_and_the_command(
    clean_models: Database,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from pmp.registry import import_files

    with clean_models.session() as s:
        s.execute(text("TRUNCATE model_template RESTART IDENTITY CASCADE"))
        import_files(s, ACTOR, [DATA / "registry" / "registry.xlsx"])
    monkeypatch.setenv("PMP_DATABASE_URL", database_url)
    monkeypatch.setenv("PMP_SECRET_KEY", "k")
    monkeypatch.setenv("PMP_LOG_FORMAT", "text")
    get_settings.cache_clear()

    def run(*argv: str) -> int:
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["template", *argv])
        return int(exit_info.value.code or 0)

    try:
        assert run("import", str(DATA / "templates.json")) == 0
        assert run("apply", "centrifugal_pump", "standard", "--preview") == 0
        out = capsys.readouterr().out
        assert "P-205" in out
        assert "gaps: suction_pressure, nde_bearing_temp, de_vibration, nde_vibration" in out
        assert run("apply", "centrifugal_pump", "nope") == 1
    finally:
        get_settings.cache_clear()
    with clean_models.session() as s:
        assert [t.name for t in list_templates(s, "centrifugal_pump")] == ["standard"]
    assert json.loads((DATA / "templates.json").read_text())["templates"][0]["model_name"]
