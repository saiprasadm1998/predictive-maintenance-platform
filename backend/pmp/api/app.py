"""FastAPI application (ARC-001 §2.2 web role, §7.3)."""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError

import pmp
from pmp.api import ingest
from pmp.api.problems import ProblemError, problem_response
from pmp.api.ratelimit import RateLimiter
from pmp.core import Database, Settings, log_context

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
DEFAULT_INGEST_RATE = 50.0


def _request_id(request: Request) -> str:
    supplied = request.headers.get(REQUEST_ID_HEADER, "")
    return supplied if _VALID_REQUEST_ID.match(supplied) else uuid.uuid4().hex


def create_app(*, settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    """Build the app. Settings and database are created on first use if not given."""
    app = FastAPI(
        title="Predictive Maintenance Platform",
        version=pmp.__version__,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.ingest_rate_limiter = RateLimiter(
        settings.ingest_rate_limit if settings else DEFAULT_INGEST_RATE
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

    @app.exception_handler(ProblemError)
    async def handle_problem(_request: Request, error: ProblemError) -> Response:
        return problem_response(error)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_request: Request, error: RequestValidationError) -> Response:
        # The spec uses 400 for schema errors (ARC §7.1.1), not FastAPI's default 422.
        errors = [
            {"location": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
            for e in error.errors()
        ]
        return problem_response(
            ProblemError(
                400, "invalid_request", "Request does not match the schema", errors=errors[:50]
            )
        )

    @app.get("/healthz", tags=["operations"], summary="Liveness check")
    def healthz() -> dict[str, str]:
        """Returns OK while the process is serving requests. Does not touch the database."""
        return {"status": "ok"}

    app.include_router(ingest.router)
    return app
