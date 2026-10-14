"""Core: TimescaleDB extension, job queue and append-only audit log.

Revision ID: 0001
Revises:
Created: 2026-10-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "job",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column(
            "run_after", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("locked_by", sa.String(200)),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="status_valid"
        ),
    )
    op.create_index("ix_job_status_run_after", "job", ["status", "run_after"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("user_id", sa.BigInteger()),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("entity", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(200), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("before_after", postgresql.JSONB(), nullable=False),
        sa.Column("ip", postgresql.INET()),
        sa.CheckConstraint("actor_type IN ('user', 'api_key', 'system')", name="actor_type_valid"),
    )
    op.create_index("ix_audit_log_entity_entity_id", "audit_log", ["entity", "entity_id"])
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index("ix_audit_log_ts", "audit_log", ["ts"])

    # Append-only: the trigger blocks changes for every role, including the owner.
    # Production role grants (no UPDATE/DELETE) are set up in sub-phase 9.1.
    op.execute(
        """
        CREATE FUNCTION pmp_audit_log_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION pmp_audit_log_append_only()
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_truncate
        BEFORE TRUNCATE ON audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION pmp_audit_log_append_only()
        """
    )


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only (ARC-001 §10.4)")
