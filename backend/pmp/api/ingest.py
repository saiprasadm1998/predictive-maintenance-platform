"""POST /api/v1/ingest/samples: the OT gateway's REST batch interface (ARC-001 §7.1.1).

Order of checks: authentication and scope (nothing is read before the key is valid),
rate limit, body size, gzip, JSON and schema, sample count. Only then is the batch
stored, and it is committed before 202 is returned (NFR-REL-01).
"""

from __future__ import annotations

import gzip
import json
import zlib
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import OperationalError

from pmp.api.deps import authenticate_api_key, database_of, settings_of
from pmp.api.problems import ProblemError
from pmp.api.ratelimit import RateLimiter, retry_after_header
from pmp.core import ApiKeyScope
from pmp.ingestion import MAX_BODY_BYTES, MAX_SAMPLES, BatchIn, ingest_batch, server_now

router = APIRouter(prefix="/api/v1/ingest", tags=["ingestion"])

MAX_DECOMPRESSED_BYTES = 10 * MAX_BODY_BYTES  # guard against compression bombs


class RejectedItem(BaseModel):
    index: int
    reason: str


class IngestResponse(BaseModel):
    accepted: int
    rejected: list[RejectedItem]


def _too_large(detail: str) -> ProblemError:
    return ProblemError(
        413,
        "payload_too_large",
        "Batch too large",
        detail,
        max_samples=MAX_SAMPLES,
        max_bytes=MAX_BODY_BYTES,
    )


async def _read_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _too_large(f"The request body is over {MAX_BODY_BYTES} bytes.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise _too_large(f"The request body is over {MAX_BODY_BYTES} bytes.")
    if request.headers.get("content-encoding", "").lower() == "gzip":
        try:
            decompressor = zlib.decompressobj(wbits=31)
            data = decompressor.decompress(bytes(body), MAX_DECOMPRESSED_BYTES)
            if decompressor.unconsumed_tail:
                raise _too_large("The decompressed body is too large.")
            return data
        except (zlib.error, gzip.BadGzipFile) as error:
            raise ProblemError(400, "invalid_payload", "Invalid gzip body", str(error)) from None
    return bytes(body)


def _parse(body: bytes) -> BatchIn:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ProblemError(400, "invalid_payload", "Body is not valid JSON", str(error)) from None
    samples = payload.get("samples") if isinstance(payload, dict) else None
    if isinstance(samples, list) and len(samples) > MAX_SAMPLES:
        raise _too_large(f"The batch has more than {MAX_SAMPLES} samples.")
    try:
        return BatchIn.model_validate(payload)
    except ValidationError as error:
        errors = [
            {"location": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
            for e in error.errors(include_url=False)
        ]
        raise ProblemError(
            400,
            "invalid_payload",
            "Batch does not match the schema",
            "Nothing was stored. See 'errors'.",
            errors=errors[:50],
        ) from None


@router.post(
    "/samples",
    status_code=202,
    response_model=IngestResponse,
    summary="Accept a batch of samples from the OT gateway",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": BatchIn.model_json_schema()}},
        }
    },
    responses={
        400: {"description": "Schema error; nothing stored"},
        401: {"description": "Missing or invalid API key"},
        403: {"description": "Key lacks the 'ingest' scope"},
        413: {"description": "Over 10,000 samples or 5 MB"},
        429: {"description": "Rate limit; see Retry-After"},
        503: {"description": "Database unavailable; retry later"},
    },
)
async def ingest_samples(request: Request) -> dict[str, Any]:
    try:
        key = await run_in_threadpool(authenticate_api_key, request, ApiKeyScope.INGEST)
    except OperationalError:
        raise _unavailable() from None
    limiter: RateLimiter = request.app.state.ingest_rate_limiter
    wait = limiter.acquire(key.id)
    if wait > 0:
        raise ProblemError(
            429,
            "rate_limited",
            "Too many requests",
            headers={"Retry-After": retry_after_header(wait)},
        )

    batch = _parse(await _read_body(request))
    late_window = timedelta(days=settings_of(request).late_data_days)
    database = database_of(request)

    def store() -> dict[str, Any]:
        with database.session() as session:
            result = ingest_batch(session, batch, now=server_now(session), late_window=late_window)
        return result.as_response()  # committed: the samples are durable

    try:
        return await run_in_threadpool(store)
    except OperationalError:
        raise _unavailable() from None


def _unavailable() -> ProblemError:
    return ProblemError(
        503,
        "unavailable",
        "Database unavailable",
        "Nothing was stored. Retry later.",
        headers={"Retry-After": "10"},
    )
