"""NFR-PERF-03 checks for the API: a 30-day trend of 20 sensors (the browser must render it
in under 3 s, so the API gets 1.5 s of that) and filtering 1,000 alerts (under 1 s).

Builds a separate `pmp_perf_api` database (dropped first) with one model of 20 sensors and
30 days of one-minute sensor outputs (864,000 rows) and 1,000 alerts, then times the
endpoints through the real application.

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
        create_user(
            s,
            Actor.system(),
            username="perf",
            display_name="perf",
            password=PASSWORD,
            assignments=[RoleAssignment(Role.VIEWER)],
        )
    return int(model_id)


def main() -> int:
    url = _url()
    db = Database(url)
    end = datetime.now(UTC).replace(second=0, microsecond=0)
    print(f"Writing {DAYS} days x {SENSORS} sensors of outputs and 1,000 alerts ...", flush=True)
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
