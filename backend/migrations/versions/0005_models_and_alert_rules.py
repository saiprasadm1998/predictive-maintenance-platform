"""Models and alert rules: model, model_version, model_sensor, training_period, mode_filter,
alert_rule (ARC §4, §6.2, Figure 8).

Revision ID: 0005
Revises: 0004
Created: 2026-10-19
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None

STATUSES = (
    "Draft",
    "Training",
    "Failed",
    "Validated",
    "Deployed",
    "Paused",
    "Superseded",
    "Retired",
)


def _created() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.Integer()),
    ]


def upgrade() -> None:
    # modelling (ARC §4): a model monitors one asset; its versions hold the definition
    op.create_table(
        "model",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("asset.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        *_created(),
        sa.UniqueConstraint("asset_id", "name"),
    )

    statuses = ", ".join(f"'{s}'" for s in STATUSES)
    op.create_table(
        "model_version",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "model_id", sa.Integer(), sa.ForeignKey("model.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("algorithm", sa.String(64), nullable=False),
        sa.Column("params", JSONB(), nullable=False, server_default="{}"),
        sa.Column("training_def", JSONB()),  # snapshot taken when training starts (3.2)
        sa.Column("metrics", JSONB()),
        sa.Column("limits", JSONB()),  # proposed limits from validation (7.3)
        sa.Column("artefact_path", sa.Text()),
        sa.Column("artefact_sha256", sa.String(64)),
        sa.Column("status", sa.String(20), nullable=False, server_default="Draft"),
        sa.Column("error", sa.Text()),
        sa.Column("status_changed_at", sa.DateTime(timezone=True)),
        *_created(),
        sa.UniqueConstraint("model_id", "version"),
        sa.CheckConstraint("version > 0", name="version_positive"),
        sa.CheckConstraint(f"status IN ({statuses})", name="status_valid"),
    )

    op.create_table(
        "model_sensor",
        sa.Column(
            "version_id",
            sa.Integer(),
            sa.ForeignKey("model_version.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tag.id"), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("version_id", "position"),
    )

    op.create_table(
        "training_period",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "version_id",
            sa.Integer(),
            sa.ForeignKey("model_version.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('training', 'validation')", name="kind_valid"),
        sa.CheckConstraint("starts_at < ends_at", name="period_valid"),
    )
    op.create_index("ix_training_period_version_id", "training_period", ["version_id"])

    op.create_table(
        "mode_filter",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "version_id",
            sa.Integer(),
            sa.ForeignKey("model_version.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("expression", sa.Text(), nullable=False),
        sa.UniqueConstraint("version_id", "position"),
    )

    # alerting (ARC §4): rules belong to the model; active limits live here, editable
    # and audited (implementation plan, decision on alert limits)
    op.create_table(
        "alert_rule",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "model_id", sa.Integer(), sa.ForeignKey("model.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tag.id")),
        sa.Column("warning", sa.Float(), nullable=False),
        sa.Column("alert", sa.Float(), nullable=False),
        sa.Column("persistence_n", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("persistence_m", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("on_delay_s", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deadband", sa.Float(), nullable=False, server_default="0.1"),
        sa.Column("clear_cycles", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "(kind = 'di' AND tag_id IS NULL) OR (kind = 'sensor' AND tag_id IS NOT NULL)",
            name="kind_valid",
        ),
        sa.CheckConstraint("0 < warning AND warning < alert", name="limits_valid"),
        sa.CheckConstraint(
            "1 <= persistence_n AND persistence_n <= persistence_m", name="persistence_valid"
        ),
        sa.CheckConstraint("on_delay_s >= 0", name="on_delay_valid"),
        sa.CheckConstraint("0 <= deadband AND deadband < 1", name="deadband_valid"),
        sa.CheckConstraint("clear_cycles >= 1", name="clear_cycles_valid"),
    )
    op.create_index(
        "ux_alert_rule_di",
        "alert_rule",
        ["model_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'di'"),
    )
    op.create_index(
        "ux_alert_rule_sensor",
        "alert_rule",
        ["model_id", "tag_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'sensor'"),
    )


def downgrade() -> None:
    raise NotImplementedError("Migrations are forward-only (ARC-001 §10.4)")
