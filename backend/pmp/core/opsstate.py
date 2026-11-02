"""Operational state the roles record for monitoring (plan 9.1, ARC §10.3).

One row per name, replaced on each write: the worker records what only it can measure
(the scheduler's last scoring duration), the web role reads it for /metrics and the
operational alerts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from pmp.core.db import Base

SCORING_STATE = "scoring"


class OpsStateRow(Base):
    __tablename__ = "ops_state"

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@dataclass(frozen=True)
class OpsState:
    data: Mapping[str, Any]
    updated_at: datetime


def record_state(session: Session, name: str, data: Mapping[str, Any], now: datetime) -> None:
    session.execute(
        insert(OpsStateRow)
        .values(name=name, data=dict(data), updated_at=now)
        .on_conflict_do_update(
            index_elements=[OpsStateRow.name], set_={"data": dict(data), "updated_at": now}
        )
    )


def read_state(session: Session, name: str) -> OpsState | None:
    row = session.get(OpsStateRow, name)
    return None if row is None else OpsState(row.data, row.updated_at)
