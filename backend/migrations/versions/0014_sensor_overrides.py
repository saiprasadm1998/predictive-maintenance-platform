"""Sensor overrides (plan 8.1, UC-14 1a).

A manual entry on a sensor either excludes it (Function check) or overrides an automatic
status to Good; both carry a reason and an expiry.

Revision ID: 0014
Revises: 0013
Created: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "sensor_exclusion",
        sa.Column("kind", sa.String(10), nullable=False, server_default="exclude"),
    )
    op.create_check_constraint("kind_valid", "sensor_exclusion", "kind IN ('exclude', 'override')")


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only (ARC-001 §10.4)")
