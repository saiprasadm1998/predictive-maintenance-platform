"""Ingestion service against PostgreSQL/TimescaleDB (UC-01, FR-ING-04, -05, -06)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from pmp.core import Actor, Database
from pmp.ingestion import (
    BatchIn,
    Quality,
    count_samples,
    ingest_batch,
    list_unmapped_tags,
    promote_unmapped_tag,
    read_samples,
    server_now,
    source_stats,
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
SOURCE = "gw-site-a-01"
WEEK = timedelta(days=7)


def register(db: Database, *names: str) -> dict[str, int]:
    with db.session() as s:
        upsert_asset(s, ACTOR, AssetSpec("SITE-A", "Site A", AssetLevel.SITE))
        upsert_asset(
            s, ACTOR, AssetSpec("K-101", "K-101", AssetLevel.EQUIPMENT, "SITE-A", Criticality.A)
        )
        for name in names:
            upsert_tag(s, ACTOR, TagSpec(SOURCE, name, "K-101", "°C", 0, 150, 60))
    with db.session() as s:
        ids = {}
        for name in names:
            tag = find_tag(s, SOURCE, name)
            assert tag is not None
            ids[name] = tag.id
        return ids


def now_of(db: Database) -> datetime:
    with db.session() as s:
        return server_now(s).replace(microsecond=0)


def ingest(db: Database, samples: list[dict[str, Any]]) -> dict[str, Any]:
    batch = BatchIn.model_validate({"source": SOURCE, "samples": samples})
    with db.session() as s:
        return ingest_batch(s, batch, now=server_now(s), late_window=WEEK).as_response()


def stored(db: Database, tag_id: int, ts: datetime) -> list[tuple[datetime, float, Quality]]:
    with db.session() as s:
        return read_samples(s, tag_id, ts - timedelta(seconds=1), ts + timedelta(seconds=1))


def test_arc_example_returns_the_documented_counts(clean_ingestion: Database) -> None:
    ids = register(clean_ingestion, "K101.TI1012.PV", "K101.ZI1015.PV")
    ts = now_of(clean_ingestion).isoformat()
    response = ingest(
        clean_ingestion,
        [
            {"tag": "K101.TI1012.PV", "ts": ts, "v": 78.42, "q": 0},
            {"tag": "K101.ZI1015.PV", "ts": ts, "v": 412.0, "q": "Good"},
            {"tag": "K101.TI1018.PV", "ts": ts, "v": 69.0, "q": "Bad"},
        ],
    )
    assert response == {"accepted": 2, "rejected": [{"index": 2, "reason": "unregistered_tag"}]}
    with clean_ingestion.session() as s:
        assert count_samples(s) == 2
    assert stored(clean_ingestion, ids["K101.TI1012.PV"], datetime.fromisoformat(ts))[0][1] == 78.42


def test_resending_a_batch_creates_no_duplicates(clean_ingestion: Database) -> None:
    register(clean_ingestion, "T1")
    ts = now_of(clean_ingestion).isoformat()
    batch = [{"tag": "T1", "ts": ts, "v": 1.0}]
    ingest(clean_ingestion, batch)
    ingest(clean_ingestion, batch)
    with clean_ingestion.session() as s:
        assert count_samples(s) == 1


def test_a_resend_with_a_new_value_replaces_the_old_one(clean_ingestion: Database) -> None:
    ids = register(clean_ingestion, "T1")
    ts = now_of(clean_ingestion)
    ingest(clean_ingestion, [{"tag": "T1", "ts": ts.isoformat(), "v": 1.0}])
    ingest(clean_ingestion, [{"tag": "T1", "ts": ts.isoformat(), "v": 2.0, "q": "Bad"}])
    assert stored(clean_ingestion, ids["T1"], ts) == [(ts, 2.0, Quality.BAD)]


def test_duplicates_inside_one_batch_keep_the_last(clean_ingestion: Database) -> None:
    ids = register(clean_ingestion, "T1")
    ts = now_of(clean_ingestion)
    response = ingest(
        clean_ingestion,
        [
            {"tag": "T1", "ts": ts.isoformat(), "v": 1.0},
            {"tag": "T1", "ts": ts.isoformat(), "v": 3.0},
        ],
    )
    assert response["accepted"] == 2
    assert [v for _, v, _ in stored(clean_ingestion, ids["T1"], ts)] == [3.0]


def test_late_and_future_samples(clean_ingestion: Database) -> None:
    register(clean_ingestion, "T1")
    now = now_of(clean_ingestion)
    response = ingest(
        clean_ingestion,
        [
            {"tag": "T1", "ts": (now - timedelta(days=6)).isoformat(), "v": 1.0},  # late: accepted
            {"tag": "T1", "ts": (now - timedelta(days=8)).isoformat(), "v": 1.0},
            {"tag": "T1", "ts": (now + timedelta(minutes=10)).isoformat(), "v": 1.0},
        ],
    )
    assert response == {
        "accepted": 1,
        "rejected": [{"index": 1, "reason": "too_old"}, {"index": 2, "reason": "in_future"}],
    }


def test_bad_samples_are_stored_and_flagged_with_their_code(clean_ingestion: Database) -> None:
    ids = register(clean_ingestion, "T1")
    ts = now_of(clean_ingestion)
    ingest(clean_ingestion, [{"tag": "T1", "ts": ts.isoformat(), "v": 5.0, "q": 0x80320000}])
    with clean_ingestion.session() as s:
        code = s.execute(
            text("SELECT quality, quality_code FROM sample WHERE tag_id = :t"),
            {"t": ids["T1"]},
        ).one()
    assert tuple(code) == (2, 0x80320000)


def test_unmapped_tags_are_listed_and_can_be_promoted(clean_ingestion: Database) -> None:
    register(clean_ingestion, "T1")
    ts = now_of(clean_ingestion).isoformat()
    ingest(clean_ingestion, [{"tag": "NEW.TAG", "ts": ts, "v": 1.0}] * 2)
    ingest(clean_ingestion, [{"tag": "NEW.TAG", "ts": ts, "v": 1.0}])
    with clean_ingestion.session() as s:
        unmapped = list_unmapped_tags(s, SOURCE)
        assert [(u.source_name, u.count) for u in unmapped] == [("NEW.TAG", 3)]
        assert unmapped[0].first_seen <= unmapped[0].last_seen
    with clean_ingestion.session() as s:
        promote_unmapped_tag(s, ACTOR, TagSpec(SOURCE, "NEW.TAG", "K-101", "bar", 0, 10, 60))
    with clean_ingestion.session() as s:
        assert list_unmapped_tags(s) == []
    assert ingest(clean_ingestion, [{"tag": "NEW.TAG", "ts": ts, "v": 1.0}])["accepted"] == 1


def test_source_statistics_are_kept(clean_ingestion: Database) -> None:
    register(clean_ingestion, "T1")
    ts = now_of(clean_ingestion)
    ingest(
        clean_ingestion,
        [
            {"tag": "T1", "ts": ts.isoformat(), "v": 1.0},
            {"tag": "NOPE", "ts": ts.isoformat(), "v": 1.0},
        ],
    )
    ingest(
        clean_ingestion, [{"tag": "T1", "ts": (ts - timedelta(minutes=1)).isoformat(), "v": 1.0}]
    )
    with clean_ingestion.session() as s:
        stats = source_stats(s, SOURCE)
    assert stats is not None
    assert (stats.accepted_total, stats.rejected_total) == (2, 1)
    assert stats.last_sample_ts == ts  # the newest sample, not the last one received


def test_a_scoped_engineer_cannot_take_another_sites_tag(clean_ingestion: Database) -> None:
    """Plan 6.7 (audit, ARC §9.2): moving a tag needs the registry right on both assets,
    and promoting cannot be used on a registered name."""
    from pmp.core import AccessDeniedError, Principal, Role, RoleAssignment
    from pmp.registry import RegistryError, find_asset, upsert_tag

    register(clean_ingestion, "T1")
    with clean_ingestion.session() as s:
        upsert_asset(s, ACTOR, AssetSpec("SITE-B", "Site B", AssetLevel.SITE))
        upsert_asset(
            s, ACTOR, AssetSpec("P-9", "P-9", AssetLevel.EQUIPMENT, "SITE-B", Criticality.B)
        )
        site_b = find_asset(s, "SITE-B")
        assert site_b is not None
    engineer_b = Actor.user(Principal(42, "pat", (RoleAssignment(Role.MODEL_ENGINEER, site_b.id),)))
    spec = TagSpec(SOURCE, "T1", "P-9", "bar", 0, 10, 60)
    with clean_ingestion.session() as s, pytest.raises(RegistryError, match="registered already"):
        promote_unmapped_tag(s, engineer_b, spec)
    with clean_ingestion.session() as s, pytest.raises(AccessDeniedError):
        upsert_tag(s, engineer_b, spec)
    with clean_ingestion.session() as s:  # an unscoped engineer may move it
        upsert_tag(s, ACTOR, spec)


def test_a_sample_without_a_value_is_refused_alone(clean_ingestion: Database) -> None:
    """Plan 6.7 (audit, AC-01): a Bad sample sent without a value loses only itself."""
    ids = register(clean_ingestion, "T1")
    ts = now_of(clean_ingestion)
    response = ingest(
        clean_ingestion,
        [
            {"tag": "T1", "ts": ts.isoformat(), "v": None, "q": "Bad"},
            {"tag": "T1", "ts": (ts - timedelta(minutes=1)).isoformat(), "v": 4.0, "q": "Bad"},
        ],
    )
    assert response["accepted"] == 1
    assert response["rejected"] == [{"index": 0, "reason": "no_value"}]
    assert [v for _, v, _ in stored(clean_ingestion, ids["T1"], ts - timedelta(minutes=1))] == [4.0]
