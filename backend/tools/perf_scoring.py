"""NFR-PERF-01 check: 100 models with 5,000 tags scored within 30 s of the cycle start.

Builds a separate `pmp_perf` database next to the development one (dropped first), with
100 assets of 50 tags each, one deployed model per asset, and 40 minutes of 1-minute
samples. The models' artefacts are written directly from synthetic training data, so the
check measures scoring, not training. Then one scheduler tick scores the latest cycle.

    make perf-scoring
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from pmp.alerting import AlertRuleSpec, RuleKind, set_alert_rules
from pmp.core import Actor, Database, run_migrations
from pmp.ingestion import Quality, SampleRow, write_samples
from pmp.modelling import (
    Action,
    MedianDetector,
    ModelDefinition,
    Period,
    SensorChoice,
    change_status,
    save_draft,
)
from pmp.modelling.artefacts import artefact_dir, write_artefact
from pmp.registry import AssetLevel, AssetSpec, Criticality, TagSpec, upsert_asset, upsert_tag
from pmp.scoring import Scheduler

MODELS, TAGS_PER_MODEL, MINUTES, BUDGET_S = 100, 50, 40, 30.0
ACTOR = Actor.system()


def _database() -> Database:
    admin_url = os.environ.get(
        "PMP_DATABASE_URL", "postgresql+psycopg://pmp:pmp@localhost:5433/pmp"
    )
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text("DROP DATABASE IF EXISTS pmp_perf WITH (FORCE)"))
        connection.execute(text("CREATE DATABASE pmp_perf"))
    admin.dispose()
    url = make_url(admin_url).set(database="pmp_perf").render_as_string(hide_password=False)
    run_migrations(url)
    return Database(url)


def _setup(db: Database, artefacts: Path, now: datetime) -> None:
    names = [f"T{j:02d}" for j in range(TAGS_PER_MODEL)]
    with db.session() as s:
        upsert_asset(s, ACTOR, AssetSpec("SITE", "Site", AssetLevel.SITE))
        for i in range(MODELS):
            code = f"EQ-{i:03d}"
            upsert_asset(
                s, ACTOR, AssetSpec(code, code, AssetLevel.EQUIPMENT, "SITE", Criticality.B)
            )
            for name in names:
                upsert_tag(s, ACTOR, TagSpec("gw", f"{code}.{name}", code, "u", 0.0, 200.0, 60))
    start = now - timedelta(minutes=MINUTES)
    with db.session() as s:
        ids: dict[str, int] = {
            str(n): int(i) for n, i in s.execute(text("SELECT source_name, id FROM tag")).all()
        }
        rows = [
            SampleRow(
                tag_id,
                start + timedelta(minutes=m),
                100 + 5 * math.sin(m / 7 + tag_id),
                Quality.GOOD,
                None,
            )
            for tag_id in ids.values()
            for m in range(MINUTES + 1)
        ]
        write_samples(s, rows)

    rng = np.random.default_rng(1)
    for i in range(MODELS):
        code = f"EQ-{i:03d}"
        tags = [f"{code}.{n}" for n in names]
        with db.session() as s:
            model = save_draft(
                s,
                ACTOR,
                ModelDefinition(
                    asset_code=code,
                    name="main",
                    sensors=tuple(SensorChoice(t) for t in tags),
                    training_periods=(Period(now - timedelta(days=30), now - timedelta(days=10)),),
                    validation_period=Period(now - timedelta(days=10), now - timedelta(days=1)),
                ),
            )
            set_alert_rules(s, ACTOR, model.id, [AlertRuleSpec(RuleKind.DI, 15, 25)])
            detector = MedianDetector()
            detector.fit(pd.DataFrame(rng.normal(0, 0.1, (50, len(tags))), columns=tags), {})
            target = artefact_dir(artefacts, model.id, 1)
            sensors = {
                t: {
                    "median": 100.0,
                    "p1": 90.0,
                    "p99": 110.0,
                    "std": 3.5,
                    "range": 20.0,
                    "range_floored": False,
                    "residual_sigma_raw": 3.0,
                    "sigma": 3.0,
                    "sigma_floored": False,
                }
                for t in tags
            }
            sha = write_artefact(
                target,
                detector,
                scaling={"sensor_order": tags, "sensors": sensors},
                manifest={"algorithm": "median"},
                validation={},
            )
            s.execute(
                text(
                    "UPDATE model_version SET status = 'Validated', artefact_path = :p, "
                    "artefact_sha256 = :sha, params = '{\"cycle_s\": 60}' WHERE model_id = :m"
                ),
                {"p": str(target), "sha": sha, "m": model.id},
            )
        with db.session() as s:
            change_status(s, ACTOR, code, "main", Action.DEPLOY)


def main() -> int:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    db = _database()
    with tempfile.TemporaryDirectory() as tmp:
        print(f"Setting up {MODELS} models x {TAGS_PER_MODEL} tags ...", flush=True)
        _setup(db, Path(tmp), now)
        scheduler = Scheduler(db, grace_s=0, clock=lambda: now + timedelta(seconds=1))
        started = time.perf_counter()
        results = scheduler.tick()
        elapsed = time.perf_counter() - started
    db.dispose()
    running = sum(r.status.value == "Running" for r in results)
    print(
        f"Scored {len(results)} models ({running} Running, "
        f"{MODELS * TAGS_PER_MODEL} tags) in {elapsed:.1f} s (budget {BUDGET_S:.0f} s)"
    )
    return 0 if len(results) == MODELS and running == MODELS and elapsed <= BUDGET_S else 1


if __name__ == "__main__":
    sys.exit(main())
