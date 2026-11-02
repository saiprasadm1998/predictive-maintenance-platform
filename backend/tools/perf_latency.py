"""NFR-PERF-02 / AC-05 check: a new score reaches the browser within one cycle plus 5 s.

Builds a separate `pmp_perf_latency` database (dropped first) with one deployed model of
four sensors, then runs the real pieces on the wall clock: the web role as a server, the
scoring scheduler (the default grace), a gateway posting the four sensors every 5 s
through the REST endpoint, and a browser-like client on the live event stream.

A sample accepted just after cycle C - 60 is first scored in cycle C, so the worst-case
latency from acceptance to the browser is one cycle plus how long after its boundary
cycle C reaches the browser (the grace plus scoring and delivery). The check records that
delay for every cycle over 4 cycles and the latency of each sample batch.

    make perf-latency     (about 5 minutes)
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import urllib.request
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from perf_ingest import _url, free_port, start_web  # tools/ is the script directory
from sqlalchemy import text

from pmp.alerting import AlertRuleSpec, RuleKind, set_alert_rules
from pmp.core import (
    Actor,
    ApiKeyScope,
    Database,
    Role,
    RoleAssignment,
    Settings,
    create_user,
    issue_api_key,
)
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

CYCLE_S, CYCLES, FEED_S, BUDGET_S = 60, 4, 5, 5.0
GRACE_S = int(Settings.model_fields["scoring_grace_s"].default)  # the shipped default
TAGS = ("EQ1.T1", "EQ1.T2", "EQ1.T3", "EQ1.T4")
ACTOR = Actor.system()
PASSWORD = "check-the-latency-now"


def _setup(db: Database, artefacts: Path, now: datetime) -> str:
    with db.session() as s:
        upsert_asset(s, ACTOR, AssetSpec("SITE", "Site", AssetLevel.SITE))
        upsert_asset(
            s, ACTOR, AssetSpec("EQ-1", "Pump", AssetLevel.EQUIPMENT, "SITE", Criticality.B)
        )
        for tag in TAGS:
            upsert_tag(s, ACTOR, TagSpec("gw", tag, "EQ-1", "u", 0.0, 200.0, FEED_S))
        ids: dict[str, int] = dict(s.execute(text("SELECT source_name, id FROM tag")).all())
        write_samples(
            s,
            [
                SampleRow(
                    int(ids[t]), now - timedelta(seconds=k * FEED_S), 100.0, Quality.GOOD, None
                )
                for t in TAGS
                for k in range(1, 60)
            ],
        )
        model = save_draft(
            s,
            ACTOR,
            ModelDefinition(
                asset_code="EQ-1",
                name="main",
                sensors=tuple(SensorChoice(t) for t in TAGS),
                training_periods=(Period(now - timedelta(days=30), now - timedelta(days=10)),),
                validation_period=Period(now - timedelta(days=10), now - timedelta(days=1)),
            ),
        )
        set_alert_rules(s, ACTOR, model.id, [AlertRuleSpec(RuleKind.DI, 15, 25)])
        detector = MedianDetector()
        rng = np.random.default_rng(1)
        detector.fit(pd.DataFrame(rng.normal(0, 0.1, (50, len(TAGS))), columns=list(TAGS)), {})
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
            for t in TAGS
        }
        sha = write_artefact(
            target,
            detector,
            scaling={"sensor_order": list(TAGS), "sensors": sensors},
            manifest={"algorithm": "median"},
            validation={},
        )
        s.execute(
            text(
                "UPDATE model_version SET status = 'Validated', artefact_path = :p, "
                "artefact_sha256 = :sha, params = :params WHERE model_id = :m"
            ),
            {
                "p": str(target),
                "sha": sha,
                "m": model.id,
                "params": json.dumps({"cycle_s": CYCLE_S}),
            },
        )
        create_user(
            s,
            ACTOR,
            username="watcher",
            display_name="Watcher",
            password=PASSWORD,
            assignments=[RoleAssignment(Role.VIEWER)],
        )
        key = issue_api_key(s, ACTOR, name="gateway", scope=ApiKeyScope.INGEST).key
    with db.session() as s:
        change_status(s, ACTOR, "EQ-1", "main", Action.DEPLOY)
    return key


def _post(url: str, body: Mapping[str, object], headers: dict[str, str]) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        answer: dict[str, object] = json.loads(response.read())
        return answer


def main() -> int:
    url = _url("pmp_perf_latency")
    db = Database(url)
    stop = threading.Event()
    accepted: list[float] = []  # wall-clock times the gateway's batches were accepted
    events: list[tuple[float, datetime]] = []  # (arrival, cycle) of score.updated
    with tempfile.TemporaryDirectory() as tmp:
        key = _setup(db, Path(tmp), datetime.now(UTC))
        port = free_port()
        server = start_web(url, port, 1, PMP_ARTEFACT_DIR=tmp)
        base = f"http://127.0.0.1:{port}/api/v1"
        token = _post(f"{base}/auth/token", {"username": "watcher", "password": PASSWORD}, {})

        def gateway() -> None:
            while not stop.wait(FEED_S - time.time() % FEED_S):
                now = datetime.now(UTC)
                body = {
                    "source": "gw",
                    "samples": [{"tag": t, "ts": now.isoformat(), "v": 100.0} for t in TAGS],
                }
                _post(f"{base}/ingest/samples", body, {"Authorization": f"ApiKey {key}"})
                accepted.append(time.time())

        def browser() -> None:
            request = urllib.request.Request(
                f"{base}/events", headers={"Authorization": f"Bearer {token['access_token']}"}
            )
            with urllib.request.urlopen(request, timeout=120) as stream:
                for raw in stream:
                    if stop.is_set():
                        return
                    line = raw.decode().strip()
                    if not line.startswith("data:"):
                        continue
                    event = json.loads(line.removeprefix("data:"))
                    if event.get("type") == "score.updated":
                        events.append((time.time(), datetime.fromisoformat(event["ts"])))

        scheduler = Scheduler(db, grace_s=GRACE_S)
        threads = [
            threading.Thread(target=gateway, daemon=True),
            threading.Thread(target=browser, daemon=True),
            threading.Thread(target=scheduler.run_forever, args=(stop,), daemon=True),
        ]
        for thread in threads:
            thread.start()
        print(f"Running {CYCLES} cycles of {CYCLE_S} s on the wall clock ...", flush=True)
        started = time.time()
        while len(events) < CYCLES + 1 and time.time() - started < (CYCLES + 3) * CYCLE_S:
            time.sleep(1)
        stop.set()
        server.terminate()
        server.wait(timeout=30)
    db.dispose()

    measured = events[1:]  # the first cycle may have been due when the scheduler started
    if not measured:
        print("No score reached the event stream")
        return 1
    delays = [arrival - cycle.timestamp() for arrival, cycle in measured]
    worst_batch = 0.0
    for arrival, cycle in measured:  # the first batch accepted after the previous cycle
        newest = [t for t in accepted if cycle.timestamp() - CYCLE_S < t <= cycle.timestamp()]
        if newest:
            worst_batch = max(worst_batch, arrival - min(newest))
    for (_, cycle), delay in zip(measured, delays, strict=True):
        print(f"  cycle {cycle:%H:%M:%S} reached the browser {delay:.2f} s after its boundary")
    print(
        f"Worst: {max(delays):.2f} s after the cycle boundary (budget {BUDGET_S:.0f} s, grace "
        f"{GRACE_S} s); worst sample-to-browser latency {worst_batch:.1f} s (budget "
        f"{CYCLE_S + BUDGET_S:.0f} s)"
    )
    return 0 if max(delays) <= BUDGET_S and worst_batch <= CYCLE_S + BUDGET_S else 1


if __name__ == "__main__":
    sys.exit(main())
