"""Alerting tables (migration 0005). Internal to the alerting module."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pmp.core import Base


class AlertRule(Base):
    __tablename__ = "alert_rule"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("model.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(10))
    tag_id: Mapped[int | None] = mapped_column(ForeignKey("tag.id"))
    warning: Mapped[float] = mapped_column(Float)
    alert: Mapped[float] = mapped_column(Float)
    persistence_n: Mapped[int] = mapped_column(Integer, default=3)
    persistence_m: Mapped[int] = mapped_column(Integer, default=5)
    on_delay_s: Mapped[int] = mapped_column(Integer, default=0)
    deadband: Mapped[float] = mapped_column(Float, default=0.1)
    clear_cycles: Mapped[int] = mapped_column(Integer, default=5)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Alert(Base):
    __tablename__ = "alert"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("alert_rule.id", ondelete="SET NULL"))
    model_id: Mapped[int] = mapped_column(ForeignKey("model.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(10))
    tag_id: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(10))
    priority: Mapped[str] = mapped_column(String(2))
    condition_active: Mapped[bool] = mapped_column(Boolean)
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version_id: Mapped[int] = mapped_column(Integer)
    ack_by: Mapped[int | None] = mapped_column(Integer)
    ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shelved_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shelve_reason: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trace: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AlertEvent(Base):
    __tablename__ = "alert_event"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alert.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    action: Mapped[str] = mapped_column(String(30))
    from_state: Mapped[str | None] = mapped_column(String(30))
    to_state: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(10))
    priority: Mapped[str] = mapped_column(String(2))
    user_id: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)


class AlertRuleState(Base):
    __tablename__ = "alert_rule_state"

    rule_id: Mapped[int] = mapped_column(
        ForeignKey("alert_rule.id", ondelete="CASCADE"), primary_key=True
    )
    levels: Mapped[list[int]] = mapped_column(JSONB)
    clear_count: Mapped[int] = mapped_column(Integer)
    condition_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_cycle: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PriorityEntry(Base):
    __tablename__ = "priority_matrix"

    criticality: Mapped[str] = mapped_column(String(1), primary_key=True)
    severity: Mapped[str] = mapped_column(String(10), primary_key=True)
    priority: Mapped[str] = mapped_column(String(2))
