"""Time-series storage policy (plan 5.4; ARC §6.3, NFR-DATA-01, FR-RUN-03).

- Chunk intervals: sample and sensor_output 1 day, score 7 days.
- Compression after 7 days, segmented as ARC §6.3 says.
- Hourly aggregates with min, max, mean and count: sample_1h and score_1h (ARC §6.3), and
  sensor_output_1h (decision 5.4: the asset screen's 30-day sensor trends need it too).
  They are TimescaleDB continuous aggregates, refreshed every 30 minutes, with real-time
  aggregation so the latest hour is included.
- retention_policy: how long raw data and aggregates are kept; an administrator can
  change it, and the worker applies it daily (pmp.core.retention).

Without the TimescaleDB extension (a plain PostgreSQL, used only by the development test
sandbox) the aggregates are ordinary views over the same rows, so the application reads
them the same way; compression and chunk settings then do not apply.

Revision ID: 0011
Revises: 0010
Created: 2026-10-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | None = None
depends_on: str | None = None

COMPRESSION = {  # hypertable: segment by
    "sample": "tag_id",
    "score": "version_id",
    "sensor_output": "version_id, tag_id",
}

AGGREGATES = {
    "sample_1h": (
        "sample",
        "tag_id",
        "min(value) AS value_min, max(value) AS value_max, avg(value) AS value_mean, count(*) AS n",
    ),
    "score_1h": (
        "score",
        "model_id",
        "min(di) AS di_min, max(di) AS di_max, avg(di) AS di_mean, "
        "min(health) AS health_min, max(health) AS health_max, avg(health) AS health_mean, "
        "count(*) AS n",
    ),
    "sensor_output_1h": (
        "sensor_output",
        "version_id, tag_id",
        ", ".join(
            f"min({c}) AS {c}_min, max({c}) AS {c}_max, avg({c}) AS {c}_mean"
            for c in ("actual", "predicted", "residual", "q", "z")
        )
        + ", count(*) AS n",
    ),
}


def _timescale() -> bool:
    """The real extension (the development sandbox has a stand-in without these)."""
    found = op.get_bind().execute(
        sa.text("SELECT count(*) FROM pg_proc WHERE proname = 'add_compression_policy'")
    )
    return bool(found.scalar_one())


def upgrade() -> None:
    op.create_table(
        "retention_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("raw_months", sa.Integer(), nullable=False),
        sa.Column("aggregate_months", sa.Integer(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_result", sa.Text()),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("id = 1", name="ck_retention_policy_single_row"),
        sa.CheckConstraint(
            "raw_months >= 1 AND aggregate_months >= raw_months", name="ck_retention_policy_months"
        ),
    )
    # The row is written on first use, with PMP_RETENTION_MONTHS as the raw default.

    if not _timescale():
        for name, (table, keys, measures) in AGGREGATES.items():
            op.execute(
                f"CREATE VIEW {name} AS SELECT {keys}, date_trunc('hour', ts) AS bucket, "
                f"{measures} FROM {table} GROUP BY {keys}, date_trunc('hour', ts)"
            )
        return

    op.execute("SELECT set_chunk_time_interval('score', INTERVAL '7 days')")
    for table, segment in COMPRESSION.items():
        op.execute(
            f"ALTER TABLE {table} SET (timescaledb.compress, "
            f"timescaledb.compress_segmentby = '{segment}', "
            "timescaledb.compress_orderby = 'ts DESC')"
        )
        op.execute(f"SELECT add_compression_policy('{table}', INTERVAL '7 days')")

    # continuous aggregates cannot be created inside a transaction
    with op.get_context().autocommit_block():
        for name, (table, keys, measures) in AGGREGATES.items():
            op.execute(
                f"CREATE MATERIALIZED VIEW {name} WITH (timescaledb.continuous, "
                "timescaledb.materialized_only = false) AS "
                f"SELECT {keys}, time_bucket(INTERVAL '1 hour', ts) AS bucket, {measures} "
                f"FROM {table} GROUP BY {keys}, bucket WITH NO DATA"
            )
            op.execute(
                f"SELECT add_continuous_aggregate_policy('{name}', "
                "start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 hour', "
                "schedule_interval => INTERVAL '30 minutes')"
            )


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only (ARC-001 §10.4)")
