"""Backup runs (plan 9.1, ARC §10.1, NFR-REL-03).

Each `pmp backup` records its outcome, so a failed backup can be shown to administrators
(ARC §10.3) by the web role, which cannot see the backup volume.

Revision ID: 0020
Revises: 0019
Created: 2026-10-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "backup_run",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("dump_bytes", sa.BigInteger(), nullable=True),
        sa.Column("artefact_bytes", sa.BigInteger(), nullable=True),
        sa.Column("removed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name="backup_run_status"
        ),
    )


def downgrade() -> None:
    op.drop_table("backup_run")
