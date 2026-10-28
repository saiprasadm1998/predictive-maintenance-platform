"""Failure-mode library tables (migration 0015): failure_mode, failure_mode_version.

Internal to the diagnostics module. Other modules use pmp.diagnostics' public interface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Identity, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pmp.core import Base


class FailureMode(Base):
    __tablename__ = "failure_mode"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    asset_type_id: Mapped[int] = mapped_column(ForeignKey("asset_type.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(64))
    current_version: Mapped[int] = mapped_column(Integer)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FailureModeVersion(Base):
    __tablename__ = "failure_mode_version"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    failure_mode_id: Mapped[int] = mapped_column(ForeignKey("failure_mode.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    iso_code: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text, default="")
    symptoms: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    tasks: Mapped[list[str]] = mapped_column(JSONB)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(Integer)
