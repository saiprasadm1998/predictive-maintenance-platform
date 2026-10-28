"""Cases (plan 8.4, UC-12, UC-13, FR-CAS-01 to -03, ARC §7: /cases)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from pmp.api.common import can_see, not_found
from pmp.api.deps import SignedIn, database_of, settings_of, signed_in
from pmp.api.problems import ProblemError
from pmp.cases import (
    MAX_ATTACHMENT_BYTES,
    UNSET,
    CaseConflictError,
    CaseDetail,
    CaseError,
    CaseQuery,
    CaseStatus,
    CaseSummary,
    Outcome,
    add_action,
    add_attachment,
    add_comment,
    assignable_people,
    attachment_file,
    change_status,
    close_case,
    complete_action,
    create_case,
    get_case,
    link_alerts,
    list_cases,
    update_case,
)
from pmp.core import active_people, user_names
from pmp.registry import find_asset, list_subtree

router = APIRouter(prefix="/api/v1", tags=["cases"])
User = Annotated[SignedIn, Depends(signed_in)]
INLINE_TYPES = {"image/png", "image/jpeg", "image/gif", "application/pdf", "text/plain"}
StatusName = Literal[
    "Open", "Investigating", "Action required", "Monitoring", "Closed", "Cancelled"
]
OutcomeName = Literal["true_finding", "false_alert", "sensor_issue", "known_condition"]


class CaseOut(BaseModel):
    id: int
    number: str = Field(description="C-nnnn")
    title: str
    status: StatusName
    priority: str
    asset_id: int
    asset_code: str
    asset_path: str
    assignee_id: int | None
    assignee: str | None = Field(description="display name")
    due: date | None
    overdue: bool
    outcome: OutcomeName | None
    review_requested: bool = Field(description="closed as a false alert: model review asked")
    alert_ids: list[int]
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None


class ActivityOut(BaseModel):
    id: int
    ts: datetime
    type: str = Field(
        description="created, comment, attachment, action, state_change, assignment, "
        "update, link or closure"
    )
    author_id: int | None
    author: str | None
    body: str
    data: dict[str, Any]
    attachment_id: int | None


class ActionOut(BaseModel):
    id: int
    description: str
    owner_id: int | None
    owner: str | None
    due: date | None
    status: Literal["open", "done"]
    created_at: datetime
    done_at: datetime | None


class AttachmentOut(BaseModel):
    id: int
    filename: str
    content_type: str
    size: int
    sha256: str
    created_at: datetime
    created_by: int | None


class CaseDetailOut(CaseOut):
    priority_set: bool = Field(description="the priority was edited, so new alerts keep it")
    confirmed_mode_id: int | None
    value_estimate: float | None
    lessons: str | None
    cancel_reason: str | None
    created_by: int | None
    snapshot: dict[str, Any] = Field(description="immutable: what was known at creation")
    activities: list[ActivityOut]
    actions: list[ActionOut]
    attachments: list[AttachmentOut]


class PersonOut(BaseModel):
    id: int
    username: str
    display_name: str
    roles: list[str]


def _today() -> date:
    return datetime.now(UTC).date()


def _summary_fields(c: CaseSummary, names: dict[int, str]) -> dict[str, Any]:
    return {
        "id": c.id,
        "number": c.number,
        "title": c.title,
        "status": c.status.value,
        "priority": c.priority,
        "asset_id": c.asset_id,
        "asset_code": c.asset_code,
        "asset_path": c.asset_path,
        "assignee_id": c.assignee_id,
        "assignee": names.get(c.assignee_id) if c.assignee_id else None,
        "due": c.due,
        "overdue": c.overdue(_today()),
        "outcome": c.outcome.value if c.outcome else None,
        "review_requested": c.review_requested,
        "alert_ids": list(c.alert_ids),
        "created_at": c.created_at,
        "updated_at": c.updated_at,
        "closed_at": c.closed_at,
    }


def _display_names(session: Session, ids: set[int | None]) -> dict[int, str]:
    wanted = {i for i in ids if i is not None}
    people = {p.principal.user_id: p.display_name for p in active_people(session, wanted)}
    usernames = user_names(session, wanted)
    return {i: people.get(i) or usernames.get(i, f"user {i}") for i in wanted}


def detail_out(session: Session, c: CaseDetail) -> CaseDetailOut:
    names = _display_names(
        session,
        {c.assignee_id, c.created_by}
        | {a.author_id for a in c.activities}
        | {a.owner_id for a in c.actions},
    )
    return CaseDetailOut(
        **_summary_fields(c, names),
        priority_set=c.priority_set,
        confirmed_mode_id=c.confirmed_mode_id,
        value_estimate=c.value_estimate,
        lessons=c.lessons,
        cancel_reason=c.cancel_reason,
        created_by=c.created_by,
        snapshot=c.snapshot,
        activities=[
            ActivityOut(
                id=a.id,
                ts=a.ts,
                type=a.type.value,
                author_id=a.author_id,
                author=names.get(a.author_id) if a.author_id else None,
                body=a.body,
                data=a.data,
                attachment_id=a.attachment_id,
            )
            for a in c.activities
        ],
        actions=[
            ActionOut(
                id=a.id,
                description=a.description,
                owner_id=a.owner_id,
                owner=names.get(a.owner_id) if a.owner_id else None,
                due=a.due,
                status=a.status.value,
                created_at=a.created_at,
                done_at=a.done_at,
            )
            for a in c.actions
        ],
        attachments=[
            AttachmentOut(
                id=a.id,
                filename=a.filename,
                content_type=a.content_type,
                size=a.size,
                sha256=a.sha256,
                created_at=a.created_at,
                created_by=a.created_by,
            )
            for a in c.attachments
        ],
    )


def _problem(error: CaseError) -> ProblemError:
    message = str(error)
    if isinstance(error, CaseConflictError):
        return ProblemError(409, "case_conflict", message)
    if "does not exist" in message:
        return not_found("Case, alert, action or attachment")
    return ProblemError(400, "case_refused", message)


def _visible_assets(session: Session, user: SignedIn) -> tuple[int, ...]:
    return tuple(a.id for a in list_subtree(session) if can_see(user, a.path))


def _visible_case(session: Session, user: SignedIn, case_id: int) -> CaseDetail:
    try:
        found = get_case(session, case_id)
    except CaseError:
        raise not_found("Case") from None
    if not can_see(user, found.asset_path):
        raise not_found("Case")
    return found


# ------------------------------------------------------------------ reads


@router.get("/cases", response_model=list[CaseOut], summary="The case list (SCR-09)")
def get_cases(
    request: Request,
    user: User,
    status: Annotated[list[StatusName] | None, Query()] = None,
    open_only: bool = False,
    priority: Annotated[list[str] | None, Query()] = None,
    assignee_id: int | None = None,
    mine: Annotated[bool, Query(description="only cases assigned to me")] = False,
    overdue: bool = False,
    outcome: OutcomeName | None = None,
    asset: Annotated[str | None, Query(description="asset code: cases at or below it")] = None,
    q: Annotated[str | None, Query(description="text in the title", max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[CaseOut]:
    """Open cases first, then priority, due date and newest."""
    with database_of(request).session() as session:
        visible = set(_visible_assets(session, user))
        if asset is not None:
            if find_asset(session, asset) is None:
                raise not_found("Asset")
            visible &= {a.id for a in list_subtree(session, asset)}
        query = CaseQuery(
            statuses=tuple(CaseStatus(s) for s in status or ()),
            open_only=open_only,
            priorities=tuple(priority or ()),
            assignee_id=user.session.principal.user_id if mine else assignee_id,
            overdue_on=_today() if overdue else None,
            outcome=Outcome(outcome) if outcome else None,
            asset_ids=tuple(sorted(visible)),
            text=q,
            limit=limit,
        )
        cases = list_cases(session, query)
        names = _display_names(session, {c.assignee_id for c in cases})
        return [CaseOut(**_summary_fields(c, names)) for c in cases]


@router.get("/cases/{case_id}", response_model=CaseDetailOut, summary="One case (SCR-05)")
def get_one_case(request: Request, user: User, case_id: int) -> CaseDetailOut:
    with database_of(request).session() as session:
        return detail_out(session, _visible_case(session, user, case_id))


@router.get(
    "/cases/{case_id}/people",
    response_model=list[PersonOut],
    summary="Who the case can be assigned to, or an action given to",
)
def get_case_people(request: Request, user: User, case_id: int) -> list[PersonOut]:
    with database_of(request).session() as session:
        found = _visible_case(session, user, case_id)
        return [
            PersonOut(
                id=p.principal.user_id,
                username=p.principal.username,
                display_name=p.display_name,
                roles=sorted(r.value for r in p.principal.roles),
            )
            for p in assignable_people(session, found.asset_path)
        ]


@router.get(
    "/cases/{case_id}/attachments/{attachment_id}",
    response_class=FileResponse,
    summary="Download an attachment",
    responses={200: {"content": {"application/octet-stream": {}}}},
)
def get_attachment(request: Request, user: User, case_id: int, attachment_id: int) -> FileResponse:
    root = settings_of(request).artefact_dir
    with database_of(request).session() as session:
        _visible_case(session, user, case_id)
        try:
            view, path = attachment_file(session, case_id, attachment_id, root)
        except CaseError:
            raise not_found("Attachment") from None
    if not path.is_file():
        raise not_found("Attachment file")
    media = view.content_type if view.content_type in INLINE_TYPES else "application/octet-stream"
    return FileResponse(
        path, media_type=media, filename=view.filename, content_disposition_type="attachment"
    )


# ------------------------------------------------------------------ commands


class CaseIn(BaseModel):
    alert_ids: list[int] = Field(min_length=1, description="alerts of one asset")
    title: str | None = Field(default=None, description="default: the asset and the alert")


class CasePatch(BaseModel):
    title: str | None = None
    priority: Literal["P1", "P2", "P3", "P4"] | None = None
    assignee_id: int | None = Field(default=None, description="null: unassign (Open only)")
    due: date | None = None


class TransitionIn(BaseModel):
    status: Literal["Investigating", "Action required", "Monitoring", "Cancelled"]
    reason: str | None = Field(default=None, description="required to cancel")


class AlertsIn(BaseModel):
    alert_ids: list[int] = Field(min_length=1)


class ActivityIn(BaseModel):
    type: Literal["comment", "action"]
    body: str = Field(description="the comment, or the action's description")
    owner_id: int | None = Field(default=None, description="action: who does it")
    due: date | None = Field(default=None, description="action: by when")


class CloseIn(BaseModel):
    outcome: OutcomeName
    confirmed_mode_id: int | None = Field(
        default=None, description="the failure mode found: required for a true finding"
    )
    value_estimate: float | None = Field(default=None, description="optional")
    lessons: str | None = Field(default=None, description="lessons learned, optional")


def _run(request: Request, command: Any) -> CaseDetailOut:
    try:
        with database_of(request).session() as session:
            return detail_out(session, command(session))
    except CaseError as error:
        raise _problem(error) from None


@router.post("/cases", response_model=CaseDetailOut, status_code=201, summary="Create a case")
def post_case(request: Request, user: User, body: CaseIn) -> CaseDetailOut:
    return _run(request, lambda s: create_case(s, user.actor, body.alert_ids, body.title))


@router.patch(
    "/cases/{case_id}",
    response_model=CaseDetailOut,
    summary="Title, priority, assignee or due date (assigning an Open case starts it)",
)
def patch_case(request: Request, user: User, case_id: int, body: CasePatch) -> CaseDetailOut:
    given = body.model_fields_set
    return _run(
        request,
        lambda s: update_case(
            s,
            user.actor,
            case_id,
            title=body.title if "title" in given else UNSET,
            priority=body.priority if "priority" in given else UNSET,
            assignee_id=body.assignee_id if "assignee_id" in given else UNSET,
            due=body.due if "due" in given else UNSET,
        ),
    )


@router.post(
    "/cases/{case_id}/transition",
    response_model=CaseDetailOut,
    summary="Change state along UCS Figure 7",
)
def post_transition(
    request: Request, user: User, case_id: int, body: TransitionIn
) -> CaseDetailOut:
    return _run(
        request,
        lambda s: change_status(s, user.actor, case_id, CaseStatus(body.status), body.reason),
    )


@router.post(
    "/cases/{case_id}/alerts", response_model=CaseDetailOut, summary="Add alerts to the case"
)
def post_case_alerts(request: Request, user: User, case_id: int, body: AlertsIn) -> CaseDetailOut:
    return _run(request, lambda s: link_alerts(s, user.actor, case_id, body.alert_ids))


@router.post(
    "/cases/{case_id}/activities",
    response_model=CaseDetailOut,
    status_code=201,
    summary="Add a comment or an action",
)
def post_activity(request: Request, user: User, case_id: int, body: ActivityIn) -> CaseDetailOut:
    if body.type == "comment":
        return _run(request, lambda s: add_comment(s, user.actor, case_id, body.body))
    return _run(
        request,
        lambda s: add_action(s, user.actor, case_id, body.body, body.owner_id, body.due),
    )


@router.post(
    "/cases/{case_id}/actions/{action_id}/done",
    response_model=CaseDetailOut,
    summary="Mark an action done",
)
def post_action_done(request: Request, user: User, case_id: int, action_id: int) -> CaseDetailOut:
    return _run(request, lambda s: complete_action(s, user.actor, case_id, action_id))


@router.post(
    "/cases/{case_id}/attachments",
    response_model=CaseDetailOut,
    status_code=201,
    summary="Attach a file (up to 20 MB)",
)
async def post_attachment(
    request: Request,
    user: User,
    case_id: int,
    file: Annotated[UploadFile, File(description="up to 20 MB")],
    comment: Annotated[str, Form()] = "",
) -> CaseDetailOut:
    content = await file.read(MAX_ATTACHMENT_BYTES + 1)
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise ProblemError(413, "too_large", "An attachment may be at most 20 MB")
    root = settings_of(request).artefact_dir
    return await asyncio.to_thread(
        _run,
        request,
        lambda s: add_attachment(
            s,
            user.actor,
            case_id,
            file.filename or "attachment",
            file.content_type or "application/octet-stream",
            content,
            root,
            comment,
        ),
    )


@router.post(
    "/cases/{case_id}/close",
    response_model=CaseDetailOut,
    summary="Close with an outcome (UC-13)",
)
def post_close(request: Request, user: User, case_id: int, body: CloseIn) -> CaseDetailOut:
    return _run(
        request,
        lambda s: close_case(
            s,
            user.actor,
            case_id,
            Outcome(body.outcome),
            body.confirmed_mode_id,
            body.value_estimate,
            body.lessons,
        ),
    )
