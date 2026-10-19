"""`pmp dq` against the test database: set (with preview), show, preview and status."""

from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from pmp import cli
from pmp.core import Actor, Database, get_settings
from pmp.dataquality import RuleScope, get_rule_set
from pmp.ingestion import Quality, SampleRow, write_samples
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


@pytest.fixture
def plant(
    clean_dq: Database, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Database]:
    monkeypatch.setenv("PMP_DATABASE_URL", database_url)
    monkeypatch.setenv("PMP_SECRET_KEY", "k")
    monkeypatch.setenv("PMP_LOG_FORMAT", "text")
    get_settings.cache_clear()
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    with clean_dq.session() as s:
        upsert_asset(s, ACTOR, AssetSpec("SITE-A", "Site A", AssetLevel.SITE))
        upsert_asset(
            s, ACTOR, AssetSpec("EQ-1", "Pump 1", AssetLevel.EQUIPMENT, "SITE-A", Criticality.B)
        )
        upsert_tag(s, ACTOR, TagSpec("gw-1", "FLOW", "EQ-1", "u", 0.0, 100.0, 60))
    with clean_dq.session() as s:
        tag = find_tag(s, "gw-1", "FLOW")
        assert tag is not None
        rows = [
            SampleRow(
                tag.id, now - timedelta(minutes=i), 50 + 3 * math.sin(i / 3), Quality.GOOD, None
            )
            for i in range(25 * 60)  # a day and an hour of 1-minute data up to now
        ]
        write_samples(s, rows)
    yield clean_dq
    get_settings.cache_clear()


def run(*args: str) -> int:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["dq", *args])
    return int(exit_info.value.code or 0)


def test_set_show_preview_and_status(plant: Database, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("set", "--tag", "FLOW", "spike_pct=30", "--comment", "test", "--days", "1") == 0
    assert "Saved tag" in capsys.readouterr().out
    with plant.session() as s:
        tag = find_tag(s, "gw-1", "FLOW")
        assert tag is not None
        assert get_rule_set(s, RuleScope.tag(tag.id)).overrides == {"spike_pct": 30.0}

    assert run("show", "--tag", "FLOW") == 0
    out = capsys.readouterr().out
    assert "version 1" in out
    assert "spike_pct            30.0" in out

    assert run("preview", "flatline_window=5", "--days", "1") == 0
    assert "Overall excluded" in capsys.readouterr().out

    assert run("set", "--tag", "FLOW", "spike_pct=default", "--days", "1") == 0
    with plant.session() as s:
        assert tag is not None
        assert get_rule_set(s, RuleScope.tag(tag.id)).version == 2

    assert run("status", "--asset", "EQ-1") == 0
    assert "FLOW" in capsys.readouterr().out


def test_set_refuses_when_too_much_would_be_excluded(
    plant: Database, capsys: pytest.CaptureFixture[str]
) -> None:
    # A huge flatline threshold flags the live signal as flat everywhere
    assert run("set", "flatline_std_pct=50", "--days", "1") == 1
    captured = capsys.readouterr()
    assert "WARNING" in captured.out
    assert "--yes" in captured.err
    with plant.session() as s:
        assert get_rule_set(s, RuleScope.everywhere()).version == 0
    assert run("set", "flatline_std_pct=50", "--days", "1", "--yes") == 0


def test_bad_input_is_reported(plant: Database, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("set", "spike_pct") == 1
    assert "NAME=VALUE" in capsys.readouterr().err
    assert run("show", "--tag", "NOPE") == 1
    assert "not registered" in capsys.readouterr().err
    assert run("show", "--role", "pump") == 1
    assert "TYPE/ROLE" in capsys.readouterr().err
