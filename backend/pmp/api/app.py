"""FastAPI application (ARC-001 §2.2 web role, §7.3)."""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

import pmp
from pmp.core import log_context

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _request_id(request: Request) -> str:
    supplied = request.headers.get(REQUEST_ID_HEADER, "")
    return supplied if _VALID_REQUEST_ID.match(supplied) else uuid.uuid4().hex


def create_app() -> FastAPI:
    app = FastAPI(
        title="Predictive Maintenance Platform",
        version=pmp.__version__,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
    )

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = _request_id(request)
        with log_context(request_id=request_id):
            response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @app.get("/healthz", tags=["operations"], summary="Liveness check")
    def healthz() -> dict[str, str]:
        """Returns OK while the process is serving requests. Does not touch the database."""
        return {"status": "ok"}

    return app
