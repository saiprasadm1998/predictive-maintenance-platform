"""Structured logging (ARC-001 §10.3).

Every record carries the request ID, user, module and model ID when they are known.
Context is held in context variables, so it follows a request or job through every
function it calls without being passed around.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from pmp.core.config import LogFormat

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
model_id_var: ContextVar[str | None] = ContextVar("model_id", default=None)

_CONTEXT_VARS: dict[str, ContextVar[str | None]] = {
    "request_id": request_id_var,
    "user_id": user_id_var,
    "model_id": model_id_var,
}


def _module_of(logger_name: str) -> str | None:
    parts = logger_name.split(".")
    if len(parts) >= 2 and parts[0] == "pmp":
        return parts[1]
    return None


def _context() -> dict[str, str]:
    return {name: value for name, var in _CONTEXT_VARS.items() if (value := var.get()) is not None}


class JsonFormatter(logging.Formatter):
    """One JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if module := _module_of(record.name):
            entry["module"] = module
        entry.update(_context())
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class TextFormatter(logging.Formatter):
    """Readable single-line format for local development."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=UTC).strftime("%H:%M:%S")
        context = " ".join(f"{k}={v}" for k, v in _context().items())
        line = f"{ts} {record.levelname:<7} {record.name}: {record.getMessage()}"
        if context:
            line = f"{line} [{context}]"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


def configure_logging(level: str = "INFO", fmt: LogFormat = LogFormat.JSON) -> None:
    """Send all logs to stdout in the chosen format."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt is LogFormat.JSON else TextFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())


@contextmanager
def log_context(
    *, request_id: str | None = None, user_id: str | None = None, model_id: str | None = None
) -> Iterator[None]:
    """Attach context to every log record written inside the block."""
    values = {"request_id": request_id, "user_id": user_id, "model_id": model_id}
    tokens = [
        (_CONTEXT_VARS[name], _CONTEXT_VARS[name].set(value))
        for name, value in values.items()
        if value is not None
    ]
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
