"""The alert engine against PostgreSQL (plan 4.2; UC-10, FR-ALM-01, -02, -04, NFR-ACC-01).

The model is the scoring tests' placeholder model on EQ-1 (criticality A); with the
synthetic data its DI sits near 30 %, so the rules here are set around that.
"""

from __future__ import annotations

import json
from datetime import timedelta

import psycopg
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from pmp import cli
from pmp.alerting import (
    AlertChanged,
    AlertError,
    AlertRuleSpec,
    AlertState,
    AlertView,
    RuleKind,
    Severity,
    acknowledge,
    alert_history,
    expire_shelves,
    get_alert,
    list_alerts,
    rule_states,
    set_alert_rules,
    set_priority,
    shelve,
    unshelve,
)
from pmp.core import (
    AccessDeniedError,
    Actor,
    Database,
    EventBus,
    Principal,
    Role,
    RoleAssignment,
    get_settings,
)
from pmp.modelling import Action, change_status, get_model
from pmp.registry import AssetLevel, AssetSpec, find_asset, upsert_asset
from pmp.scoring import EVENT_CHANNEL, Band, RuntimeStatus, Scheduler
from tests.integration.test_scoring_cycle import (  # noqa: F401  (deployed is a fixture)
    ACTOR,
    LIVE,
    Clock,
    _write,
    deployed,
)

pytestmark = pytest.mark.integration
DRIFTING = ("EQ1.T1", "EQ1.T2", "EQ1.T3")


@pytest.fixture
def db(request: pytest.FixtureRequest) -> Database:
    """EQ-1 / main deployed, with history up to an hour after LIVE (the scoring tests'
    `deployed` fixture)."""
    database: Database = request.getfixturevalue("deployed")
    return database


def _rules(db: Database, *rules: AlertRuleSpec) -> None:
    with db.session() as s:
        set_alert_rules(s, ACTOR, get_model(s, "EQ-1", "main").id, list(rules))


def _t1(db: Database) -> int:
    with db.session() as s:
        return get_model(s, "EQ-1", "main").latest.sensors[0].tag_id


def _scheduler(db: Database, minutes: int = 1, bus: EventBus | None = None) -> Scheduler:
    return Scheduler(db, bus=bus, clock=Clock(LIVE + timedelta(minutes=minutes, seconds=30)))


def _run(scheduler: Scheduler, cycles: int) -> list[AlertChanged]:
    changes: list[AlertChanged] = []
    for _ in range(cycles):
        for result in scheduler.tick():
            changes += result.alerts
        scheduler.clock.now += timedelta(minutes=1)  # type: ignore[attr-defined]
    return changes


def _raise_one(db: Database) -> int:
    """A DI warning raised on the first cycle (1 of 1)."""
    _rules(db, AlertRuleSpec(RuleKind.DI, 10, 200, persistence_n=1, persistence_m=1))
    changes = _run(_scheduler(db), 1)
    assert [(c.action, c.severity, c.priority) for c in changes] == [
        ("raise", Severity.WARNING, "P2")  # criticality A, Warning -> P2
    ]
    return changes[0].alert_id


