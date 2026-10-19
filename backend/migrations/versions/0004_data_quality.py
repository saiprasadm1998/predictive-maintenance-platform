"""Data quality: dq_rule, sensor_status, sensor_exclusion (ARC §4, UCS §6.1).

Revision ID: 0004
Revises: 0003
Created: 2026-10-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Versioned rule overrides (UC-04: "rules are versioned and audited"). A save adds a
    # new version; the highest version for a scope is the current one.
    op.create_table(
        "dq_rule",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        # global: scope_key ''; role: '<asset_type>/<role>'; tag: '<tag id>'
        sa.Column("scope", sa.String(10), nullable=False),
        sa.Column("scope_key", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("params", JSONB(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.Integer()),
        sa.UniqueConstraint("scope", "scope_key", "version"),
        sa.CheckConstraint("scope IN ('global', 'role', 'tag')", name="scope_valid"),
        sa.CheckConstraint("version > 0", name="version_positive"),
    )

    # Current NE 107 status per sensor and the rule that set it (FR-DQ-02).
    op.create_table(
        "sensor_status",
        sa.Column(
            "tag_id",
            sa.Integer(),
            sa.ForeignKey("tag.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("rule", sa.String(30), nullable=False),
        sa.Column("effect", sa.String(20), nullable=False),
        sa.Column("since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Manual exclusions (UC-14). Read by the rules from 2.1; created and managed in 8.1.
    op.create_table(
        "sensor_exclusion",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "tag_id", sa.Integer(), sa.ForeignKey("tag.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cleared_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.Integer()),
        sa.CheckConstraint("starts_at < expires_at", name="period_valid"),
    )
    op.create_index("ix_sensor_exclusion_tag_id", "sensor_exclusion", ["tag_id"])


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only (ARC-001 §10.4)")
