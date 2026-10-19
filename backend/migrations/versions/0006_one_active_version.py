"""At most one Deployed or Paused version per model (FR-MOD-07, ARC §6.2).

Revision ID: 0006
Revises: 0005
Created: 2026-10-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index(
        "ux_model_version_active",
        "model_version",
        ["model_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('Deployed', 'Paused')"),
    )


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only (ARC-001 §10.4)")
