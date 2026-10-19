"""Alerting tables (migration 0005). Internal to the alerting module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Identity, Integer, String, func
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
