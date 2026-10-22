"""History import over HTTP (UC-02, FR-ING-03, ARC-001 §7.1.3) and job status.

POST /api/v1/ingest/backfill             upload a file; queue a preview or an import job
POST /api/v1/ingest/backfill/{id}/load   import a file that was uploaded for preview
GET  /api/v1/jobs/{id}                   job status, progress and result

Authentication: an `ingest` API key (a gateway or script), or a signed-in user allowed to
change the registry and its imports (ARC §9.2: Model Engineer or Administrator, plan 6.6).
A key reads only the jobs it started; signed-in users read every job.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from pmp.api.deps import (
    SignedIn,
    authenticate_api_key,
    database_of,
    resolve_user,
    settings_of,
)
from pmp.api.problems import ProblemError
from pmp.core import (
    Actor,
    ApiKeyScope,
    JobStatus,
    Permission,
    audit_change,
    authorize,
    enqueue,
    get_job,
)
from pmp.ingestion import (
    BACKFILL_JOB,
    BackfillError,
    BackfillOptions,
    Layout,
    OverlapMode,
    check_file,
)
from pmp.modelling import TRAIN_JOB, ModelError, asset_path, model_of_version

router = APIRouter(tags=["ingestion"])
_UPLOAD_ID = re.compile(r"^[0-9a-f]{32}$")
SUFFIXES = {".csv", ".parquet"}
MAX_ATTEMPTS = 3


class QueuedJob(BaseModel):
    job_id: int
    upload_id: str
    preview: bool


class LoadRequest(BaseModel):
    source: Annotated[str, Field(min_length=1, max_length=100)]
    layout: Layout | None = None
    mode: OverlapMode = OverlapMode.SKIP
    naive_as_utc: bool = False
    ts_column: str = "ts"
    tag_column: str = "tag"
    value_column: str = "value"
    quality_column: str = "quality"


class JobView(BaseModel):
    id: int
    type: str
    status: JobStatus
    progress: float | None
    attempts: int
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None


def _upload_dir(request: Request) -> Path:
    directory = Path(settings_of(request).artefact_dir) / "uploads"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _find_upload(request: Request, upload_id: str) -> Path:
    if _UPLOAD_ID.match(upload_id):
        for suffix in SUFFIXES:
            path = _upload_dir(request) / f"{upload_id}{suffix}"
            if path.exists():
                return path
    raise ProblemError(
        404,
        "not_found",
        "Upload not found",
        "Upload the file again; imported files are removed after loading.",
    )


def _check_columns(path: Path, options: BackfillOptions) -> None:
    try:
        check_file(path, options)
    except BackfillError as error:
        raise ProblemError(400, "invalid_file", "File cannot be imported", str(error)) from None


class _Uploader:
    """Who uploads: an ingest key, or a signed-in user (audited)."""

    def __init__(self, key_id: int | None = None, actor: Actor | None = None) -> None:
        self.key_id = key_id
        self.actor = actor


def _uploader(request: Request) -> _Uploader:
    if request.headers.get("authorization", "").lower().startswith("apikey "):
        return _Uploader(key_id=authenticate_api_key(request, ApiKeyScope.INGEST).id)
    user = resolve_user(request)
    authorize(user.actor, Permission.REGISTRY, what="history imports")
    return _Uploader(actor=user.actor)


def _queue(
    request: Request, who: _Uploader, upload_id: str, options: BackfillOptions, preview: bool
) -> QueuedJob:
    payload = {
        "key_id": who.key_id,  # only this key may read the job (ARC §1.2: keys write only)
        "upload": _find_upload(request, upload_id).name,
        "options": options.to_payload(),
        "preview": preview,
    }
    with database_of(request).session() as session:
        job_id = enqueue(session, BACKFILL_JOB, payload, max_attempts=MAX_ATTEMPTS)
        if who.actor is not None and not preview:
            audit_change(
                session,
                who.actor,
                entity="history_import",
                entity_id=job_id,
                action="queue",
                before=None,
                after={"upload": upload_id, "options": options.to_payload()},
            )
    return QueuedJob(job_id=job_id, upload_id=upload_id, preview=preview)


@router.post(
    "/api/v1/ingest/backfill",
    status_code=202,
    response_model=QueuedJob,
    summary="Upload a history file (CSV or Parquet) to preview or import",
)
def upload_history(
    request: Request,
    file: Annotated[UploadFile, File(description="CSV or Parquet, long or wide format")],
    source: Annotated[str, Form(min_length=1, max_length=100)],
    preview: Annotated[bool, Form()] = False,
    layout: Annotated[Layout | None, Form()] = None,
    mode: Annotated[OverlapMode, Form()] = OverlapMode.SKIP,
    naive_as_utc: Annotated[bool, Form()] = False,
    ts_column: Annotated[str, Form()] = "ts",
    tag_column: Annotated[str, Form()] = "tag",
    value_column: Annotated[str, Form()] = "value",
    quality_column: Annotated[str, Form()] = "quality",
) -> QueuedJob:
    who = _uploader(request)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUFFIXES:
        raise ProblemError(
            415, "unsupported_file", "Unsupported file type", "Upload a .csv or .parquet file."
        )
    limit = settings_of(request).backfill_max_mb * 1024 * 1024
    upload_id = uuid.uuid4().hex
    path = _upload_dir(request) / f"{upload_id}{suffix}"
    size = 0
    with path.open("wb") as target:
        while chunk := file.file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                target.close()
                path.unlink(missing_ok=True)
                raise ProblemError(
                    413,
                    "payload_too_large",
                    "File too large",
                    f"History files are limited to {settings_of(request).backfill_max_mb} MB.",
                )
            target.write(chunk)
    options = BackfillOptions(
        source.strip(),
        layout,
        mode,
        naive_as_utc,
        ts_column,
        tag_column,
        value_column,
        quality_column,
    )
    try:
        _check_columns(path, options)
    except ProblemError:
        path.unlink(missing_ok=True)
        raise
    return _queue(request, who, upload_id, options, preview)


@router.post(
    "/api/v1/ingest/backfill/{upload_id}/load",
    status_code=202,
    response_model=QueuedJob,
    summary="Import a file that was uploaded for preview",
)
def load_history(request: Request, upload_id: str, body: LoadRequest) -> QueuedJob:
    who = _uploader(request)
    path = _find_upload(request, upload_id)
    options = BackfillOptions(**body.model_dump())
    _check_columns(path, options)
    return _queue(request, who, upload_id, options, preview=False)


def _user_sees_job(
    session: Session, user: SignedIn, job_type: str, payload: Mapping[str, Any]
) -> bool:
    """ARC §9.2 scope: a training job is seen by users who may see its model's asset; a
    history import by users who may import (it can hold any tag); others by all."""
    principal = user.session.principal
    if job_type == BACKFILL_JOB:
        return principal.grant(Permission.REGISTRY, None)
    if job_type == TRAIN_JOB and "version_id" in payload:
        try:
            model = model_of_version(session, int(payload["version_id"]))
        except ModelError:
            return principal.grant(Permission.VIEW, None)
        return principal.grant(Permission.VIEW, asset_path(session, model.asset_code))
    return True


@router.get(
    "/api/v1/jobs/{job_id}",
    response_model=JobView,
    tags=["jobs"],
    summary="Status, progress and result of a background job",
)
def job_status(request: Request, job_id: int) -> JobView:
    """With an ingest key: only the history imports that key started (ARC §1.2). Signed-in
    users see every job (training, imports)."""
    by_key = request.headers.get("authorization", "").lower().startswith("apikey ")
    key = authenticate_api_key(request, ApiKeyScope.INGEST) if by_key else None
    user = None if key is not None else resolve_user(request)
    with database_of(request).session() as session:
        job = get_job(session, job_id)
        visible = job is not None and (
            job.payload.get("key_id") == key.id and job.type == BACKFILL_JOB
            if key is not None
            else _user_sees_job(session, user, job.type, job.payload)  # type: ignore[arg-type]
        )
    if job is None or not visible:
        raise ProblemError(404, "not_found", "Job not found")
    return JobView(
        id=job.id,
        type=job.type,
        status=job.status,
        progress=job.progress,
        attempts=job.attempts,
        result=dict(job.result) if job.result else None,
        error=job.last_error,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )
