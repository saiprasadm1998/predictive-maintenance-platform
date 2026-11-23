"""Retention per kind of data; the reject log; the MQTT transport's state.

- retention_policy gets a period in days for every kind of data (raw samples, roll-ups,
  scores, forecasts, alerts, cases, uploaded files, notification log, audit log) and the
  number of rows and files the last clean-up removed.
- reject_log keeps every sample or message ingestion refused, with the reason (PHI-001
  §5.1: nothing is dropped silently).
- ingest_transport holds the broker connection's state, written by the MQTT subscriber
  and shown on the ingestion-health screen.
- Subscriptions get a delivery mode (immediately, or a daily digest); each user may set
  quiet hours (notification_pref).
- The audit log stays append-only, except that the nightly clean-up may delete rows older
  than seven years.

Revision ID: 0023
Revises: 0022
Created: 2026-11-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("retention_policy", sa.Column("last_removed", sa.BigInteger(), nullable=True))
    op.add_column(
        "retention_policy",
        sa.Column("periods", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_table(
        "reject_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("transport", sa.String(10), nullable=False),
        sa.Column("tag", sa.String(200)),
        sa.Column("sample_ts", sa.DateTime(timezone=True)),
        sa.Column("value", sa.Float()),
        sa.Column("reason", sa.String(30), nullable=False),
        sa.Column("detail", sa.Text()),
    )
    op.create_index("ix_reject_log_received_at", "reject_log", ["received_at"])
    op.create_table(
        "ingest_transport",
        sa.Column("name", sa.String(20), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("connected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.add_column(
        "subscription",
        sa.Column("delivery", sa.String(10), nullable=False, server_default="immediate"),
    )
    op.create_table(
        "notification_pref",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("app_user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("quiet_start", sa.Integer()),
        sa.Column("quiet_end", sa.Integer()),
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION pmp_audit_log_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE'
               AND current_setting('pmp.retention', true) = 'on'
               AND OLD.ts < now() - interval '7 years' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$
        """
    )


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only (ARC-001 §10.4)")
