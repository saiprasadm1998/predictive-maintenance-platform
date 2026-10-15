"""RFC 9457 problem details (ARC-001 §7.3): every error body has a stable code."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

PROBLEM_TYPE_BASE = "https://pmp.local/problems/"


class ProblemError(Exception):
    """Raise anywhere in a request to return a problem+json response."""

    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str = "",
        *,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(detail or title)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.headers = headers or {}
        self.extra = extra


def problem_response(error: ProblemError) -> JSONResponse:
    body: dict[str, Any] = {
        "type": PROBLEM_TYPE_BASE + error.code,
        "title": error.title,
        "status": error.status,
        "code": error.code,
    }
    if error.detail:
        body["detail"] = error.detail
    body.update(error.extra)
    return JSONResponse(
        body,
        status_code=error.status,
        headers=error.headers,
        media_type="application/problem+json",
    )
