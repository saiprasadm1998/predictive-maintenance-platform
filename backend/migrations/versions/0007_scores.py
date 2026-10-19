"""Scoring outputs: score and sensor_output hypertables, runtime_status (ARC §6.2, §6.3).

Revision ID: 0007
Revises: 0006
Created: 2026-10-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # One row per model version and cycle. No foreign keys on the hypertables, as for
    # sample: the scoring cycle only writes IDs it has just read.
    op.create_table(
        "score",
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("band", sa.String(10), nullable=False),
        sa.Column("di", sa.Float()),
        sa.Column("health", sa.Float()),
        sa.Column("coverage", sa.Float(), nullable=False),
        sa.Column("envelope_flag", sa.Boolean()),  # filled by AAKR (Phase 7)
        sa.Column("reason", sa.Text()),
        sa.PrimaryKeyConstraint("version_id", "ts"),
    )
    op.execute("SELECT create_hypertable('score', by_range('ts', INTERVAL '1 day'))")
    op.create_index("ix_score_model_id_ts", "score", ["model_id", sa.text("ts DESC")])

    op.create_table(
        "sensor_output",
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual", sa.Float()),
        sa.Column("predicted", sa.Float()),
        sa.Column("residual", sa.Float()),
        sa.Column("q", sa.Float()),
        sa.Column("z", sa.Float()),
        sa.Column("contribution", sa.Float()),
        sa.Column("dq_status", sa.String(30), nullable=False),
        sa.PrimaryKeyConstraint("version_id", "tag_id", "ts"),
    )
    op.execute("SELECT create_hypertable('sensor_output', by_range('ts', INTERVAL '1 day'))")

    # The current runtime status per model (FR-RUN-04)
    op.create_table(
        "runtime_status",
        sa.Column(
            "model_id",
            sa.Integer(),
            sa.ForeignKey("model.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version_id", sa.Integer()),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("last_cycle", sa.DateTime(timezone=True)),
        sa.Column("since", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only (ARC-001 §10.4)")
