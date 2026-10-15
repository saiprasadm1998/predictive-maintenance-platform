"""API keys and ingestion: api_key, sample hypertable, unmapped_tag, ingest_source.

Revision ID: 0003
Revises: 0002
Created: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # core: machine credentials (FR-SEC-02)
    op.create_table(
        "api_key",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("prefix", sa.String(16), nullable=False, unique=True),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.Integer()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("scope IN ('ingest', 'results-read')", name="scope_valid"),
    )

    # ingestion: time series of raw samples (ARC §6.2, §6.3)
    op.create_table(
        "sample",
        # No foreign key to tag: it would add a lookup to every insert at 10,000 samples/s
        # (NFR-PERF-04). Ingestion only writes tag IDs it has just resolved, and tags are
        # never deleted.
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        # 0 Good, 1 Uncertain, 2 Bad (UC-01 step 4)
        sa.Column("quality", sa.SmallInteger(), nullable=False),
        # the source's OPC UA StatusCode when one was sent (FR-ING-05: preserve it)
        sa.Column("quality_code", sa.BigInteger()),
        sa.PrimaryKeyConstraint("tag_id", "ts"),
        sa.CheckConstraint("quality IN (0, 1, 2)", name="quality_valid"),
    )
    op.execute("SELECT create_hypertable('sample', by_range('ts', INTERVAL '1 day'))")

    op.create_table(
        "unmapped_tag",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("source_name", sa.String(200), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("source", "source_name"),
    )

    op.create_table(
        "ingest_source",
        sa.Column("source", sa.String(100), primary_key=True),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sample_ts", sa.DateTime(timezone=True)),
        sa.Column("accepted_total", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("rejected_total", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only (ARC-001 §10.4)")
