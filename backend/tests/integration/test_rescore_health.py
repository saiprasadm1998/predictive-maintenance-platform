"""Re-scoring, ingestion health and the stale-source e-mail (plan 8.7).

"Done when" (PRD): a re-score completes as a background job and replaces the outputs of
the selected version (FR-RUN-05); stopping the gateway feed raises a stale-source warning
within 3 scan intervals (FR-ING-07).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from pmp.alerting import AlertRuleSpec, RuleKind
from pmp.core import AccessDeniedError, Actor, Database, JobRegistry, Role, Worker, get_job
from pmp.ingestion import BatchIn, ingest_batch, ingestion_health, source_health
from pmp.modelling import get_model
from pmp.notifications import EventKind, Notifier
from pmp.scoring import (
    RESCORE_JOB,
    RescoreError,
    RescoreRequest,
    make_rescore_handler,
    queue_rescore,
    rescore_period,
)
from tests.integration.test_alerts import _rules, _run, _scheduler
from tests.integration.test_notifications import (  # noqa: F401  (db and deployed are fixtures)
    Clock,
    Mailbox,
    actor,
    db,
    subscribe,
)
from tests.integration.test_scoring_cycle import (  # noqa: F401  (deployed is a fixture)
    ACTOR,
    LIVE,
    deployed,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def plant(db: Database) -> Iterator[Database]:  # noqa: F811
    """The notification tests' plant: EQ-1 deployed, users ana, max, moe and vic. The
    sources these tests feed are removed afterwards: other test files add their own."""
    with db.session() as s:
        s.execute(text("TRUNCATE ingest_source"))
    yield db
    with db.session() as s:
        s.execute(text("TRUNCATE ingest_source"))


def _version(plant: Database) -> int:
    with plant.session() as s:
        return get_model(s, "EQ-1", "main").latest.id


def _snapshot(plant: Database) -> tuple[object, ...]:
    with plant.session() as s:
        return (
            s.execute(text("SELECT id, state, priority FROM alert ORDER BY id")).all(),
            s.execute(text("SELECT count(*) FROM alert_event")).scalar_one(),
            s.execute(text("SELECT status, last_cycle, since FROM runtime_status")).all(),
            s.execute(text("SELECT count(*) FROM notification_log")).scalar_one(),
        )


def test_a_rescore_replaces_the_versions_outputs_and_nothing_else(plant: Database) -> None:
    _rules(plant, AlertRuleSpec(RuleKind.DI, 10, 20, persistence_n=1, persistence_m=1))
    _run(_scheduler(plant), 5)  # live cycles LIVE+1 .. LIVE+5 min, with an alert
    version = _version(plant)
    with plant.session() as s:
        live: dict[datetime, float] = dict(
            s.execute(text("SELECT ts, di FROM score WHERE version_id = :v"), {"v": version}).all()
        )
        s.execute(text("UPDATE score SET di = 999 WHERE version_id = :v"), {"v": version})
        s.execute(text("DELETE FROM sensor_output WHERE version_id = :v"), {"v": version})
    before = _snapshot(plant)
    seen: list[float] = []

    result = rescore_period(
        plant,
        RescoreRequest(version, LIVE - timedelta(hours=6), LIVE + timedelta(hours=1)),
        progress=lambda percent, **_: seen.append(percent),
    )

    newest = LIVE + timedelta(minutes=5)
    assert result.end == newest  # never past the latest live cycle
    assert (result.cycles, result.replaced) == (6 * 60 + 5, 4)
    assert seen[-1] == 100
    with plant.session() as s:
        scores: dict[datetime, float] = dict(
            s.execute(text("SELECT ts, di FROM score WHERE version_id = :v"), {"v": version}).all()
        )
        outputs = s.execute(
            text("SELECT count(DISTINCT ts) FROM sensor_output WHERE version_id = :v"),
            {"v": version},
        ).scalar_one()
    assert len(scores) == 6 * 60 + 5 + 1
    assert scores[newest] == 999  # the live cycle is left alone
    for minute in range(1, 5):  # the same samples and model give the same DI
        ts = LIVE + timedelta(minutes=minute)
        assert scores[ts] == pytest.approx(live[ts])
    assert outputs == 6 * 60 + 5
    assert _snapshot(plant) == before  # no alert, alert event, status or e-mail changed

    again = rescore_period(plant, RescoreRequest(version, LIVE - timedelta(hours=1), LIVE))
    assert (again.cycles, again.replaced) == (60, 60)  # repeatable: a retried job is safe


def test_a_rescore_is_queued_as_a_job_by_model_engineers(plant: Database) -> None:
    version = _version(plant)
    with plant.session() as s:
        s.execute(text("TRUNCATE job RESTART IDENTITY"))
        audit_before = s.execute(text("SELECT coalesce(max(id), 0) FROM audit_log")).scalar_one()
    now = datetime.now(UTC)
    period = RescoreRequest(version, LIVE - timedelta(hours=1), LIVE)
    with plant.session() as s, pytest.raises(AccessDeniedError):
        queue_rescore(s, actor(plant, "ana"), period, now)
    with plant.session() as s:
        for wrong, why in (
            (RescoreRequest(version, LIVE, LIVE), "end after it starts"),
            (RescoreRequest(version, LIVE, now + timedelta(hours=1)), "future"),
            (RescoreRequest(version, LIVE - timedelta(days=400), LIVE), "366 days"),
            (RescoreRequest(version + 99, LIVE - timedelta(hours=1), LIVE), "does not exist"),
        ):
            with pytest.raises(RescoreError, match=why):
                queue_rescore(s, actor(plant, "moe"), wrong, now)
        job_id = queue_rescore(s, actor(plant, "moe"), period, now)
    registry = JobRegistry()
    registry.register(RESCORE_JOB, make_rescore_handler(plant))
    assert Worker(plant, registry, name="t").run_once()
    with plant.session() as s:
        job = get_job(s, job_id)
        audited = s.execute(
            text("SELECT count(*) FROM audit_log WHERE action = 'rescore' AND id > :b"),
            {"b": audit_before},
        ).scalar_one()
    assert job is not None
    assert job.status.value == "succeeded"
    assert job.result is not None
    assert job.result["cycles"] == 60
    assert audited == 1


def _feed(plant: Database, at: datetime, lag: timedelta = timedelta(0)) -> None:
    batch = BatchIn.model_validate(
        {"source": "gw-1", "samples": [{"tag": t, "ts": at - lag, "v": 50.0} for t in ("EQ1.T1",)]}
    )
    with plant.session() as s:
        ingest_batch(s, batch, now=at, late_window=timedelta(days=3650))


def test_a_stopped_feed_is_stale_within_3_scan_intervals(plant: Database) -> None:
    stop = datetime.now(UTC).replace(microsecond=0)
    _feed(plant, stop)
    with plant.session() as s:
        (fresh,) = source_health(s, stop + timedelta(seconds=60))
        (stale,) = source_health(s, stop + timedelta(seconds=121))
        with pytest.raises(AccessDeniedError):
            ingestion_health(s, actor(plant, "moe"), stop)
        screen = ingestion_health(s, Actor.system(), stop + timedelta(seconds=121))
    assert (fresh.source, fresh.interval_s, fresh.tags) == ("gw-1", 60, 4)
    assert not fresh.stale
    assert stale.stale
    assert stale.stale_after < timedelta(seconds=3 * 60)
    assert (stale.accepted_total, stale.skewed, stale.skew_s) == (1, False, 0)
    assert stale.per_minute == pytest.approx(0.2)  # 1 sample in 5 minutes
    t1 = next(t for t in screen.tags if t.source_name == "EQ1.T1")
    t2 = next(t for t in screen.tags if t.source_name == "EQ1.T2")
    assert (t1.last_sample_ts, t1.stale) == (stop, True)
    assert t2.last_sample_ts is not None  # the fixture's history
    assert t2.stale

    _feed(plant, stop + timedelta(seconds=150), lag=timedelta(seconds=90))
    with plant.session() as s:
        (skewed,) = source_health(s, stop + timedelta(seconds=150))
    assert not skewed.stale
    assert (skewed.skew_s, skewed.skewed) == (90, True)  # a gateway clock 90 s behind


def test_the_stale_source_is_emailed_to_subscribed_administrators_once(plant: Database) -> None:
    from pmp.core import RoleAssignment, create_user

    with plant.session() as s:
        create_user(
            s,
            ACTOR,
            username="ada",
            display_name="Ada",
            password="correct horse battery",
            assignments=[RoleAssignment(Role.ADMINISTRATOR)],
            email="ada@plant.test",
        )
    subscribe(plant, "ada", EventKind.SOURCE_STALE, minimum="P4")
    subscribe(plant, "moe", EventKind.SOURCE_STALE, minimum="P4")  # not an administrator
    stop = datetime.now(UTC).replace(microsecond=0)
    _feed(plant, stop)
    mailbox = Mailbox()
    clock = Clock(stop + timedelta(seconds=60))
    worker = Notifier(plant, mailbox, "https://pmp.test", clock=clock)
    worker.run_once()
    assert mailbox.sent == []
    clock.now = stop + timedelta(seconds=135)  # within 3 scan intervals of the stop
    worker.run_once()
    ((to, subject, body),) = mailbox.sent
    assert (to, subject) == ("ada@plant.test", "[PMP] Data source stale · gw-1")
    assert "has sent nothing for 135 s (scan interval 60 s)" in body
    assert "https://pmp.test/admin?tab=ingestion" in body
    clock.now += timedelta(minutes=10)
    worker.run_once()
    assert len(mailbox.sent) == 1  # once per stop
    _feed(plant, clock.now)  # back, then stopped again: warned again
    clock.now += timedelta(minutes=3)
    worker.run_once()
    assert len(mailbox.sent) == 2


def test_results_give_every_models_current_health_in_one_call(plant: Database) -> None:
    from pmp.api.results import _results

    _rules(plant, AlertRuleSpec(RuleKind.DI, 10, 20, persistence_n=1, persistence_m=1))
    _run(_scheduler(plant), 2)
    with plant.session() as s:
        (model,) = _results(s, "SITE-A").models
        assert _results(s, "EQ-1").models == [model]
    assert (model.asset, model.model, model.band, model.status) == (
        "EQ-1",
        "main v1",
        "Alert",
        "Running",
    )
    assert (model.active_alerts, model.urgency) == (1, None)  # no forecast run yet
    assert model.di is not None
    assert model.health is not None
    assert model.last_cycle == LIVE + timedelta(minutes=2)
