"""The health roll-up against PostgreSQL (plan 4.3; UC-08, FR-HLT-01, UCS §6.5)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from pmp import cli
from pmp.core import Database, get_settings
from pmp.modelling import Action, change_status
from pmp.registry import AssetLevel, AssetSpec, Criticality, upsert_asset
from pmp.scoring import Band, NodeHealth, Scheduler, health_tree, worst_band
from tests.integration.test_scoring_cycle import (  # noqa: F401  (deployed is a fixture)
    ACTOR,
    LIVE,
    Clock,
    _deploy,
    deployed,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def db(request: pytest.FixtureRequest) -> Database:
    """EQ-1 / main deployed under SITE-A, plus an empty unit EQ-0 beside it."""
    database: Database = request.getfixturevalue("deployed")
    with database.session() as s:
        upsert_asset(
            s, ACTOR, AssetSpec("EQ-0", "Idle pump", AssetLevel.EQUIPMENT, "SITE-A", Criticality.B)
        )
    return database


def _tree(db: Database) -> dict[str, NodeHealth]:
    with db.session() as s:
        (root,) = health_tree(s)
    return {n.code: n for n in root.walk()}


def test_roll_up_follows_the_latest_cycle(db: Database, tmp_path: Path) -> None:
    tree = _tree(db)
    assert tree["EQ-1"].band is Band.UNKNOWN  # deployed, not scored yet
    assert tree["EQ-0"].band is None  # no model: not monitored
    assert tree["SITE-A"].band is Band.UNKNOWN

    _deploy(db, tmp_path / "second", "bearings")
    scheduler = Scheduler(db, clock=Clock(LIVE + timedelta(minutes=1, seconds=30)))
    results = {r.model_id: r for r in scheduler.tick()}
    tree = _tree(db)
    eq1 = tree["EQ-1"]
    assert len(eq1.models) == 2
    healths = [r.output.health for r in results.values() if r.output and r.output.health]
    assert eq1.health == min(healths)
    assert eq1.band is worst_band(r.band for r in results.values())
    assert tree["SITE-A"].band is eq1.band
    assert tree["SITE-A"].health == eq1.health
    assert tree["SITE-A"].counts == {eq1.band: 1}
    assert tree["SITE-A"].worst == "EQ-1"

    # a model change shows on the next read: pausing one leaves only the other
    with db.session() as s:
        change_status(s, ACTOR, "EQ-1", "bearings", Action.PAUSE)
    scheduler.clock.now += timedelta(minutes=1)  # type: ignore[attr-defined]
    scheduler.tick()
    tree = _tree(db)
    assert [m.name for m in tree["EQ-1"].models] == ["main"]

    with db.session() as s:
        change_status(s, ACTOR, "EQ-1", "main", Action.PAUSE)
    tree = _tree(db)
    assert tree["EQ-1"].band is None
    assert tree["SITE-A"].band is None
    assert tree["SITE-A"].counts == {}


def test_subtree_and_command(
    db: Database,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    Scheduler(db, clock=Clock(LIVE + timedelta(minutes=1, seconds=30))).tick()
    with db.session() as s:
        roots = health_tree(s, "EQ-1")
    assert [r.code for r in roots] == ["EQ-1"]

    monkeypatch.setenv("PMP_DATABASE_URL", database_url)
    monkeypatch.setenv("PMP_SECRET_KEY", "k")
    monkeypatch.setenv("PMP_LOG_FORMAT", "text")
    get_settings.cache_clear()
    for argv, code in ((["health", "tree"], 0), (["health", "tree", "NOPE"], 1)):
        with pytest.raises(SystemExit) as exit_info:
            cli.main(argv)
        assert exit_info.value.code == code
    out, err = capsys.readouterr()
    assert "SITE-A" in out
    assert "  EQ-1" in out
    assert "- model main: " in out
    assert "Not monitored" in out  # EQ-0
    assert "'NOPE' does not exist" in err
