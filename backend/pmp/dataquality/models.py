"""Data-quality tables (migration 0004): dq_rule, sensor_status, sensor_exclusion.

Internal to the dataquality module. Other modules use pmp.dataquality's public interface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Identity, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pmp.core import Base


class DqRule(Base):
    """One version of the rule overrides for a scope (global, role or tag)."""

    __tablename__ = "dq_rule"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    scope: Mapped[str] = mapped_column(String(10))
    scope_key: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(Integer)


class SensorStatus(Base):
    __tablename__ = "sensor_status"

    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(30))
    rule: Mapped[str] = mapped_column(String(30))
    effect: Mapped[str] = mapped_column(String(20))
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SensorExclusion(Base):
    __tablename__ = "sensor_exclusion"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(10), default="exclude")  # or "override"
    reason: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(Integer)