def test_injected_drift_raises_at_the_right_priority_and_clears(db: Database) -> None:
    """Done when (plan 4.2): an injected drift raises an alert at the right priority and
    clears after recovery."""
    with db.session() as s:
        audit_before = s.scalar(text("SELECT coalesce(max(id), 0) FROM audit_log"))
    _rules(db, AlertRuleSpec(RuleKind.DI, 50, 80))  # normal DI ~30: below 45
    drift = {name: (lambda i: 100.0 + 3.0 * (i + 1)) for name in DRIFTING}
    _write(db, LIVE + timedelta(minutes=60), 20, **drift)  # slow ramp: no spikes
    scheduler = _scheduler(db, minutes=55)
    assert _run(scheduler, 5) == []  # normal operation: nothing raised

    changes = _run(scheduler, 20)
    # the ramp passes the warning limit first, then the alert limit: priority follows
    assert [(c.action, c.severity, c.priority) for c in changes] == [
        ("raise", Severity.WARNING, "P2"),
        ("escalate", Severity.ALERT, "P1"),
    ]
    alert = get_alert_by(db, changes[0].alert_id)
    assert alert.severity is Severity.ALERT
    assert alert.priority == "P1"  # criticality A, Alert
    assert alert.state is AlertState.ACTIVE_UNACK
    with db.session() as s:
        band = s.scalar(text("SELECT band FROM score ORDER BY ts DESC LIMIT 1"))
    assert band == Band.ALERT.value

    # traceability (NFR-ACC-01): version, rule, cycle, inputs with sample times and DQ
    trace = alert.trace
    assert trace["version_id"] == alert.version_id
    assert trace["rule"]["kind"] == "di"
    assert trace["value"] >= 50
    assert len(trace["contributions"]) == 4
    t1 = trace["inputs"]["EQ1.T1"]
    assert t1["sample_ts"] is not None
    assert t1["dq"]
    assert t1["usable"] is True

    # recovery: back to normal values; cleared after 5 cycles below 45
    _write(db, LIVE + timedelta(minutes=80), 40)
    changes = _run(scheduler, 20)
    assert [c.action for c in changes] == ["clear"]
    assert changes[0].state is AlertState.RTN_UNACK  # nobody acknowledged it
    with db.session() as s:
        acknowledge(s, ACTOR, [alert.id], scheduler.clock.now, "seen")  # type: ignore[attr-defined]
        assert get_alert(s, alert.id).state is AlertState.NORMAL
        actions = [e.action for e in alert_history(s, alert.id)]
        audits = s.scalar(  # this run's only: the audit log is append-only
            text(
                "SELECT count(*) FROM audit_log WHERE entity = 'alert' "
                "AND entity_id = :id AND id > :before"
            ),
            {"id": str(alert.id), "before": audit_before},
        )
    assert actions == ["raise", "escalate", "clear", "acknowledge"]
    assert audits == 4


def get_alert_by(db: Database, alert_id: int) -> AlertView:
    with db.session() as s:
        return get_alert(s, alert_id)


def test_acknowledge_shelve_unshelve_and_expiry(db: Database) -> None:
    alert_id = _raise_one(db)
    now = LIVE + timedelta(minutes=2)
    with db.session() as s:
        acknowledge(s, ACTOR, [alert_id], now)
        assert get_alert(s, alert_id).state is AlertState.ACTIVE_ACK
        with pytest.raises(AlertError, match="Active-Acknowledged"):
            acknowledge(s, ACTOR, [alert_id], now)
        with pytest.raises(AlertError, match="No alert with ID 999"):
            acknowledge(s, ACTOR, [alert_id, 999], now)
        with pytest.raises(AlertError, match="needs a reason"):
            shelve(s, ACTOR, [alert_id], now, reason=" ", duration=timedelta(hours=1))
        with pytest.raises(AlertError, match="at most"):
            shelve(s, ACTOR, [alert_id], now, reason="valve work", duration=timedelta(days=8))
        shelve(s, ACTOR, [alert_id], now, reason="valve work", duration=timedelta(hours=1))
        view = get_alert(s, alert_id)
        assert view.state is AlertState.SHELVED
        assert view.shelved_until == now + timedelta(hours=1)

        unshelve(s, ACTOR, [alert_id], now)  # condition still active: back to unacknowledged
        view = get_alert(s, alert_id)
        assert view.state is AlertState.ACTIVE_UNACK
        assert view.ack_at is None

        shelve(s, ACTOR, [alert_id], now, reason="valve work", duration=timedelta(hours=1))
        assert expire_shelves(s, now + timedelta(minutes=59)) == []
        expired = expire_shelves(s, now + timedelta(hours=1))
        assert [c.state for c in expired] == [AlertState.ACTIVE_UNACK]


def test_shelved_alerts_keep_evaluating(db: Database) -> None:
    alert_id = _raise_one(db)
    with db.session() as s:
        shelve(s, ACTOR, [alert_id], LIVE, reason="known", duration=timedelta(days=1))
    _rules(db, AlertRuleSpec(RuleKind.DI, 60, 200, persistence_n=1, persistence_m=1))
    scheduler = _scheduler(db, minutes=2)
    assert _run(scheduler, 5) == []  # cleared while shelved: no state change shown
    with db.session() as s:
        view = get_alert(s, alert_id)
        assert view.state is AlertState.SHELVED
        assert not view.condition_active
        changes = expire_shelves(s, LIVE + timedelta(days=2))
    assert [c.state for c in changes] == [AlertState.NORMAL]


