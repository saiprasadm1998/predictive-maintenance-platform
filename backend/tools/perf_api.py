"""NFR-PERF-03 checks for the API: a 30-day trend of 20 sensors (the browser must render it
in under 3 s, so the API gets 1.5 s of that), filtering 1,000 alerts (under 1 s), and the
reads the fleet overview makes for a 500-asset fleet (the screen must load in under 2 s,
plan 6.2, so the API gets 1 s of that).

Builds a separate `pmp_perf_api` database (dropped first) with one model of 20 sensors and
30 days of one-minute sensor outputs (864,000 rows), 1,000 alerts, and a fleet of 500
monitored assets (5 sites, 50 units, each asset with a deployed, scored model), then times
the endpoints through the real application.

    make perf-api
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from pmp.api import create_app
from pmp.core import Actor, Database, Role, RoleAssignment, Settings, create_user, run_migrations

TREND_BUDGET_S, ALERT_BUDGET_S, SENSORS, DAYS = 1.5, 1.0, 20, 30
FLEET_BUDGET_S, SITES, UNITS_PER_SITE, ASSETS_PER_UNIT = 1.0, 5, 10, 10
FLEET_READS: list[tuple[str, dict[str, Any]]] = [  # what the fleet overview reads on opening
    ("/api/v1/assets", {"tree": "true"}),
    ("/api/v1/fleet/kpis", {}),
    ("/api/v1/models", {}),
    ("/api/v1/alerts", {"limit": 100}),
]
PASSWORD = "check-the-api-speed"


def _url() -> str:
    admin_url = os.environ.get(
        "PMP_DATABASE_URL", "postgresql+psycopg://pmp:pmp@localhost:5433/pmp"
    )
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text("DROP DATABASE IF EXISTS pmp_perf_api WITH (FORCE)"))
        connection.execute(text("CREATE DATABASE pmp_perf_api"))
    admin.dispose()
    url = make_url(admin_url).set(database="pmp_perf_api").render_as_string(hide_password=False)
    run_migrations(url)
    return url


def _setup(db: Database, end: datetime) -> int:
    """Rows are written with SQL directly: this checks reading, not writing."""
    with db.session() as s:
        s.execute(
            text(
                "INSERT INTO asset (id, code, name, level, path, criticality) "
                "VALUES (1, 'K-1', 'Compressor', 5, '1', 'A')"
            )
        )
        s.execute(
            text(
                "INSERT INTO tag (source, source_name, asset_id, description, unit, range_lo, "
                "range_hi, interval_s) SELECT 'gw', 'K1.T' || i, 1, '', 'u', 0, 100, 60 "
                "FROM generate_series(1, :n) i"
            ),
            {"n": SENSORS},
        )
        model_id = s.execute(
            text("INSERT INTO model (asset_id, name) VALUES (1, 'main') RETURNING id")
        ).scalar_one()
        version_id = s.execute(
            text(
                "INSERT INTO model_version (model_id, version, status, algorithm, params) "
                "VALUES (:m, 1, 'Deployed', 'median', '{}') RETURNING id"
            ),
            {"m": model_id},
        ).scalar_one()
        s.execute(
            text(
                "INSERT INTO model_sensor (version_id, tag_id, position, required) "
                "SELECT :v, id, row_number() OVER (ORDER BY id) - 1, false FROM tag"
            ),
            {"v": version_id},
        )
        s.execute(
            text(
                "INSERT INTO sensor_output (version_id, tag_id, ts, actual, predicted, residual, "
                "q, z, contribution, dq_status, dq_rule, used) "
                "SELECT :v, t.id, ts, 50 + sin(m / 60.0), 50, sin(m / 60.0), 0.01, 0.5, 0.05, "
                "'Good', 'none', true FROM tag t, "
                "generate_series(0, :minutes - 1) m, "
                "LATERAL (SELECT :end - m * interval '1 minute' AS ts) x"
            ),
            {"v": version_id, "minutes": DAYS * 1440, "end": end},
        )
        s.execute(
            text(
                "INSERT INTO alert (model_id, kind, state, severity, priority, condition_active, "
                "raised_at, version_id, trace) SELECT :m, 'di', (ARRAY['Active-Unacknowledged',"
                "'Active-Acknowledged','RTN-Unacknowledged','Shelved'])[1 + i % 4], 'Warning', "
                "'P' || (1 + i % 4), true, :end - i * interval '1 minute', :v, '{}' "
                "FROM generate_series(1, 1000) i"
            ),
            {"m": model_id, "v": version_id, "end": end},
        )
        _fleet(s, end)
        create_user(
            s,
            Actor.system(),
            username="perf",
            display_name="perf",
            password=PASSWORD,
            assignments=[RoleAssignment(Role.VIEWER)],
        )
    return int(model_id)


def _fleet(s: Any, end: datetime) -> None:
    """5 sites x 10 units x 10 assets, each asset with a deployed model scored at `end`."""
    s.execute(
        text("INSERT INTO asset (id, code, name, level, path) VALUES (2, 'ENT', 'Fleet', 1, '2')")
    )
    next_id = 3
    for site in range(SITES):
        site_id = next_id
        next_id += 1
        s.execute(
            text(
                "INSERT INTO asset (id, parent_id, code, name, level, path) "
                "VALUES (:id, 2, :c, :c, 2, :p)"
            ),
            {"id": site_id, "c": f"S{site}", "p": f"2.{site_id}"},
        )
        for unit in range(UNITS_PER_SITE):
            unit_id = next_id
            next_id += 1
            s.execute(
                text(
                    "INSERT INTO asset (id, parent_id, code, name, level, path) "
                    "VALUES (:id, :parent, :c, :c, 4, :p)"
                ),
                {
                    "id": unit_id,
                    "parent": site_id,
                    "c": f"S{site}U{unit}",
                    "p": f"2.{site_id}.{unit_id}",
                },
            )
            s.execute(
                text(
                    "INSERT INTO asset (id, parent_id, code, name, level, path, criticality) "
                    "SELECT :first + i, :parent, :prefix || i, 'Pump ' || :prefix || i, 5, "
                    "(:path || '.' || (:first + i))::ltree, 'B' FROM generate_series(0, :n - 1) i"
                ),
                {
                    "first": next_id,
                    "parent": unit_id,
                    "prefix": f"S{site}U{unit}E",
                    "path": f"2.{site_id}.{unit_id}",
                    "n": ASSETS_PER_UNIT,
                },
            )
            next_id += ASSETS_PER_UNIT
    s.execute(text("SELECT setval(pg_get_serial_sequence('asset', 'id'), :n)"), {"n": next_id})
    s.execute(
        text(
            "INSERT INTO model (asset_id, name) SELECT id, 'main' FROM asset WHERE level = 5 "
            "AND code <> 'K-1'"
        )
    )
    s.execute(
        text(
            "INSERT INTO model_version (model_id, version, status, algorithm, params) "
            "SELECT id, 1, 'Deployed', 'median', '{}' FROM model m WHERE NOT EXISTS "
            "(SELECT 1 FROM model_version v WHERE v.model_id = m.id)"
        )
    )
    s.execute(
        text(
            "INSERT INTO score (version_id, ts, model_id, status, band, di, health, coverage) "
            "SELECT v.id, :end, v.model_id, 'Running', (ARRAY['Healthy','Healthy','Watch',"
            "'Alert'])[1 + v.id % 4], 5 + v.id % 30, 95 - v.id % 60, 1 FROM model_version v "
            "WHERE NOT EXISTS (SELECT 1 FROM score x WHERE x.version_id = v.id)"
        ),
        {"end": end},
    )
    s.execute(
        text(
            "INSERT INTO runtime_status (model_id, version_id, status, last_cycle, since) "
            "SELECT model_id, id, 'Running', :end, :end FROM model_version v WHERE NOT EXISTS "
            "(SELECT 1 FROM runtime_status r WHERE r.model_id = v.model_id)"
        ),
        {"end": end},
    )


def main() -> int:
    url = _url()
    db = Database(url)
    end = datetime.now(UTC).replace(second=0, microsecond=0)
    print(
        f"Writing {DAYS} days x {SENSORS} sensors of outputs, 1,000 alerts and a 500-asset "
        "fleet ...",
        flush=True,
    )
    model_id = _setup(db, end)
    settings = Settings(
        database_url=url,
        secret_key="perf",
        artefact_dir=Path(tempfile.mkdtemp()),
        _env_file=None,
    )
    failed = False
    with TestClient(create_app(settings=settings, database=db), base_url="https://perf") as client:
        token = client.post(
            "/api/v1/auth/token", json={"username": "perf", "password": PASSWORD}
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        start = (end - timedelta(days=DAYS)).isoformat()
        checks: list[tuple[str, str, dict[str, Any], float]] = [
            (
                "30-day trend, 20 sensors",
                f"/api/v1/models/{model_id}/outputs",
                {"from": start, "to": end.isoformat(), "px": 1000},
                TREND_BUDGET_S,
            ),
            (
                "1,000 alerts filtered",
                "/api/v1/alerts",
                {"priority": ["P1", "P2"], "limit": 1000},
                ALERT_BUDGET_S,
            ),
        ]
        began = time.perf_counter()
        sizes = 0
        for path, params in FLEET_READS:
            one = time.perf_counter()
            response = client.get(path, params=params, headers=headers)
            if os.environ.get("PMP_PERF_DETAIL"):
                print(f"  {path}: {time.perf_counter() - one:.2f} s")
            failed |= response.status_code != 200
            sizes += len(response.content)
        elapsed = time.perf_counter() - began
        ok = elapsed <= FLEET_BUDGET_S
        failed |= not ok
        print(
            f"Fleet overview reads, 500 assets: {elapsed:.2f} s, {sizes / 1024:.0f} KB "
            f"(budget {FLEET_BUDGET_S} s) {'OK' if ok else 'FAILED'}"
        )
        for name, path, params, budget in checks:
            began = time.perf_counter()
            response = client.get(path, params=params, headers=headers)
            elapsed = time.perf_counter() - began
            ok = response.status_code == 200 and elapsed <= budget
            failed |= not ok
            size = len(response.content) / 1024
            print(
                f"{name}: {elapsed:.2f} s, {size:.0f} KB (budget {budget} s) "
                f"{'OK' if ok else 'FAILED'}"
            )
    db.dispose()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
