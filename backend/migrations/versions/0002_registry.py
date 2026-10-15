"""Registry: asset hierarchy (ltree), tags, asset types, roles and tag-role map.

Revision ID: 0002
Revises: 0001
Created: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS ltree")

    op.create_table(
        "asset_type",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )

    op.create_table(
        "type_role",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "asset_type_id",
            sa.Integer(),
            sa.ForeignKey("asset_type.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("unit", sa.String(50), nullable=False, server_default=""),
        sa.UniqueConstraint("asset_type_id", "code"),
    )

    op.create_table(
        "asset",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("asset.id")),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),  # converted to ltree below
        sa.Column("asset_type_id", sa.Integer(), sa.ForeignKey("asset_type.id")),
        sa.Column("criticality", sa.String(1)),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("level BETWEEN 1 AND 5", name="level_valid"),
        sa.CheckConstraint("criticality IN ('A', 'B', 'C')", name="criticality_valid"),
    )
    op.create_index("ix_asset_parent_id", "asset", ["parent_id"])

    op.create_table(
        "tag",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("source_name", sa.String(200), nullable=False),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("asset.id"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("unit", sa.String(50), nullable=False),
        sa.Column("range_lo", sa.Float(), nullable=False),
        sa.Column("range_hi", sa.Float(), nullable=False),
        sa.Column("interval_s", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("source", "source_name"),
        sa.CheckConstraint("range_lo < range_hi", name="range_valid"),
        sa.CheckConstraint("interval_s > 0", name="interval_positive"),
    )
    op.create_index("ix_tag_asset_id", "tag", ["asset_id"])

    op.create_table(
        "tag_role_map",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "asset_id", sa.Integer(), sa.ForeignKey("asset.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "type_role_id",
            sa.Integer(),
            sa.ForeignKey("type_role.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tag_id", sa.Integer(), sa.ForeignKey("tag.id", ondelete="CASCADE"), nullable=False
        ),
        sa.UniqueConstraint("asset_id", "type_role_id"),
        sa.UniqueConstraint("tag_id"),
    )

    # The path column is ltree; set its type and the indexes that make subtree queries fast.
    op.execute("ALTER TABLE asset ALTER COLUMN path TYPE ltree USING path::ltree")
    op.create_unique_constraint("uq_asset_path", "asset", ["path"])
    op.execute("CREATE INDEX ix_asset_path_gist ON asset USING gist (path)")


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only (ARC-001 §10.4)")