def test_out_of_service_follows_the_model(db: Database) -> None:
    alert_id = _raise_one(db)
    with db.session() as s:
        change_status(s, ACTOR, "EQ-1", "main", Action.PAUSE)
    scheduler = _scheduler(db, minutes=2)
    results = scheduler.tick()
    assert results == []  # paused: not scored
    with db.session() as s:
        assert get_alert(s, alert_id).state is AlertState.OUT_OF_SERVICE
        with pytest.raises(AlertError):
            acknowledge(s, ACTOR, [alert_id], LIVE)
        change_status(s, ACTOR, "EQ-1", "main", Action.RESUME)
    scheduler.clock.now += timedelta(minutes=1)  # type: ignore[attr-defined]
    scheduler.tick()
    with db.session() as s:
        view = get_alert(s, alert_id)
        events = [e.action for e in alert_history(s, alert_id)]
        # back in service: Normal, and the rule starts afresh (raised again on 1 of 1)
        assert view.state is AlertState.NORMAL
        assert len(list_alerts(s)) == 1
    assert events == ["raise", "out_of_service", "return_to_service"]


def test_priority_matrix_change_reprioritises_open_alerts(db: Database) -> None:
    alert_id = _raise_one(db)
    with db.session() as s:
        try:
            changes = set_priority(s, ACTOR, "A", Severity.WARNING, "P1", LIVE)
            assert [(c.alert_id, c.priority) for c in changes] == [(alert_id, "P1")]
            assert get_alert(s, alert_id).priority == "P1"
            assert s.scalar(text("SELECT count(*) FROM audit_log WHERE entity = 'priority_matrix'"))
        finally:
            set_priority(s, ACTOR, "A", Severity.WARNING, "P2", LIVE)


def test_sensor_alerts_set_the_band(db: Database) -> None:
    t1 = _t1(db)
    _rules(
        db,
        AlertRuleSpec(RuleKind.DI, 500, 900),
        AlertRuleSpec(RuleKind.SENSOR, 1e-6, 1e6, tag_id=t1, persistence_n=1, persistence_m=1),
    )
    results = _scheduler(db).tick()
    assert [(c.kind, c.tag_id) for c in results[0].alerts] == [(RuleKind.SENSOR, t1)]
    assert results[0].band is Band.WATCH  # DI far below its limits; a sensor warning


def test_cycles_not_running_are_not_evaluated(db: Database) -> None:
    _rules(db, AlertRuleSpec(RuleKind.DI, 10, 200, persistence_n=1, persistence_m=1))
    _write(db, LIVE + timedelta(minutes=60), 10, **{"EQ1.MOTOR": lambda i: 50.0})
    results = _scheduler(db, minutes=62).tick()
    assert results[0].status is RuntimeStatus.NOT_IN_OPERATING_MODE
    assert results[0].alerts == ()
    with db.session() as s:
        assert s.scalar(select(func.count()).select_from(text("alert_rule_state"))) == 0


def test_alert_changes_are_announced(db: Database, database_url: str) -> None:
    _rules(db, AlertRuleSpec(RuleKind.DI, 10, 200, persistence_n=1, persistence_m=1))
    bus = EventBus()
    published: list[AlertChanged] = []
    bus.subscribe(AlertChanged, published.append)
    url = make_url(database_url).set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(hide_password=False), autocommit=True) as listener:
        listener.execute(f"LISTEN {EVENT_CHANNEL}")
        _scheduler(db, bus=bus).tick()
        notes = [json.loads(n.payload) for n in listener.notifies(timeout=5, stop_after=2)]
    assert {n["type"] for n in notes} == {"alert.changed", "score.updated"}
    assert [c.action for c in published] == ["raise"]


def test_alert_commands(
    db: Database,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    alert_id = _raise_one(db)
    monkeypatch.setenv("PMP_DATABASE_URL", database_url)
    monkeypatch.setenv("PMP_SECRET_KEY", "k")
    monkeypatch.setenv("PMP_LOG_FORMAT", "text")
    get_settings.cache_clear()

    def run(*argv: str) -> int:
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["alert", *argv])
        return int(exit_info.value.code or 0)

    assert run("list") == 0
    assert run("ack", str(alert_id), "--comment", "on it") == 0
    assert run("ack", str(alert_id)) == 1
    assert run("shelve", str(alert_id), "--reason", "maintenance", "--for", "8h") == 0
    assert run("unshelve", str(alert_id)) == 0
    assert run("show", str(alert_id)) == 0
    assert run("matrix", "show") == 0
    out, err = capsys.readouterr()
    assert "Warning" in out
    assert "EQ-1 / main" in out
    assert "acknowledge  Active-Unacknowledged -> Active-Acknowledged" in out
    assert "unshelved" in out
    assert "A            P2       P1" in out
    assert "Cannot acknowledge an alert that is Active-Acknowledged" in err


