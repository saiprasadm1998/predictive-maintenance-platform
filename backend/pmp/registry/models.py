"""Registry tables (ARC-001 §6.2): asset, tag, asset_type, type_role, tag_role_map.

These classes are internal to the registry module. Other modules use the views and
functions exported from pmp.registry, never these tables.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.types import UserDefinedType

from pmp.core import Base


class Ltree(UserDefinedType[str]):
    """PostgreSQL ltree path, e.g. '1.4.17'. Values travel as plain strings."""

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "LTREE"

    def bind_expression(self, bindvalue: Any) -> ColumnElement[str]:
        # Convert explicitly so inserts never depend on the driver's type guessing.
        return func.text2ltree(bindvalue, type_=self)


class AssetType(Base):
    __tablename__ = "asset_type"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")


class TypeRole(Base):
    __tablename__ = "type_role"
    __table_args__ = (UniqueConstraint("asset_type_id", "code"),)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    asset_type_id: Mapped[int] = mapped_column(ForeignKey("asset_type.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(50), default="")


class Asset(Base):
    __tablename__ = "asset"
    __table_args__ = (
        CheckConstraint("level BETWEEN 1 AND 5", name="level_valid"),
        CheckConstraint("criticality IN ('A', 'B', 'C')", name="criticality_valid"),
        Index("ix_asset_path_gist", "path", postgresql_using="gist"),
        Index("ix_asset_parent_id", "parent_id"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("asset.id"))
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    level: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(Ltree, unique=True)
    asset_type_id: Mapped[int | None] = mapped_column(ForeignKey("asset_type.id"))
    criticality: Mapped[str | None] = mapped_column(String(1))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Tag(Base):
    __tablename__ = "tag"
    __table_args__ = (
        UniqueConstraint("source", "source_name"),
        CheckConstraint("range_lo < range_hi", name="range_valid"),
        CheckConstraint("interval_s > 0", name="interval_positive"),
        Index("ix_tag_asset_id", "asset_id"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    source: Mapped[str] = mapped_column(String(100))
    source_name: Mapped[str] = mapped_column(String(200))
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"))
    description: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str] = mapped_column(String(50))
    range_lo: Mapped[float] = mapped_column(Float)
    range_hi: Mapped[float] = mapped_column(Float)
    interval_s: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TagRoleMap(Base):
    """Which tag fills which role of its asset's type (FR-REG-04)."""

    __tablename__ = "tag_role_map"
    __table_args__ = (UniqueConstraint("asset_id", "type_role_id"), UniqueConstraint("tag_id"))

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id", ondelete="CASCADE"))
    type_role_id: Mapped[int] = mapped_column(ForeignKey("type_role.id", ondelete="CASCADE"))
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id", ondelete="CASCADE"))
