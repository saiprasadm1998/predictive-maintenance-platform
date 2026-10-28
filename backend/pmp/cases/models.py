"""Case tables (migration 0017). Internal to the cases module."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
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


class CaseRow(Base):
    __tablename__ = "case"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    priority: Mapped[str] = mapped_column(String(2))
    priority_set: Mapped[bool] = mapped_column(Boolean, default=False)  # edited by a user
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id", ondelete="CASCADE"))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    due: Mapped[date | None] = mapped_column(Date)
    outcome: Mapped[str | None] = mapped_column(String(20))
    confirmed_mode_id: Mapped[int | None] = mapped_column(
        ForeignKey("failure_mode.id", ondelete="SET NULL")
    )
    value_estimate: Mapped[float | None] = mapped_column(Float)
    lessons: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    review_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CaseAlertRow(Base):
    __tablename__ = "case_alert"

    case_id: Mapped[int] = mapped_column(
        ForeignKey("case.id", ondelete="CASCADE"), primary_key=True
    )
    alert_id: Mapped[int] = mapped_column(
        ForeignKey("alert.id", ondelete="CASCADE"), primary_key=True
    )
    open: Mapped[bool] = mapped_column(Boolean, default=True)  # one open case per alert
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    linked_by: Mapped[int | None] = mapped_column(Integer)


class AttachmentRow(Base):
    __tablename__ = "case_attachment"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("case.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(Text)  # relative to the artefact directory
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(Integer)


class ActivityRow(Base):
    __tablename__ = "case_activity"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("case.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    type: Mapped[str] = mapped_column(String(20))
    author_id: Mapped[int | None] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    attachment_id: Mapped[int | None] = mapped_column(
        ForeignKey("case_attachment.id", ondelete="SET NULL")
    )
