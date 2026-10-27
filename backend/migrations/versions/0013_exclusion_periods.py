"""Training-data cleansing (plan 7.2).

A model version keeps the periods the engineer excluded on the training trend (UC-05
step 5) beside its training and validation periods.

Revision ID: 0013
Revises: 0012
Created: 2026-10-27
"""

from __future__ import annotations

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint("kind_valid", "training_period", type_="check")
    op.create_check_constraint(
        "kind_valid", "training_period", "kind IN ('training', 'validation', 'exclusion')"
    )


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only (ARC-001 §10.4)")
