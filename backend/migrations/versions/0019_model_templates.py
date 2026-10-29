"""Asset-type model templates (plan 8.6, UC-07, FR-MOD-08).

A template is a model definition written with the asset type's roles instead of tags:
applied to assets of the type, each role resolves to the asset's tag.

Revision ID: 0019
Revises: 0018
Created: 2026-10-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "model_template",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "asset_type_id",
            sa.Integer(),
            sa.ForeignKey("asset_type.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("definition", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Integer()),
        sa.UniqueConstraint("asset_type_id", "name", name="template_name_unique"),
    )


def downgrade() -> None:
    op.drop_table("model_template")
