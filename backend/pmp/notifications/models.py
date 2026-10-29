"""Notification tables (migration 0018). Internal to the notifications module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
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


class SubscriptionRow(Base):
    __tablename__ = "subscription"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    scope_asset_id: Mapped[int | None] = mapped_column(ForeignKey("asset.id", ondelete="CASCADE"))
    min_priority: Mapped[str] = mapped_column(String(2))
    events: Mapped[list[str]] = mapped_column(JSONB)
    channel: Mapped[str] = mapped_column(String(10), default="email")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationRow(Base):
    __tablename__ = "notification_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    event: Mapped[str] = mapped_column(String(20))
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alert.id", ondelete="SET NULL"))
    case_id: Mapped[int | None] = mapped_column(ForeignKey("case.id", ondelete="SET NULL"))
    recipient: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    summary_id: Mapped[int | None] = mapped_column(BigInteger)  # held, then sent in this summary
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CursorRow(Base):
    __tablename__ = "notifier_cursor"

    name: Mapped[str] = mapped_column(String(30), primary_key=True)
    position: Mapped[int] = mapped_column(BigInteger)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
