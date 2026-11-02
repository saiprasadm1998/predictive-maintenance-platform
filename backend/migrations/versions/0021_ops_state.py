"""Operational state (plan 9.1, ARC §10.3).

Small named records the roles write for monitoring, e.g. the scheduler's last scoring
duration, so the web role can serve /metrics and the operational alerts.

Revision ID: 0021
Revises: 0020
Created: 2026-11-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "ops_state",
        sa.Column("name", sa.String(40), primary_key=True),
        sa.Column("data", JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ops_state")
