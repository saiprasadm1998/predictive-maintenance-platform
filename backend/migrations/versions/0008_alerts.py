"""Alerts: alert, alert_event, alert_rule_state, priority_matrix (ARC §6.2, UCS §6.6).

Revision ID: 0008
Revises: 0007
Created: 2026-10-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None

STATES = (
    "Normal",
    "Active-Unacknowledged",
    "Active-Acknowledged",
    "RTN-Unacknowledged",
    "Shelved",
    "Out of service",
)
# UCS §6.6 default matrix (FR-ALM-04); configurable
DEFAULT_MATRIX = [
    ("A", "Alert", "P1"),
    ("A", "Warning", "P2"),
    ("B", "Alert", "P2"),
    ("B", "Warning", "P3"),
    ("C", "Alert", "P3"),
    ("C", "Warning", "P4"),
]


def upgrade() -> None:
    states = ", ".join(f"'{s}'" for s in STATES)
    op.create_table(
        "alert",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("alert_rule.id", ondelete="SET NULL")),
        sa.Column(
            "model_id", sa.Integer(), sa.ForeignKey("model.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("tag_id", sa.Integer()),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("priority", sa.String(2), nullable=False),
        sa.Column("condition_active", sa.Boolean(), nullable=False),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("ack_by", sa.Integer()),
        sa.Column("ack_at", sa.DateTime(timezone=True)),
        sa.Column("shelved_until", sa.DateTime(timezone=True)),
        sa.Column("shelve_reason", sa.Text()),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("trace", JSONB(), nullable=False),  # NFR-ACC-01
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(f"state IN ({states})", name="state_valid"),
        sa.CheckConstraint("severity IN ('Warning', 'Alert')", name="severity_valid"),
        sa.CheckConstraint("priority IN ('P1', 'P2', 'P3', 'P4')", name="priority_valid"),
    )
    # One alert per rule that is not Normal (UCS §6.6)
    op.create_index(
        "ux_alert_open_per_rule",
        "alert",
        ["rule_id"],
        unique=True,
        postgresql_where=sa.text("state <> 'Normal'"),
    )
    op.create_index("ix_alert_model_id", "alert", ["model_id"])
    op.create_index("ix_alert_state", "alert", ["state"])

    # The alert event log: the source for ISA-18.2 KPIs (ARC §6.2)
    op.create_table(
        "alert_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "alert_id", sa.Integer(), sa.ForeignKey("alert.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("from_state", sa.String(30)),
        sa.Column("to_state", sa.String(30), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("priority", sa.String(2), nullable=False),
        sa.Column("user_id", sa.Integer()),
        sa.Column("comment", sa.Text()),
    )
    op.create_index("ix_alert_event_alert_id", "alert_event", ["alert_id"])

    # Each rule's memory between cycles, so persistence survives restarts
    op.create_table(
        "alert_rule_state",
        sa.Column(
            "rule_id",
            sa.Integer(),
            sa.ForeignKey("alert_rule.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("levels", JSONB(), nullable=False),
        sa.Column("clear_count", sa.Integer(), nullable=False),
        sa.Column("condition_since", sa.DateTime(timezone=True)),
        sa.Column("last_cycle", sa.DateTime(timezone=True), nullable=False),
    )

    matrix = op.create_table(
        "priority_matrix",
        sa.Column("criticality", sa.String(1), primary_key=True),
        sa.Column("severity", sa.String(10), primary_key=True),
        sa.Column("priority", sa.String(2), nullable=False),
        sa.CheckConstraint("criticality IN ('A', 'B', 'C')", name="criticality_valid"),
        sa.CheckConstraint("priority IN ('P1', 'P2', 'P3', 'P4')", name="priority_valid"),
    )
    op.bulk_insert(
        matrix, [{"criticality": c, "severity": s, "priority": p} for c, s, p in DEFAULT_MATRIX]
    )


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only (ARC-001 §10.4)")
