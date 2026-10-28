"""Data-quality services against PostgreSQL: versioned rules, statuses, events, preview.

UC-04 (configure rules, preview, versioned and audited) and FR-DQ-02 (one current NE 107
category per sensor, with the rule that set it).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from pmp.core import Actor, AuditLog, Database, EventBus
from pmp.dataquality import (
    DataQualityError,
    ExclusionKind,
    Ne107,
    Reference,
    Rule,
    RuleScope,
    SensorStatusChanged,
    add_exclusion,
    effective_params,
    end_exclusion,
    evaluate_sensors,
    get_rule_set,
    get_sensor_statuses,
    list_exclusions,
    list_rule_versions,
    preview_rules,
    save_rule_set,
)
from pmp.ingestion import Quality, SampleRow, write_samples
from pmp.registry import (
    AssetLevel,
    AssetSpec,
    Criticality,
    RoleSpec,
    TagSpec,
    find_tag,
    upsert_asset,
    upsert_asset_type,
    upsert_role,
    upsert_tag,
)

pytestmark = pytest.mark.integration
ACTOR = Actor.system()
T0 = datetime(2026, 9, 1, tzinfo=UTC)


def _plant(db: Database) -> tuple[int, int]:
    """EQ-1 (a pump) with FLOW (role 'flow') and TEMP (no role). Returns their tag IDs."""
    with db.session() as s:
        upsert_asset_type(s, ACTOR, code="pump", name="Pump")
        upsert_role(s, ACTOR, "pump", RoleSpec("flow", "Flow", "m3/h"))
        upsert_asset(s, ACTOR, AssetSpec("SITE-A", "Site A", AssetLevel.SITE))
        upsert_asset(
            s,
            ACTOR,
            AssetSpec("EQ-1", "Pump 1", AssetLevel.EQUIPMENT, "SITE-A", Criticality.B, "pump"),
        )
        for name, role in (("FLOW", "flow"), ("TEMP", None)):
            spec = TagSpec("gw-1", name, "EQ-1", "u", 0.0, 100.0, 60)
            upsert_tag(s, ACTOR, spec, role_code=role)
    with db.session() as s:
        flow, temp = find_tag(s, "gw-1", "FLOW"), find_tag(s, "gw-1", "TEMP")
        assert flow is not None
        assert temp is not None
        return flow.id, temp.id


def _write(db: Database, tag_id: int, points: Iterable[tuple[datetime, float, Quality]]) -> None:
    with db.session() as s:
        write_samples(s, (SampleRow(tag_id, ts, v, q, None) for ts, v, q in points))


def _healthy(start: datetime, minutes: int) -> list[tuple[datetime, float, Quality]]:
    return [
        (start + timedelta(minutes=i), 50.0 + 3.0 * math.sin(i / 3), Quality.GOOD)
        for i in range(minutes)
    ]


# ------------------------------------------------------------------ rule sets


def test_saving_creates_versions_and_audit_entries(clean_dq: Database) -> None:
    _plant(clean_dq)
    scope = RuleScope.everywhere()
    with clean_dq.session() as s:
        assert get_rule_set(s, scope).version == 0
        audit_start = s.scalar(select(func.coalesce(func.max(AuditLog.id), 0)))
        first = save_rule_set(s, ACTOR, scope, {"spike_pct": "30"}, "noisy plant")
        again = save_rule_set(s, ACTOR, scope, {"spike_pct": 30})  # same: no new version
        second = save_rule_set(s, ACTOR, scope, {"spike_pct": 35, "flatline": "off"})
        cleared = save_rule_set(s, ACTOR, scope, {})
    assert (first.version, again.version, second.version, cleared.version) == (1, 1, 2, 3)
    with clean_dq.session() as s:
        history = list_rule_versions(s, scope)
        assert [v.version for v in history] == [3, 2, 1]
        assert history[1].overrides == {"spike_pct": 35.0, "flatline": False}
        assert history[2].comment == "noisy plant"
        audits = s.scalars(
            select(AuditLog)
            .where(AuditLog.entity == "dq_rule", AuditLog.id > audit_start)
            .order_by(AuditLog.id)
        ).all()
    assert [a.entity_id for a in audits] == ["global:"] * 3
    assert audits[0].before_after["before"] is None
    assert audits[1].before_after["before"]["params"] == {"spike_pct": 30.0}
    assert audits[1].before_after["after"]["version"] == 2


@pytest.mark.parametrize(
    ("scope", "message"),
    [
        (RuleScope.role("compressor", "flow"), "Asset type 'compressor' does not exist"),
        (RuleScope.role("pump", "speed"), "has no role 'speed'"),
        (RuleScope.tag(999), "Tag '999' does not exist"),
    ],
)
def test_unknown_scopes_are_refused(clean_dq: Database, scope: RuleScope, message: str) -> None:
    _plant(clean_dq)
    with pytest.raises(DataQualityError, match=message), clean_dq.session() as s:
        save_rule_set(s, ACTOR, scope, {"spike_pct": 30})


def test_invalid_parameters_save_nothing(clean_dq: Database) -> None:
    _plant(clean_dq)
    with pytest.raises(DataQualityError), clean_dq.session() as s:
        save_rule_set(s, ACTOR, RuleScope.everywhere(), {"spike_pct": -1})
    with clean_dq.session() as s:
        assert get_rule_set(s, RuleScope.everywhere()).version == 0


def test_overrides_layer_global_then_role_then_tag(clean_dq: Database) -> None:
    flow, temp = _plant(clean_dq)
    with clean_dq.session() as s:
        save_rule_set(s, ACTOR, RuleScope.everywhere(), {"spike_pct": 30, "stale_factor": 4})
        save_rule_set(s, ACTOR, RuleScope.role("pump", "flow"), {"spike_pct": 35})
        save_rule_set(s, ACTOR, RuleScope.tag(flow), {"spike_pct": 40})
    with clean_dq.session() as s:
        flow_params, temp_params = effective_params(s, flow), effective_params(s, temp)
    assert (flow_params.spike_pct, flow_params.stale_factor) == (40.0, 4.0)
    assert (temp_params.spike_pct, temp_params.stale_factor) == (30.0, 4.0)


# ------------------------------------------------------------------ evaluation


def test_statuses_are_stored_and_events_published_on_change(clean_dq: Database) -> None:
    flow, temp = _plant(clean_dq)
    _write(clean_dq, flow, _healthy(T0, 40))
    _write(clean_dq, temp, _healthy(T0, 40))
    bus = EventBus()
    seen: list[SensorStatusChanged] = []
    bus.subscribe(SensorStatusChanged, seen.append)
    first_cycle = T0 + timedelta(minutes=39, seconds=30)

    with clean_dq.session() as s:
        states = evaluate_sensors(s, first_cycle, bus=bus)
    assert {t: st.status for t, st in states.items()} == {flow: Ne107.GOOD, temp: Ne107.GOOD}
    assert [(e.tag_id, e.previous) for e in seen] == [(flow, None), (temp, None)]

    seen.clear()
    with clean_dq.session() as s:
        evaluate_sensors(s, first_cycle + timedelta(minutes=1), bus=bus)
    assert seen == []  # nothing changed

    _write(clean_dq, flow, [(T0 + timedelta(minutes=40), 51.0, Quality.BAD)])
    bad_cycle = T0 + timedelta(minutes=40, seconds=30)
    with clean_dq.session() as s:
        evaluate_sensors(s, bad_cycle, [flow], bus=bus)
    assert [(e.tag_id, e.previous, e.status, e.rule) for e in seen] == [
        (flow, Ne107.GOOD, Ne107.FAILURE, Rule.BAD_QUALITY)
    ]
    with clean_dq.session() as s:
        views = {v.source_name: v for v in get_sensor_statuses(s)}
    assert views["FLOW"].status is Ne107.FAILURE
    assert views["FLOW"].rule is Rule.BAD_QUALITY
    assert views["FLOW"].since == bad_cycle
    assert views["TEMP"].since == first_cycle  # unchanged since its first evaluation
    assert views["TEMP"].evaluated_at == first_cycle + timedelta(minutes=1)
    assert views["FLOW"].asset_code == "EQ-1"


def test_a_tag_without_samples_is_stale(clean_dq: Database) -> None:
    flow, _ = _plant(clean_dq)
    with clean_dq.session() as s:
        state = evaluate_sensors(s, T0, [flow])[flow]
    assert (state.status, state.rule) == (Ne107.FAILURE, Rule.STALE)


def _exclude(
    db: Database, tag_id: int, start: datetime, end: datetime, cleared: datetime | None
) -> None:
    with db.session() as s:
        s.execute(
            text(
                "INSERT INTO sensor_exclusion (tag_id, reason, starts_at, expires_at, cleared_at) "
                "VALUES (:tag, 'calibration', :start, :end, :cleared)"
            ),
            {"tag": tag_id, "start": start, "end": end, "cleared": cleared},
        )


def test_manual_exclusions_are_read_until_they_expire_or_are_cleared(clean_dq: Database) -> None:
    flow, temp = _plant(clean_dq)
    _write(clean_dq, flow, _healthy(T0, 120))
    _write(clean_dq, temp, _healthy(T0, 120))
    _exclude(clean_dq, flow, T0, T0 + timedelta(minutes=60), None)
    _exclude(clean_dq, temp, T0, T0 + timedelta(minutes=60), T0 + timedelta(minutes=45))

    def rules_at(minute: int) -> dict[int, Rule]:
        with clean_dq.session() as s:
            states = evaluate_sensors(s, T0 + timedelta(minutes=minute))
        return {t: st.rule for t, st in states.items()}

    assert rules_at(40) == {flow: Rule.MANUAL_EXCLUSION, temp: Rule.MANUAL_EXCLUSION}
    assert rules_at(50) == {flow: Rule.MANUAL_EXCLUSION, temp: Rule.NONE}  # temp cleared
    assert rules_at(61) == {flow: Rule.NONE, temp: Rule.NONE}  # flow expired


def test_training_statistics_replace_the_instrument_range(clean_dq: Database) -> None:
    flow, _ = _plant(clean_dq)
    points = [
        *_healthy(T0, 38),
        (T0 + timedelta(minutes=38), 50.0, Quality.GOOD),
        (T0 + timedelta(minutes=39), 56.0, Quality.GOOD),
    ]
    _write(clean_dq, flow, points)
    at = T0 + timedelta(minutes=39)
    with clean_dq.session() as s:
        plain = evaluate_sensors(s, at, [flow])[flow]
        trained = evaluate_sensors(s, at, [flow], references={flow: Reference(range=20.0)})[flow]
    assert plain.rule is Rule.NONE  # a 6-unit jump is 6 % of the instrument range
    assert trained.rule is Rule.SPIKE  # but 30 % of the training range


# ------------------------------------------------------------------ preview


def test_preview_warns_above_twenty_percent_and_saves_nothing(clean_dq: Database) -> None:
    flow, temp = _plant(clean_dq)
    day = 24 * 60
    _write(clean_dq, temp, _healthy(T0, 2 * day))
    # FLOW is healthy for the first day, then stuck at one value for the second
    stuck = [(T0 + timedelta(minutes=i), 42.0, Quality.GOOD) for i in range(day, 2 * day)]
    _write(clean_dq, flow, _healthy(T0, day) + stuck)
    end = T0 + timedelta(days=2)

    with clean_dq.session() as s:
        report = preview_rules(s, RuleScope.everywhere(), days=2, end=end)
        by_name = {t.source_name: t for t in report.tags}
        assert by_name["TEMP"].excluded_share == 0.0
        assert 0.45 < by_name["FLOW"].excluded_share < 0.5  # flatline after 30 stuck samples
        assert by_name["FLOW"].by_rule[Rule.FLATLINE] == by_name["FLOW"].excluded
        assert report.warning
        assert [t.source_name for t in report.over_limit] == ["FLOW"]
        assert "WARNING" in report.summary()

        relaxed = preview_rules(s, RuleScope.tag(flow), {"flatline_used": "on"}, days=2, end=end)
        assert [t.source_name for t in relaxed.tags] == ["FLOW"]
        assert not relaxed.warning  # flatlined but still used
        assert get_rule_set(s, RuleScope.tag(flow)).version == 0


def test_preview_covers_only_the_scope(clean_dq: Database) -> None:
    _plant(clean_dq)
    with clean_dq.session() as s:
        report = preview_rules(s, RuleScope.role("pump", "flow"), days=1, end=T0)
    assert [t.source_name for t in report.tags] == ["FLOW"]
    assert report.tags[0].by_rule[Rule.STALE] == report.tags[0].cycles == 1440


# ------------------------------------------------------------------ exclusions (8.1, UC-14)


def _audit_after(db: Database, after: int) -> list[str]:
    with db.session() as s:
        return list(
            s.scalars(
                select(AuditLog.action)
                .where(AuditLog.entity == "sensor_exclusion", AuditLog.id > after)
                .order_by(AuditLog.id)
            ).all()
        )


def _audit_mark(db: Database) -> int:
    with db.session() as s:
        return int(s.scalar(select(func.coalesce(func.max(AuditLog.id), 0))) or 0)


def _flat(start: datetime, minutes: int) -> list[tuple[datetime, float, Quality]]:
    return [(start + timedelta(minutes=i), 50.0, Quality.GOOD) for i in range(minutes)]


def test_an_exclusion_applies_from_the_next_cycle_and_expires(clean_dq: Database) -> None:
    flow, temp = _plant(clean_dq)
    _write(clean_dq, flow, _healthy(T0, 120))
    _write(clean_dq, temp, _healthy(T0, 120))
    mark = _audit_mark(clean_dq)
    now = T0 + timedelta(minutes=40, seconds=10)
    with clean_dq.session() as s:
        made = add_exclusion(
            s, ACTOR, flow, ExclusionKind.EXCLUDE, " calibration ", now + timedelta(minutes=30), now
        )
    assert (made.reason, made.source_name, made.asset_code) == ("calibration", "FLOW", "EQ-1")

    def state_at(minute: int) -> tuple[Ne107, Rule]:
        with clean_dq.session() as s:
            found = evaluate_sensors(s, T0 + timedelta(minutes=minute), [flow])[flow]
        return found.status, found.rule

    assert state_at(40) == (Ne107.GOOD, Rule.NONE)  # the cycle before it was made
    assert state_at(41) == (Ne107.FUNCTION_CHECK, Rule.MANUAL_EXCLUSION)
    assert state_at(71) == (Ne107.GOOD, Rule.NONE)  # expired on its own
    with clean_dq.session() as s:
        assert [e.id for e in list_exclusions(s, active_at=now + timedelta(minutes=1))] == [made.id]
        assert list_exclusions(s, active_at=now + timedelta(hours=1)) == []
    assert _audit_after(clean_dq, mark) == ["exclude"]


def test_an_override_forces_good_but_not_over_bad_quality(clean_dq: Database) -> None:
    flow, _ = _plant(clean_dq)
    _write(clean_dq, flow, _flat(T0, 60))  # genuinely constant: flatline
    now = T0 + timedelta(minutes=59, seconds=10)
    with clean_dq.session() as s:
        before = evaluate_sensors(s, T0 + timedelta(minutes=59), [flow], store=False)[flow]
        add_exclusion(
            s,
            ACTOR,
            flow,
            ExclusionKind.OVERRIDE,
            "constant by design",
            now + timedelta(hours=1),
            now,
        )
    assert before.rule is Rule.FLATLINE
    with clean_dq.session() as s:
        after = evaluate_sensors(s, T0 + timedelta(minutes=60), [flow], store=False)[flow]
    assert (after.status, after.rule, after.usable) == (Ne107.GOOD, Rule.OVERRIDE, True)

    _write(clean_dq, flow, [(T0 + timedelta(minutes=61), 50.0, Quality.BAD)])
    with clean_dq.session() as s:
        bad = evaluate_sensors(s, T0 + timedelta(minutes=61, seconds=30), [flow], store=False)[flow]
    assert (bad.status, bad.rule) == (Ne107.FAILURE, Rule.BAD_QUALITY)  # FR-ING-05


def test_a_new_entry_ends_the_previous_and_ending_is_audited(clean_dq: Database) -> None:
    flow, _ = _plant(clean_dq)
    mark = _audit_mark(clean_dq)
    with clean_dq.session() as s:
        first = add_exclusion(
            s, ACTOR, flow, ExclusionKind.EXCLUDE, "a", T0 + timedelta(hours=8), T0
        )
        second = add_exclusion(
            s,
            ACTOR,
            flow,
            ExclusionKind.OVERRIDE,
            "b",
            T0 + timedelta(hours=8),
            T0 + timedelta(hours=1),
        )
    later = T0 + timedelta(hours=2)
    with clean_dq.session() as s:
        active = list_exclusions(s, active_at=later)
        assert [e.id for e in active] == [second.id]
        assert {e.id: e.ended_at for e in list_exclusions(s)}[first.id] == T0 + timedelta(hours=1)
        ended = end_exclusion(s, ACTOR, second.id, later)
        assert ended.ended_at == later
        with pytest.raises(DataQualityError, match="already ended"):
            end_exclusion(s, ACTOR, second.id, later)
    assert _audit_after(clean_dq, mark) == ["exclude", "end", "override", "end"]


@pytest.mark.parametrize(
    ("reason", "until", "message"),
    [
        ("", timedelta(hours=1), "Give a reason"),
        ("x", timedelta(hours=-1), "must be in the future"),
        ("x", timedelta(days=91), "at most 90 days"),
    ],
)
def test_an_exclusion_needs_a_reason_and_a_bounded_expiry(
    clean_dq: Database, reason: str, until: timedelta, message: str
) -> None:
    flow, _ = _plant(clean_dq)
    with clean_dq.session() as s, pytest.raises(DataQualityError, match=message):
        add_exclusion(s, ACTOR, flow, ExclusionKind.EXCLUDE, reason, T0 + until, T0)
