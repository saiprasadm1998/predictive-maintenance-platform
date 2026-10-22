"""Shared request dependencies: database, settings, user sessions, API-key authentication."""

from __future__ import annotations

import ipaddress
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from pmp.api.problems import ProblemError
from pmp.core import (
    ActiveSession,
    Actor,
    ApiKeyScope,
    ApiKeyView,
    Database,
    Settings,
    SignInPolicy,
    csrf_matches,
    get_settings,
    resolve_session,
    user_id_var,
    verify_api_key,
)

logger = logging.getLogger(__name__)
security_log = logging.getLogger("pmp.security")

SESSION_COOKIE = "pmp_session"
CSRF_HEADER = "X-CSRF-Token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
KEY_USE_LOG_EVERY_S = 300.0  # successful key use is logged at most every 5 min per key
_key_use_logged: dict[int, float] = {}


def settings_of(request: Request) -> Settings:
    settings: Settings | None = getattr(request.app.state, "settings", None)
    if settings is None:
        settings = get_settings()
        request.app.state.settings = settings
    return settings


def database_of(request: Request) -> Database:
    database: Database | None = getattr(request.app.state, "database", None)
    if database is None:
        database = Database(settings_of(request).database_url.get_secret_value())
        request.app.state.database = database
    return database


def authenticate_api_key(request: Request, scope: ApiKeyScope) -> ApiKeyView:
    """Check `Authorization: ApiKey <key>` and its scope. Runs in a worker thread.

    401 for a missing or invalid key (attempt logged, UC-01 2a); 403 for a valid key
    with the wrong scope (UC-18 1a).
    """
    client = request.client.host if request.client else "unknown"
    header = request.headers.get("authorization", "")
    scheme, _, key = header.partition(" ")
    if scheme.lower() != "apikey" or not key.strip():
        logger.warning("API key missing or malformed from %s for %s", client, request.url.path)
        raise ProblemError(
            401,
            "unauthorized",
            "Missing API key",
            "Send the header 'Authorization: ApiKey <key>'.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    with database_of(request).session() as session:
        view = verify_api_key(session, key.strip())
    if view is None:
        logger.warning("Invalid or revoked API key from %s for %s", client, request.url.path)
        raise ProblemError(
            401,
            "unauthorized",
            "Invalid API key",
            "The key is unknown or has been revoked.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    user_id_var.set(f"key:{view.prefix}")  # ARC §10.3: who, on this request's log lines
    _log_key_use(view, client)
    if view.scope is not scope:
        logger.warning(
            "API key %s (scope %s) refused for %s", view.prefix, view.scope, request.url.path
        )
        raise ProblemError(
            403,
            "forbidden",
            "Key not allowed here",
            f"This endpoint needs a key with scope '{scope.value}'.",
        )
    return view


def _log_key_use(view: ApiKeyView, client: str) -> None:
    """Key use is a security event (ARC §9.3 FR 6); the gateway calls many times a
    minute, so each key is logged at most every 5 minutes."""
    now = time.monotonic()
    if now - _key_use_logged.get(view.id, -KEY_USE_LOG_EVERY_S) < KEY_USE_LOG_EVERY_S:
        return
    _key_use_logged[view.id] = now
    security_log.info(
        "API key used: %s (%s) from %s",
        view.prefix,
        view.scope.value,
        client,
        extra={"event": "api_key_used", "key_prefix": view.prefix, "ip": client},
    )


def policy_of(request: Request) -> SignInPolicy:
    settings = settings_of(request)
    return SignInPolicy(
        max_failures=settings.login_max_failures,
        lockout=timedelta(minutes=settings.login_lockout_minutes),
        idle_timeout=timedelta(minutes=settings.session_idle_minutes),
        max_age=timedelta(hours=settings.session_max_hours),
    )


def client_ip(request: Request) -> str | None:
    """The client's IP address, if it is one (stored as INET in sessions and the audit)."""
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None


@dataclass(frozen=True)
class SignedIn:
    """The signed-in user of a request: `actor` goes to every service call."""

    actor: Actor
    session: ActiveSession
    token: str
    via_cookie: bool


def _unauthorized(detail: str) -> ProblemError:
    return ProblemError(
        401, "unauthorized", "Sign in first", detail, headers={"WWW-Authenticate": "Bearer"}
    )


_bearer_scheme = HTTPBearer(
    auto_error=False,
    description="A token from POST /api/v1/auth/token (browsers use the session cookie).",
)


def signed_in(
    request: Request,
    _credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer_scheme)] = None,
) -> SignedIn:
    """Dependency for endpoints that need a signed-in user (the Swagger "Authorize" button
    sends the bearer token)."""
    return resolve_user(request)


def resolve_user(request: Request) -> SignedIn:
    """The user behind `Authorization: Bearer <token>` or the session cookie.

    Requests that change something with the cookie must echo the session's CSRF token in
    the X-CSRF-Token header (ARC §9.1 C2); bearer tokens are not sent automatically by
    browsers, so they need none.
    """
    scheme, _, bearer = request.headers.get("authorization", "").partition(" ")
    via_cookie = scheme.lower() != "bearer" or not bearer.strip()
    token = request.cookies.get(SESSION_COOKIE, "") if via_cookie else bearer.strip()
    if not token:
        raise _unauthorized("Sign in with POST /api/v1/auth/login or send a bearer token.")
    with database_of(request).session() as session:
        active = resolve_session(session, token, datetime.now(UTC), policy=policy_of(request))
    if active is None:
        raise _unauthorized("The session has ended (signed out, idle for too long or expired).")
    user_id_var.set(str(active.principal.user_id))  # ARC §10.3: on this request's log lines
    if (
        via_cookie
        and request.method not in _SAFE_METHODS
        and not csrf_matches(active.csrf_token, request.headers.get(CSRF_HEADER))
    ):
        security_log.warning(
            "CSRF token missing or wrong: %s %s",
            request.method,
            request.url.path,
            extra={"event": "csrf_refused", "username": active.principal.username},
        )
        raise ProblemError(
            403, "csrf_failed", "Missing or wrong CSRF token", f"Send the {CSRF_HEADER} header."
        )
    return SignedIn(Actor.user(active.principal, client_ip(request)), active, token, via_cookie)
