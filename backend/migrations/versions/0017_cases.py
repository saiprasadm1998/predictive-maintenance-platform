"""Cases (plan 8.4, UC-12, UC-13, FR-CAS-01 to -03, UCS §6.9, ARC §6).

A case links one or more alerts of one asset (an alert to only one open case: a partial
unique index), keeps an immutable snapshot taken at creation (a trigger refuses changes),
and logs its activities: comments, attachments, actions, state changes and assignments.

Revision ID: 0017
Revises: 0016
Created: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "case",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),  # C-nnnn
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(2), nullable=False),
        sa.Column("priority_set", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "asset_id", sa.Integer(), sa.ForeignKey("asset.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("assignee_id", sa.Integer(), sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.Column("due", sa.Date()),
        sa.Column("outcome", sa.String(20)),
        sa.Column(
            "confirmed_mode_id",
            sa.Integer(),
            sa.ForeignKey("failure_mode.id", ondelete="SET NULL"),
        ),
        sa.Column("value_estimate", sa.Float()),
        sa.Column("lessons", sa.Text()),
        sa.Column("cancel_reason", sa.Text()),
        sa.Column("review_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Integer()),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("case_status", "case", ["status", "priority"])
    op.create_index("case_asset", "case", ["asset_id"])
    op.execute(
        """
        CREATE FUNCTION case_snapshot_immutable() RETURNS trigger AS $$
        BEGIN
          IF NEW.snapshot IS DISTINCT FROM OLD.snapshot THEN
            RAISE EXCEPTION 'A case snapshot cannot be changed (FR-CAS-01)';
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        CREATE TRIGGER case_snapshot_immutable BEFORE UPDATE ON "case"
          FOR EACH ROW EXECUTE FUNCTION case_snapshot_immutable();
        """
    )
    op.create_table(
        "case_alert",
        sa.Column(
            "case_id", sa.Integer(), sa.ForeignKey("case.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "alert_id",
            sa.Integer(),
            sa.ForeignKey("alert.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("open", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "linked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("linked_by", sa.Integer()),
    )
    op.create_index(
        "case_alert_one_open_case",
        "case_alert",
        ["alert_id"],
        unique=True,
        postgresql_where=sa.text("open"),
    )
    op.create_table(
        "case_attachment",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "case_id", sa.Integer(), sa.ForeignKey("case.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Integer()),
    )
    op.create_table(
        "case_activity",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "case_id", sa.Integer(), sa.ForeignKey("case.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("author_id", sa.Integer()),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("data", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "attachment_id",
            sa.Integer(),
            sa.ForeignKey("case_attachment.id", ondelete="SET NULL"),
        ),
    )
    op.create_index("case_activity_case", "case_activity", ["case_id", "id"])


def downgrade() -> None:
    op.drop_table("case_activity")
    op.drop_table("case_attachment")
    op.drop_table("case_alert")
    op.execute('DROP TRIGGER IF EXISTS case_snapshot_immutable ON "case"')
    op.execute("DROP FUNCTION IF EXISTS case_snapshot_immutable()")
    op.drop_table("case")
