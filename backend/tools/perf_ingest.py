"""NFR-PERF-04 check: ingestion sustains 10,000 samples/s through the REST batch endpoint.

Builds a separate `pmp_perf_ingest` database (dropped first) with 5,000 tags, starts the
web role as a real server (`pmp web`, PMP_WEB_WORKERS processes, default 2) and posts
batches of 5,000 samples (one per tag, each batch one second apart) from several client
threads for 30 seconds, counting what the server accepted.

    make perf-ingest
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from pmp.core import Actor, ApiKeyScope, Database, issue_api_key, run_migrations
from pmp.registry import AssetLevel, AssetSpec, Criticality, TagSpec, upsert_asset, upsert_tag

ASSETS, TAGS_PER_ASSET, SECONDS, CLIENTS, TARGET = 100, 50, 30.0, 6, 10_000
ACTOR = Actor.system()


def _url(name: str) -> str:
    admin_url = os.environ.get(
        "PMP_DATABASE_URL", "postgresql+psycopg://pmp:pmp@localhost:5433/pmp"
    )
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        connection.execute(text(f"CREATE DATABASE {name}"))
    admin.dispose()
    url = make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    run_migrations(url)
    return url


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_web(url: str, port: int, workers: int, **extra: str) -> subprocess.Popen[bytes]:
    """`pmp web` on 127.0.0.1:port against `url`; returns when /healthz answers."""
    env = {
        **os.environ,
        "PMP_DATABASE_URL": url,
        "PMP_SECRET_KEY": "perf",
        "PMP_WEB_WORKERS": str(workers),
        "PMP_LOG_LEVEL": "WARNING",
        "PMP_LOG_FORMAT": "text",
        "PMP_INGEST_RATE_LIMIT": "1000",
        **extra,
    }
    server = subprocess.Popen(
        [str(Path(sys.executable).with_name("pmp")), "web", "--no-migrate", "--port", str(port)],
        env=env,
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1)
            return server
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.3)
    server.terminate()
    raise SystemExit("The web role did not start")


def main() -> int:
    url = _url("pmp_perf_ingest")
    db = Database(url)
    names: list[str] = []
    with db.session() as s:
        upsert_asset(s, ACTOR, AssetSpec("SITE", "Site", AssetLevel.SITE))
        for i in range(ASSETS):
            code = f"EQ-{i:03d}"
            upsert_asset(
                s, ACTOR, AssetSpec(code, code, AssetLevel.EQUIPMENT, "SITE", Criticality.B)
            )
            for j in range(TAGS_PER_ASSET):
                names.append(f"{code}.T{j:02d}")
                upsert_tag(s, ACTOR, TagSpec("gw", names[-1], code, "u", 0.0, 200.0, 60))
        key = issue_api_key(s, ACTOR, name="perf", scope=ApiKeyScope.INGEST).key
    db.dispose()

    workers = int(os.environ.get("PMP_WEB_WORKERS", "2"))
    port = free_port()
    server = start_web(url, port, workers)
    endpoint = f"http://127.0.0.1:{port}/api/v1/ingest/samples"
    start = datetime.now(UTC).replace(microsecond=0) - timedelta(days=1)
    counter = iter(range(10**9))
    lock = threading.Lock()
    accepted = rejected = failures = 0

    def client(stop_at: float) -> None:
        nonlocal accepted, rejected, failures
        while time.monotonic() < stop_at:
            with lock:
                n = next(counter)
            ts = (start + timedelta(seconds=n)).isoformat()
            body = json.dumps(
                {"source": "gw", "samples": [{"tag": t, "ts": ts, "v": 100.0} for t in names]}
            ).encode()
            request = urllib.request.Request(
                endpoint,
                data=body,
                headers={"Authorization": f"ApiKey {key}", "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    answer = json.loads(response.read())
                with lock:
                    accepted += answer["accepted"]
                    rejected += len(answer["rejected"])
            except urllib.error.URLError:
                with lock:
                    failures += 1

    print(
        f"Posting {len(names)}-sample batches from {CLIENTS} clients for {SECONDS:.0f} s "
        f"to {workers} web processes ...",
        flush=True,
    )
    began = time.monotonic()
    threads = [threading.Thread(target=client, args=(began + SECONDS,)) for _ in range(CLIENTS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.monotonic() - began
    server.terminate()
    server.wait(timeout=30)

    rate = accepted / elapsed
    print(
        f"Accepted {accepted:,} samples in {elapsed:.1f} s: {rate:,.0f} samples/s "
        f"(target {TARGET:,}); {rejected} rejected, {failures} failed requests"
    )
    return 0 if rate >= TARGET and rejected == 0 and failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
