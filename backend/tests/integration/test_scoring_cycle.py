"""The scoring runtime against PostgreSQL (plan 4.1; FR-RUN-01 to -04; NFR-REL-01)."""

from __future__ import annotations

import json
import math
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from pmp import cli
from pmp.alerting import AlertRuleSpec, RuleKind, set_alert_rules
from pmp.core import Actor, Database, EventBus, LockKey, get_settings, lock_for_transaction
from pmp.ingestion import Quality, SampleRow, write_samples
from pmp.modelling import (
    Action,
    ModelCache,
    ModelDefinition,
    Period,
    SensorChoice,
    change_status,
    get_model,
    list_active_versions,
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
from pmp.scoring import (
    EVENT_CHANNEL,
    Band,
    RuntimeStatus,
    Scheduler,
    ScoreComputed,
    get_runtime_statuses,
    score_models,
)

pytestmark = pytest.mark.integration
ACTOR = Actor.system()
T0 = datetime(2026, 6, 1, tzinfo=UTC)
LIVE = T0 + timedelta(days=4)  # scoring starts here
TAGS = ("EQ1.T1", "EQ1.T2", "EQ1.T3", "EQ1.MOTOR")


def _definition(name: str = "main") -> ModelDefinition:
    return ModelDefinition(
        asset_code="EQ-1",
        name=name,
        sensors=(
            SensorChoice("EQ1.T1", required=True),
            SensorChoice("EQ1.T2"),
            SensorChoice("EQ1.T3"),
            SensorChoice("EQ1.MOTOR"),
        ),
        training_periods=(Period(T0, T0 + timedelta(days=3)),),
        validation_period=Period(T0 + timedelta(days=3), LIVE),
        mode_filters=("EQ1.MOTOR > 120",),
    )


def _ids(db: Database) -> dict[str, int]:
    with db.session() as s:
        return {n: t.id for n in TAGS if (t := find_tag(s, "gw-1", n)) is not None}


def _write(
    db: Database, start: datetime, minutes: int, **overrides: Callable[[int], float]
) -> None:
    ids = _ids(db)
    rows = []
    for name, tag_id in ids.items():
        for i in range(minutes):
            t = (start - T0).total_seconds() / 60 + i
            value = 100 + 10 * math.sin(t / 40 + len(name))
            if name == "EQ1.MOTOR":  # a running motor's current moves a little
                value = 150 + 5 * math.sin(t / 30)
            if name in overrides:
                value = overrides[name](i)
            rows.append(SampleRow(tag_id, start + timedelta(minutes=i), value, Quality.GOOD, None))
    with db.session() as s:
        write_samples(s, rows)


@pytest.fixture
def deployed(clean_models: Database, tmp_path: Path) -> Database:
    db = clean_models
    with db.session() as s:
        s.execute(text("TRUNCATE sample, score, sensor_output"))
        s.execute(text("TRUNCATE sensor_status, dq_rule"))
        upsert_asset(s, ACTOR, AssetSpec("SITE-A", "Site A", AssetLevel.SITE))
        upsert_asset(
            s, ACTOR, AssetSpec("EQ-1", "Pump", AssetLevel.EQUIPMENT, "SITE-A", Criticality.A)
        )
        for name in TAGS:
            upsert_tag(s, ACTOR, TagSpec("gw-1", name, "EQ-1", "u", 0.0, 400.0, 60))
    _write(db, T0, 4 * 1440 + 60)
    _deploy(db, tmp_path, "main")
    return db


def _deploy(db: Database, artefacts: Path, name: str) -> None:
    with db.session() as s:
        model = save_draft(s, ACTOR, _definition(name))
        t1 = model.latest.sensors[0].tag_id
        set_alert_rules(
            s,
            ACTOR,
            model.id,
            [AlertRuleSpec(RuleKind.DI, 15, 25), AlertRuleSpec(RuleKind.SENSOR, 3, 5, tag_id=t1)],
        )
        view, _ = start_training(s, ACTOR, "EQ-1", name, queue=False)
    assert run_training(db, view.id, artefacts)["status"] == "Validated"
    with db.session() as s:
        change_status(s, ACTOR, "EQ-1", name, Action.DEPLOY)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _scores(db: Database) -> list[tuple[datetime, str, str]]:
    with db.session() as s:
        rows = s.execute(text("SELECT ts, status, band FROM score ORDER BY ts")).all()
    return [(ts, status, band) for ts, status, band in rows]


def test_each_cycle_is_scored_once_on_the_clock(deployed: Database) -> None:
    clock = Clock(LIVE + timedelta(minutes=10, seconds=25))
    bus = EventBus()
    computed: list[ScoreComputed] = []
    bus.subscribe(ScoreComputed, computed.append)
    scheduler = Scheduler(deployed, grace_s=20, bus=bus, clock=clock)

    results = scheduler.tick()
    assert [(r.status, r.written) for r in results] == [(RuntimeStatus.RUNNING, True)]
    cycle = LIVE + timedelta(minutes=10)
    assert results[0].ts == cycle
    assert scheduler.tick() == []  # nothing new is due
    clock.now += timedelta(seconds=60)
    assert [r.ts for r in scheduler.tick()] == [cycle + timedelta(minutes=1)]
    assert [e.ts for e in computed] == [cycle, cycle + timedelta(minutes=1)]

    with deployed.session() as s:
        outputs = s.scalar(text("SELECT count(*) FROM sensor_output"))
        statuses = get_runtime_statuses(s)
    assert outputs == 2 * 4
    assert statuses[0].status is RuntimeStatus.RUNNING
    assert statuses[0].health is not None
    assert statuses[0].band is not Band.UNKNOWN  # placeholder model: any real band


def test_missed_cycles_are_not_back_filled_and_restarts_do_not_duplicate(
    deployed: Database,
) -> None:
    clock = Clock(LIVE + timedelta(minutes=5, seconds=30))
    Scheduler(deployed, clock=clock).tick()
    clock.now += timedelta(minutes=30)  # worker down for half an hour
    restarted = Scheduler(deployed, clock=clock)  # a new process: reads the last cycle
    results = restarted.tick()
    assert [r.ts for r in results] == [LIVE + timedelta(minutes=35)]
    assert [ts for ts, *_ in _scores(deployed)] == [
        LIVE + timedelta(minutes=5),
        LIVE + timedelta(minutes=35),
    ]
    again = Scheduler(deployed, clock=clock)
    again._last = {}  # as if the restart forgot everything: the database still refuses
    assert [r.written for r in again.tick()] == [False]
    assert len(_scores(deployed)) == 2


def test_late_data_does_not_change_a_past_score(deployed: Database) -> None:
    clock = Clock(LIVE + timedelta(minutes=5, seconds=30))
    Scheduler(deployed, clock=clock).tick()
    before = _scores(deployed)
    _write(deployed, LIVE + timedelta(minutes=5), 1, **{"EQ1.T1": lambda i: 380.0})
    Scheduler(deployed, clock=clock).tick()
    assert _scores(deployed) == before


def test_statuses_follow_the_data(deployed: Database) -> None:
    scheduler = Scheduler(deployed, clock=Clock(LIVE + timedelta(minutes=2, seconds=30)))
    _write(deployed, LIVE, 60, **{"EQ1.MOTOR": lambda i: 50.0 if i < 5 else 150.0})
    assert scheduler.tick()[0].status is RuntimeStatus.NOT_IN_OPERATING_MODE

    scheduler.clock = Clock(LIVE + timedelta(hours=3, seconds=30))  # data stopped at 1 h
    result = scheduler.tick()[0]
    assert result.status is RuntimeStatus.INSUFFICIENT_DATA
    assert "Required sensor not usable: EQ1.T1" in (result.reason or "")
    with deployed.session() as s:
        row = s.execute(text("SELECT band, health, di FROM score ORDER BY ts DESC LIMIT 1")).one()
    assert tuple(row) == ("Unknown", None, None)  # Unknown, not a number


def test_paused_retired_and_broken_models(deployed: Database, tmp_path: Path) -> None:
    _deploy(deployed, tmp_path / "second", "bearings")
    clock = Clock(LIVE + timedelta(minutes=5, seconds=30))
    with deployed.session() as s:
        change_status(s, ACTOR, "EQ-1", "bearings", Action.PAUSE)
    results = Scheduler(deployed, clock=clock).tick()
    assert [r.status for r in results] == [RuntimeStatus.RUNNING]

    with deployed.session() as s:
        folder = Path(get_model(s, "EQ-1", "main").latest.artefact_path or "")
        change_status(s, ACTOR, "EQ-1", "bearings", Action.RETIRE)
    (folder / "scaling.json").write_text("{}")  # tampered: the model cannot load
    clock.now += timedelta(minutes=1)
    results = Scheduler(deployed, clock=clock).tick()
    assert [r.status for r in results] == [RuntimeStatus.ERROR]
    assert "does not match its checksum" in (results[0].reason or "")
    with deployed.session() as s:
        statuses = {v.status for v in get_runtime_statuses(s)}
    assert statuses == {RuntimeStatus.ERROR, RuntimeStatus.OUT_OF_SERVICE}


def test_each_score_is_announced_with_notify(deployed: Database, database_url: str) -> None:
    url = make_url(database_url).set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(hide_password=False), autocommit=True) as listener:
        listener.execute(f"LISTEN {EVENT_CHANNEL}")
        Scheduler(deployed, clock=Clock(LIVE + timedelta(minutes=5, seconds=30))).tick()
        notes = list(listener.notifies(timeout=5, stop_after=1))
    payload = json.loads(notes[0].payload)
    assert payload["type"] == "score.updated"
    assert payload["status"] == "Running"
    assert payload["health"] is not None


