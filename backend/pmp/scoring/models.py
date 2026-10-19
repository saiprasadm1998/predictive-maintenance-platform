"""Scoring tables (migration 0007). Internal to the scoring module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from pmp.core import Base


class ScoreRow(Base):
    __tablename__ = "score"

    version_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    model_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    band: Mapped[str] = mapped_column(String(10))
    di: Mapped[float | None] = mapped_column(Float)
    health: Mapped[float | None] = mapped_column(Float)
    coverage: Mapped[float] = mapped_column(Float)
    envelope_flag: Mapped[bool | None] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text)


class SensorOutputRow(Base):
    __tablename__ = "sensor_output"

    version_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tag_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    actual: Mapped[float | None] = mapped_column(Float)
    predicted: Mapped[float | None] = mapped_column(Float)
    residual: Mapped[float | None] = mapped_column(Float)
    q: Mapped[float | None] = mapped_column(Float)
    z: Mapped[float | None] = mapped_column(Float)
    contribution: Mapped[float | None] = mapped_column(Float)
    dq_status: Mapped[str] = mapped_column(String(30))


class RuntimeStatusRow(Base):
    __tablename__ = "runtime_status"

    model_id: Mapped[int] = mapped_column(
        ForeignKey("model.id", ondelete="CASCADE"), primary_key=True
    )
    version_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str | None] = mapped_column(Text)
    last_cycle: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
