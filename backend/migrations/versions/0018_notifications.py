"""Notifications (plan 8.5, UC-15, FR-NOT-01, UCS §6.10, ARC §4: subscription,
notification_log).

Subscriptions per user (scope, minimum priority, events, channel); one log row per
notification with its delivery state, retries and error; the notifier's cursors.

Revision ID: 0018
Revises: 0017
Created: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "subscription",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("app_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope_asset_id", sa.Integer(), sa.ForeignKey("asset.id", ondelete="CASCADE")),
        sa.Column("min_priority", sa.String(2), nullable=False),
        sa.Column("events", JSONB(), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False, server_default="email"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("min_priority IN ('P1', 'P2', 'P3', 'P4')", name="priority_valid"),
    )
    op.create_index("subscription_user", "subscription", ["user_id"])
    op.create_table(
        "notification_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("app_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event", sa.String(20), nullable=False),
        sa.Column("alert_id", sa.Integer(), sa.ForeignKey("alert.id", ondelete="SET NULL")),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("case.id", ondelete="SET NULL")),
        sa.Column("recipient", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("summary_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
    )
    op.create_index("notification_user_time", "notification_log", ["user_id", "created_at"])
    op.create_index("notification_status", "notification_log", ["status", "next_attempt_at"])
    op.create_table(
        "notifier_cursor",
        sa.Column("name", sa.String(30), primary_key=True),
        sa.Column("position", sa.BigInteger(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("notifier_cursor")
    op.drop_table("notification_log")
    op.drop_table("subscription")
