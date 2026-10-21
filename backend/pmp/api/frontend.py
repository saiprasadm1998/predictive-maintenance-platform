"""Serving the built front end from the web role (ARC §2.2, §11: one image, one origin).

When PMP_FRONTEND_DIR points at the Vite build (frontend/dist), `/static/*` are served as
static files that never change (their names carry a content hash), and every other path
that is not the API or an operations endpoint returns index.html, so a deep link such as
/assets/6?range=24h opens the app, which then routes on the client. Paths under /api that
match nothing still answer 404 problem+json. (Vite's usual `assets/` folder is renamed
`static/` in vite.config.ts, because /assets/:id is the asset analysis screen.)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

from pmp.api.problems import ProblemError

RESERVED = ("api/", "healthz", "readyz", "static/")
NO_CACHE = {"Cache-Control": "no-cache"}
IMMUTABLE = "public, max-age=31536000, immutable"


class _HashedFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = IMMUTABLE
        return response


def mount_frontend(app: FastAPI, directory: Path) -> bool:
    """Serve the app from `directory` if it holds a build; returns whether it does."""
    index = directory / "index.html"
    if not index.is_file():
        return False
    root = directory.resolve()
    if (root / "static").is_dir():
        app.mount("/static", _HashedFiles(directory=root / "static"), name="frontend-static")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        if path.startswith(RESERVED):
            raise ProblemError(404, "not_found", "Not Found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)  # favicon and other files at the top level
        return FileResponse(index, headers=NO_CACHE)

    return True
