"""FastAPI application (ARC-001 §2.2 web role, §7.3)."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

import pmp
from pmp.api import (
    admin,
    alerts,
    assets,
    auth,
    backfill,
    diagnostics,
    dq,
    events,
    forecasts,
    ingest,
    models,
    registry,
    users,
)
from pmp.api.deps import database_of
from pmp.api.frontend import mount_frontend
from pmp.api.problems import ProblemError, problem_response
from pmp.api.ratelimit import RateLimiter
from pmp.core import AccessDeniedError, Database, Settings, log_context

DOCS_PATH = "/api/v1/docs"
# The front end is served from this origin only: its scripts, styles (ECharts and React
# set inline styles), canvas images and the API, and it may not be framed.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)
logger = logging.getLogger(__name__)
REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
DEFAULT_INGEST_RATE = 50.0


def _request_id(request: Request) -> str:
    supplied = request.headers.get(REQUEST_ID_HEADER, "")
    return supplied if _VALID_REQUEST_ID.match(supplied) else uuid.uuid4().hex


PROBLEM_SCHEMA = {
    "type": "object",
    "description": "RFC 9457 problem details (ARC §7.3)",
    "required": ["type", "title", "status", "code"],
    "properties": {
        "type": {"type": "string"},
        "title": {"type": "string"},
        "status": {"type": "integer"},
        "code": {"type": "string", "description": "stable error code, e.g. not_found"},
        "detail": {"type": "string"},
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"location": {"type": "string"}, "message": {"type": "string"}},
            },
        },
    },
    "additionalProperties": True,
}
_PROBLEM_REF = {"$ref": "#/components/schemas/Problem"}


def _openapi(app: FastAPI) -> dict[str, Any]:
    """The generated document, corrected to say what the API does: schema errors are 400
    problem details (not FastAPI's 422), and every operation can answer with a problem."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title, version=app.version, routes=app.routes, description=app.description
    )
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    components["Problem"] = PROBLEM_SCHEMA
    for name in ("HTTPValidationError", "ValidationError"):
        components.pop(name, None)
    problem = {"application/problem+json": {"schema": _PROBLEM_REF}}
    for path in schema.get("paths", {}).values():
        for operation in path.values():
            responses = operation.setdefault("responses", {})
            if responses.pop("422", None) is not None:
                responses["400"] = {"description": "Invalid request", "content": problem}
            responses["default"] = {"description": "Error (problem details)", "content": problem}
    app.openapi_schema = schema
    return schema


def create_app(*, settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    """Build the app. Settings and database are created on first use if not given."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        hub = getattr(app.state, "event_hub", None)
        if hub is not None:
            hub.stop()

    app = FastAPI(
        lifespan=lifespan,
        title="Predictive Maintenance Platform",
        version=pmp.__version__,
        openapi_url="/api/v1/openapi.json",
        docs_url=DOCS_PATH,
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

    secure = settings.session_cookie_secure if settings else True

    @app.middleware("http")
    async def security_headers_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """ARC §9.3 / ASVS L1 headers on every response (plan 6.7)."""
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("Referrer-Policy", "same-origin")
        headers.setdefault("X-Frame-Options", "DENY")
        if not request.url.path.startswith(DOCS_PATH):  # Swagger UI loads its own assets
            headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        if secure:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000")
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

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_request: Request, error: StarletteHTTPException) -> Response:
        """404, 405 and the like as problem+json too (ARC §7.3)."""
        codes = {404: "not_found", 405: "method_not_allowed"}
        title = str(error.detail) if error.detail else "HTTP error"
        return problem_response(
            ProblemError(
                error.status_code,
                codes.get(error.status_code, "http_error"),
                title,
                headers=dict(error.headers or {}),
            )
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_request: Request, error: Exception) -> Response:
        logger.exception("Unhandled error", exc_info=error)
        return problem_response(
            ProblemError(500, "internal_error", "Internal error", "See the server log.")
        )

    @app.exception_handler(AccessDeniedError)
    async def handle_denied(_request: Request, error: AccessDeniedError) -> Response:
        return problem_response(ProblemError(403, "forbidden", "Not allowed", str(error)))

    @app.get("/healthz", tags=["operations"], summary="Liveness check")
    def healthz() -> dict[str, str]:
        """Returns OK while the process is serving requests. Does not touch the database."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["operations"], summary="Readiness check (database reachable)")
    def readyz(request: Request) -> dict[str, str]:
        try:
            with database_of(request).session() as session:
                session.execute(text("SELECT 1"))
        except Exception:
            raise ProblemError(503, "not_ready", "Database unreachable") from None
        return {"status": "ready"}

    app.openapi = lambda: _openapi(app)  # type: ignore[method-assign]
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(assets.router)
    app.include_router(models.router)
    app.include_router(models.versions)
    app.include_router(diagnostics.router)
    app.include_router(forecasts.router)
    app.include_router(alerts.router)
    app.include_router(registry.router)
    app.include_router(dq.router)
    app.include_router(users.router)
    app.include_router(events.router)
    app.include_router(ingest.router)
    app.include_router(backfill.router)
    # Last, so the API and operations endpoints always win over the app's catch-all route.
    if settings is not None and settings.frontend_dir is not None:
        if mount_frontend(app, settings.frontend_dir):
            logger.info("Serving the front end from %s", settings.frontend_dir)
        else:
            logger.warning("No front-end build in %s; serving the API only", settings.frontend_dir)
    return app
