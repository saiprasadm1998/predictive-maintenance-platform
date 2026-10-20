"""Spec alignment (plan 4.4): per-cycle data-quality state on sensor outputs (UCS §6.1),
and alert rules out of service with their model (UCS Figure 6).

Revision ID: 0009
Revises: 0008
Created: 2026-10-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # dq_status now holds the NE 107 status ("Good", "Failure", ...); the rule that set it
    # and whether the value was used are kept beside it. Older rows keep usable/excluded.
    op.add_column("sensor_output", sa.Column("dq_rule", sa.String(30)))
    op.add_column("sensor_output", sa.Column("used", sa.Boolean()))
    op.add_column(
        "alert_rule_state",
        sa.Column("out_of_service", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only (ARC-001 §10.4)")
