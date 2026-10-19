"""Modelling tables (migration 0005). Internal to the modelling module."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Identity, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pmp.core import Base


class Model(Base):
    __tablename__ = "model"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(Integer)


class ModelVersion(Base):
    __tablename__ = "model_version"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("model.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    algorithm: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    training_def: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    limits: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    artefact_path: Mapped[str | None] = mapped_column(Text)
    artefact_sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="Draft")
    error: Mapped[str | None] = mapped_column(Text)
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(Integer)


class ModelSensor(Base):
    __tablename__ = "model_sensor"

    version_id: Mapped[int] = mapped_column(
        ForeignKey("model_version.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    required: Mapped[bool] = mapped_column(Boolean, default=False)


class TrainingPeriod(Base):
    __tablename__ = "training_period"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("model_version.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(12))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ModeFilter(Base):
    __tablename__ = "mode_filter"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("model_version.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    expression: Mapped[str] = mapped_column(Text)
