"""Failure-mode library (plan 8.2, UC-16, FR-DIA-02, FR-ADV-01).

Failure modes per asset type, each kept as versions: name, ISO 14224 code, symptoms (role,
expected direction, weight) and recommended tasks.

Revision ID: 0015
Revises: 0014
Created: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "failure_mode",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "asset_type_id",
            sa.Integer(),
            sa.ForeignKey("asset_type.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("asset_type_id", "code", name="code_unique"),
    )
    op.create_table(
        "failure_mode_version",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "failure_mode_id",
            sa.Integer(),
            sa.ForeignKey("failure_mode.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("iso_code", sa.String(32)),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("symptoms", JSONB(), nullable=False),
        sa.Column("tasks", JSONB(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Integer()),
        sa.UniqueConstraint("failure_mode_id", "version", name="version_unique"),
        sa.CheckConstraint("version > 0", name="version_positive"),
    )


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only (ARC-001 §10.4)")