def test_score_once_and_status_commands(
    deployed: Database,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PMP_DATABASE_URL", database_url)
    monkeypatch.setenv("PMP_SECRET_KEY", "k")
    monkeypatch.setenv("PMP_LOG_FORMAT", "text")
    get_settings.cache_clear()
    at = (LIVE + timedelta(minutes=7, seconds=12)).isoformat()
    for _ in range(2):
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["score", "once", "EQ-1", "main", "--at", at])
        assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "Running  DI" in out
    assert "top contributors" in out
    assert "[already scored; nothing written]" in out
    with pytest.raises(SystemExit):
        cli.main(["score", "status"])
    assert "EQ-1 / main" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["score", "once", "EQ-1", "nope"])
    assert exit_info.value.code == 1
    get_settings.cache_clear()
    with deployed.session() as s:
        assert s.scalar(select(func.count()).select_from(text("score"))) == 1


def test_only_one_scheduler_leads(deployed: Database) -> None:
    import threading
    import time

    clock = Clock(LIVE + timedelta(minutes=5, seconds=30))
    stop = threading.Event()
    leader = Scheduler(deployed, clock=clock, poll_s=0.05)
    follower = Scheduler(deployed, clock=clock, poll_s=0.05)
    first = threading.Thread(target=leader.run_forever, args=(stop,))
    first.start()
    deadline = time.monotonic() + 10
    while not _scores(deployed) and time.monotonic() < deadline:
        time.sleep(0.05)
    second = threading.Thread(target=follower.run_forever, args=(stop,))
    second.start()
    time.sleep(0.3)
    assert follower._last is None  # never ticked: the lock is held
    stop.set()
    first.join(timeout=10)
    second.join(timeout=10)
    assert not first.is_alive()
    assert not second.is_alive()
    assert len(_scores(deployed)) == 1


