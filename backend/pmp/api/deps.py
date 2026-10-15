"""Shared request dependencies: database, settings, API-key authentication."""

from __future__ import annotations

import logging

from fastapi import Request

from pmp.api.problems import ProblemError
from pmp.core import ApiKeyScope, ApiKeyView, Database, Settings, get_settings, verify_api_key

logger = logging.getLogger(__name__)


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
