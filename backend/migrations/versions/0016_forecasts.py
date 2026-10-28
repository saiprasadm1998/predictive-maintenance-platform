"""Time-to-threshold forecasts (plan 8.3, UC-11, FR-PRG-01, -02, UCS §6.8).

One row per forecast run: target, threshold, window, fit, crossing time with its 80 %
interval and urgency, the 15-minute means it was fitted to, and the alert it is stored with.

Revision ID: 0016
Revises: 0015
Created: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "forecast",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "model_id", sa.Integer(), sa.ForeignKey("model.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("alert_id", sa.Integer(), sa.ForeignKey("alert.id", ondelete="SET NULL")),
        sa.Column("target", sa.String(10), nullable=False),
        sa.Column("tag_id", sa.Integer()),
        sa.Column("threshold_kind", sa.String(10), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("direction", sa.SmallInteger(), nullable=False),
        sa.Column("window_days", sa.Float(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.String(12)),
        sa.Column("params", JSONB(), nullable=False),
        sa.Column("r2", sa.Float()),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("median_h", sa.Float()),
        sa.Column("lower_h", sa.Float()),
        sa.Column("upper_h", sa.Float()),
        sa.Column("urgency", sa.String(10), nullable=False),
        sa.Column("series", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Integer()),
    )
    op.create_index("forecast_alert", "forecast", ["alert_id", "id"])
    op.create_index("forecast_model", "forecast", ["model_id", "id"])


def downgrade() -> None:
    op.drop_table("forecast")
