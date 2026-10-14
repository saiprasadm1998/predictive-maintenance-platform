"""Structured logging with request, user, module and model context (ARC-001 §10.3)."""

from __future__ import annotations

import json
import logging

from pmp.core import log_context
from pmp.core.logging import JsonFormatter, TextFormatter


def _record(name: str, message: str = "hello") -> logging.LogRecord:
    return logging.LogRecord(name, logging.INFO, __file__, 1, message, None, None)


def test_json_lines_carry_level_logger_message_and_module() -> None:
    entry = json.loads(JsonFormatter().format(_record("pmp.scoring.engine")))
    assert entry["level"] == "INFO"
    assert entry["logger"] == "pmp.scoring.engine"
    assert entry["message"] == "hello"
    assert entry["module"] == "scoring"
    assert entry["ts"].endswith("+00:00")


def test_context_is_attached_inside_the_block_only() -> None:
    formatter = JsonFormatter()
    with log_context(request_id="req-1", user_id="42", model_id="m-7"):
        inside = json.loads(formatter.format(_record("pmp.alerting")))
    outside = json.loads(formatter.format(_record("pmp.alerting")))

    assert inside["request_id"] == "req-1"
    assert inside["user_id"] == "42"
    assert inside["model_id"] == "m-7"
    assert "request_id" not in outside


def test_nested_context_restores_the_outer_values() -> None:
    formatter = JsonFormatter()
    with log_context(request_id="outer"):
        with log_context(model_id="m-1"):
            nested = json.loads(formatter.format(_record("pmp.scoring")))
        after = json.loads(formatter.format(_record("pmp.scoring")))

    assert nested["request_id"] == "outer"
    assert nested["model_id"] == "m-1"
    assert "model_id" not in after


def test_non_pmp_loggers_have_no_module() -> None:
    entry = json.loads(JsonFormatter().format(_record("uvicorn.error")))
    assert "module" not in entry


def test_text_format_is_one_readable_line() -> None:
    with log_context(request_id="r-9"):
        line = TextFormatter().format(_record("pmp.core", "started"))
    assert "INFO" in line
    assert "pmp.core: started" in line
    assert "request_id=r-9" in line
