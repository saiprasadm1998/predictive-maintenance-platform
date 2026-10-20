"""Users, role assignments and sessions (plan 5.1; FR-SEC-01, ARC §4 core: user, role).

The user table is `app_user` because `user` is reserved in PostgreSQL.

Revision ID: 0010
Revises: 0009
Created: 2026-10-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | None = None
depends_on: str | None = None

ROLES = ("viewer", "analyst", "maintenance", "model_engineer", "administrator")


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(200)),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    # usernames are unique whatever their case
    op.execute("CREATE UNIQUE INDEX ux_app_user_username ON app_user (lower(username))")

    op.create_table(
        "user_role",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("app_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(30), nullable=False),
        # optional hierarchy scope ("Analyst for Site A only", ARC §9.2)
        sa.Column("scope_asset_id", sa.Integer(), sa.ForeignKey("asset.id")),
        sa.CheckConstraint(
            "role IN (" + ", ".join(f"'{r}'" for r in ROLES) + ")", name="ck_user_role_role"
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_user_role ON user_role (user_id, role, scope_asset_id) "
        "NULLS NOT DISTINCT"
    )

    op.create_table(
        "user_session",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("app_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", INET()),
    )
    op.create_index("ix_user_session_user_id", "user_session", ["user_id"])


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only (ARC-001 §10.4)")
