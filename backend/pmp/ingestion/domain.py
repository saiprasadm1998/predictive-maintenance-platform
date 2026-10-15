"""Ingestion rules (UC-01, FR-ING-01, -04, -05, ARC §7.1.1). No database imports.

Malformed payloads are rejected whole (HTTP 400, nothing stored; UC-01 2b). Only three
things reject a single sample: an unregistered tag, a timestamp older than the late
window, or one more than 5 minutes in the future.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import IntEnum, StrEnum
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

MAX_SAMPLES = 10_000
MAX_BODY_BYTES = 5 * 1024 * 1024
FUTURE_TOLERANCE = timedelta(minutes=5)
MAX_STATUS_CODE = 0xFFFFFFFF


class Quality(IntEnum):
    """Stored in sample.quality."""

    GOOD = 0
    UNCERTAIN = 1
    BAD = 2


_QUALITY_NAMES = {"Good": Quality.GOOD, "Uncertain": Quality.UNCERTAIN, "Bad": Quality.BAD}


def map_quality(q: int | str | None) -> tuple[Quality, int | None]:
    """Map the payload's quality to (category, raw OPC UA code or None).

    An OPC UA StatusCode is an unsigned 32-bit number whose top two bits (30-31) give the
    severity: 00 Good, 01 Uncertain, 10 Bad (11 is reserved and treated as Bad). The
    strings Good, Uncertain and Bad are also accepted. No quality means Good.
    """
    if q is None:
        return Quality.GOOD, None
    if isinstance(q, str):
        try:
            return _QUALITY_NAMES[q], None
        except KeyError:
            raise ValueError(
                "quality must be an OPC UA StatusCode or Good, Uncertain, Bad"
            ) from None
    if not 0 <= q <= MAX_STATUS_CODE:
        raise ValueError("an OPC UA StatusCode is an unsigned 32-bit number")
    severity = (q >> 30) & 0b11
    category = {0: Quality.GOOD, 1: Quality.UNCERTAIN}.get(severity, Quality.BAD)
    return category, q


class SampleIn(BaseModel):
    """One sample as sent by the gateway (ARC §7.1.1)."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    tag: Annotated[str, Field(min_length=1, max_length=200)]
    ts: AwareDatetime  # timestamps must carry an offset; stored in UTC (NFR-COMP-01)
    v: float
    q: int | str | None = None

    @field_validator("q", mode="before")
    @classmethod
    def _valid_quality(cls, q: object) -> object:
        # Checked before Pydantic's own conversion, which would turn true into 1.
        if q is not None and (isinstance(q, bool) or not isinstance(q, int | str)):
            raise ValueError("quality must be an OPC UA StatusCode or Good, Uncertain, Bad")
        map_quality(q)
        return q

    @field_validator("v", mode="before")
    @classmethod
    def _number_not_bool(cls, v: object) -> object:
        if isinstance(v, bool | str):
            raise ValueError("value must be a number")
        return v


class BatchIn(BaseModel):
    """A batch from one gateway source."""

    model_config = ConfigDict(extra="forbid")

    source: Annotated[str, Field(min_length=1, max_length=100)]
    samples: list[SampleIn]


class RejectReason(StrEnum):
    UNREGISTERED_TAG = "unregistered_tag"
    TOO_OLD = "too_old"
    IN_FUTURE = "in_future"


def check_window(ts: datetime, now: datetime, late_window: timedelta) -> RejectReason | None:
    """Late samples are accepted within the window (default 7 days, FR-ING-04); samples more
    than 5 minutes ahead of the server clock are rejected."""
    if ts > now + FUTURE_TOLERANCE:
        return RejectReason.IN_FUTURE
    if ts < now - late_window:
        return RejectReason.TOO_OLD
    return None


def to_utc(ts: datetime) -> datetime:
    return ts.astimezone(UTC)