def test_sensor_outputs_keep_the_data_quality_state(deployed: Database) -> None:
    """UCS §6.1: every cycle keeps each sensor's NE 107 status, the rule and whether it was
    used, also when the cycle had insufficient data (PDS SCR-03 lists the unusable)."""
    scheduler = Scheduler(deployed, clock=Clock(LIVE + timedelta(minutes=2, seconds=30)))
    scheduler.tick()
    scheduler.clock = Clock(LIVE + timedelta(hours=3, seconds=30))  # data stopped at 1 h
    result = scheduler.tick()[0]
    assert result.status is RuntimeStatus.INSUFFICIENT_DATA
    with deployed.session() as s:
        rows = s.execute(
            text("SELECT ts, dq_status, dq_rule, used FROM sensor_output ORDER BY ts, tag_id")
        ).all()
    running = {(st, rule, used) for ts, st, rule, used in rows if ts == LIVE + timedelta(minutes=2)}
    stopped = {(st, rule, used) for ts, st, rule, used in rows if ts == result.ts}
    assert running == {("Good", "none", True)}
    assert stopped == {("Failure", "stale", False)}


def test_two_writers_never_count_a_cycle_twice(deployed: Database) -> None:
    """If two workers ever score the same cycle, the per-version lock makes the second
    wait for the first and then find the cycle done, so its alerts are not evaluated
    again (ARC §1.2: no duplicates)."""
    Scheduler(deployed, clock=Clock(LIVE + timedelta(minutes=4, seconds=30))).tick()
    with deployed.session() as s:
        version = list_active_versions(s)[0]
    cycle = LIVE + timedelta(minutes=5)
    results: list[bool] = []

    def run() -> None:
        results.extend(r.written for r in score_models(deployed, cycle, [version], ModelCache()))

    with deployed.session() as holder:  # another writer is in the middle of this version
        lock_for_transaction(holder, LockKey.SCORE_CYCLE, version.version_id)
        second = threading.Thread(target=run)
        second.start()
        second.join(timeout=2)
        assert second.is_alive()  # waiting for the lock, nothing written yet
        assert results == []
    second.join(timeout=30)
    assert results == [True]
    run()  # the cycle is now done: found under the lock, alerts untouched
    assert results == [True, False]
    with deployed.session() as s:
        levels = s.execute(text("SELECT levels FROM alert_rule_state")).scalars().all()
    assert levels
    assert all(len(lv) == 2 for lv in levels)  # the earlier cycle and this one, once