def test_rules_go_out_of_service_with_the_model_and_restart_afresh(db: Database) -> None:
    """UCS Figure 6: Normal -> Out of service when the model is paused; on its return
    the rules count afresh, so cycles from before the pause never complete a 3 of 5."""
    _rules(db, AlertRuleSpec(RuleKind.DI, 10, 200))  # DI ~30: every cycle exceeds
    scheduler = _scheduler(db)
    assert _run(scheduler, 2) == []  # 2 of 5 so far
    with db.session() as s:
        model_id = get_model(s, "EQ-1", "main").id
        change_status(s, ACTOR, "EQ-1", "main", Action.PAUSE)
    _run(scheduler, 1)
    with db.session() as s:
        assert set(rule_states(s, model_id).values()) == {AlertState.OUT_OF_SERVICE}
        change_status(s, ACTOR, "EQ-1", "main", Action.RESUME)
    assert _run(scheduler, 2) == []  # would have raised here if the old cycles counted
    with db.session() as s:
        assert set(rule_states(s, model_id).values()) == {AlertState.NORMAL}
    assert [c.action for c in _run(scheduler, 1)] == ["raise"]


def test_out_of_service_alerts_have_no_priority_and_come_last(db: Database) -> None:
    alert_id = _raise_one(db)
    with db.session() as s:
        shelve(s, ACTOR, [alert_id], LIVE, reason="work", duration=timedelta(hours=1))
        change_status(s, ACTOR, "EQ-1", "main", Action.PAUSE)
    _run(_scheduler(db, minutes=2), 1)
    with db.session() as s:
        view = get_alert(s, alert_id)
    assert (view.state, view.priority) == (AlertState.OUT_OF_SERVICE, None)
    assert (view.shelved_until, view.shelve_reason) == (None, None)


def test_escalation_is_acknowledged_again(db: Database) -> None:
    alert_id = _raise_one(db)  # Warning, DI ~30
    with db.session() as s:
        acknowledge(s, ACTOR, [alert_id], LIVE)
    _rules(db, AlertRuleSpec(RuleKind.DI, 10, 20, persistence_n=1, persistence_m=1))
    changes = _run(_scheduler(db, minutes=2), 1)
    assert [(c.action, c.previous, c.state, c.severity) for c in changes] == [
        ("escalate", AlertState.ACTIVE_ACK, AlertState.ACTIVE_UNACK, Severity.ALERT)
    ]
    with db.session() as s:
        assert get_alert(s, alert_id).ack_at is None


def test_only_analysts_and_model_engineers_act_on_alerts_in_their_scope(db: Database) -> None:
    """ARC §9.2: acknowledge / shelve alerts: Analyst and Model Engineer, within scope."""
    alert_id = _raise_one(db)
    with db.session() as s:
        site_a = find_asset(s, "SITE-A")
        assert site_a is not None
        other = upsert_asset(s, ACTOR, AssetSpec("SITE-Z", "Elsewhere", AssetLevel.SITE))
        site_z = find_asset(s, "SITE-Z")
    assert other is not None
    assert site_z is not None

    def as_(role: Role, scope: int | None = None) -> Actor:
        return Actor.user(Principal(42, "pat", (RoleAssignment(role, scope),)))

    for refused in (as_(Role.VIEWER), as_(Role.ADMINISTRATOR), as_(Role.ANALYST, site_z.id)):
        with db.session() as s, pytest.raises(AccessDeniedError):
            acknowledge(s, refused, [alert_id], LIVE)
    with db.session() as s:
        acknowledge(s, as_(Role.ANALYST, site_a.id), [alert_id], LIVE)
        assert get_alert(s, alert_id).state is AlertState.ACTIVE_ACK


@pytest.mark.parametrize("change", ["remove", "switch off"])
def test_an_alert_closes_when_its_rule_is_removed_or_switched_off(
    db: Database, change: str
) -> None:
    """Plan 6.7 (audit): otherwise the alert could never clear and would hold the band."""
    alert_id = _raise_one(db)
    if change == "remove":
        _rules(db)
    else:
        _rules(
            db, AlertRuleSpec(RuleKind.DI, 10, 200, persistence_n=1, persistence_m=1, enabled=False)
        )
    alert = get_alert_by(db, alert_id)
    assert alert.state is AlertState.NORMAL
    assert alert.condition_active is False
    with db.session() as s:
        last = alert_history(s, alert_id)[-1]
    assert (last.action, last.to_state) == ("rule_removed", AlertState.NORMAL.value)
    assert last.comment == (
        "alert rule removed" if change == "remove" else "alert rule switched off"
    )
