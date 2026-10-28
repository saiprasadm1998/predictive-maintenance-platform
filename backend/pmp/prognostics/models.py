"""Forecast table (migration 0016). Internal to the prognostics module."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pmp.core import Base


class ForecastRow(Base):
    __tablename__ = "forecast"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("model.id", ondelete="CASCADE"))
    version_id: Mapped[int] = mapped_column(Integer)
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alert.id", ondelete="SET NULL"))
    target: Mapped[str] = mapped_column(String(10))
    tag_id: Mapped[int | None] = mapped_column(Integer)
    threshold_kind: Mapped[str] = mapped_column(String(10))
    threshold: Mapped[float] = mapped_column(Float)
    direction: Mapped[int] = mapped_column(SmallInteger)
    window_days: Mapped[float] = mapped_column(Float)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    method: Mapped[str | None] = mapped_column(String(12))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    r2: Mapped[float | None] = mapped_column(Float)
    points: Mapped[int] = mapped_column(Integer)
    valid: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text)
    median_h: Mapped[float | None] = mapped_column(Float)
    lower_h: Mapped[float | None] = mapped_column(Float)
    upper_h: Mapped[float | None] = mapped_column(Float)
    urgency: Mapped[str] = mapped_column(String(10))
    series: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(Integer)
