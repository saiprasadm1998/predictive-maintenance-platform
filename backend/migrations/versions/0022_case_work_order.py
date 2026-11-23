"""Work order reference on a case.

The maintenance system's work order that carries the case's field work, so the two records
can be matched.

Revision ID: 0022
Revises: 0021
Created: 2026-11-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("case", sa.Column("work_order", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("case", "work_order")