def test_sensors_no_deployed_model_scores_still_get_a_current_status(deployed: Database) -> None:
    """Plan 6.7 (audit, FR-DQ-02): a tag in no model, and a paused model's tags, are
    checked by the leader once a minute, so no status freezes."""
    with deployed.session() as s:
        upsert_tag(s, ACTOR, TagSpec("gw-1", "EQ1.SPARE", "EQ-1", "u", 0.0, 400.0, 60))
    clock = Clock(LIVE + timedelta(minutes=5, seconds=25))
    scheduler = Scheduler(deployed, grace_s=20, clock=clock)
    scheduler.tick()

    def statuses() -> dict[str, tuple[str, datetime]]:
        with deployed.session() as s:
            rows = s.execute(
                text(
                    "SELECT t.source_name, st.status, st.evaluated_at FROM sensor_status st "
                    "JOIN tag t ON t.id = st.tag_id"
                )
            ).all()
        return {name: (status, at) for name, status, at in rows}

    first = statuses()
    assert first["EQ1.SPARE"][0] == "Failure"  # no samples at all: stale
    with deployed.session() as s:
        change_status(s, ACTOR, "EQ-1", "main", Action.PAUSE)
    clock.now += timedelta(minutes=2)
    scheduler.tick()
    later = statuses()
    assert later["EQ1.T1"][1] > first["EQ1.T1"][1]  # the paused model's sensor too
    assert later["EQ1.SPARE"][1] > first["EQ1.SPARE"][1]


def test_a_model_waits_for_the_longest_grace_of_its_sources(deployed: Database) -> None:
    """Plan 6.7 (audit, ARC §5.1, AC-05): 5 s by default; a late source gets its own."""
    from pmp.ingestion import set_source_grace

    clock = Clock(LIVE + timedelta(minutes=10, seconds=25))
    assert [r.ts for r in Scheduler(deployed, clock=clock).tick()] == [LIVE + timedelta(minutes=10)]
    with deployed.session() as s:
        s.execute(
            text(
                "INSERT INTO ingest_source (source, last_received_at, accepted_total, "
                "rejected_total) VALUES ('gw-1', now(), 0, 0)"
            )
        )
        set_source_grace(s, ACTOR, "gw-1", 30)
    clock.now += timedelta(minutes=1)  # 11:25 after LIVE: 11:00 needs until 11:30
    assert [r.ts for r in Scheduler(deployed, clock=clock).tick()] == []
