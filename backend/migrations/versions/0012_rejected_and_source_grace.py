"""Audit fixes (plan 6.7).

- A rejected version keeps its trained artefact and validation report with the status
  Rejected (PRD: a model version is immutable); the next draft takes a new number.
- Each gateway source may have its own scoring grace (ARC §5.1); NULL uses the default.

Revision ID: 0012
Revises: 0011
Created: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | None = None
depends_on: str | None = None

STATUSES = (
    "Draft",
    "Training",
    "Failed",
    "Validated",
    "Rejected",
    "Deployed",
    "Paused",
    "Superseded",
    "Retired",
)


def upgrade() -> None:
    op.drop_constraint("status_valid", "model_version", type_="check")
    statuses = ", ".join(f"'{s}'" for s in STATUSES)
    op.create_check_constraint("status_valid", "model_version", f"status IN ({statuses})")
    op.add_column("ingest_source", sa.Column("grace_s", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "grace_valid", "ingest_source", "grace_s IS NULL OR (grace_s >= 0 AND grace_s <= 600)"
    )


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only (ARC-001 §10.4)")
