"""User administration over the API (UC-17, FR-SEC-01): administrators only; the user
services check it (ARC §9.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from pmp.api.deps import SignedIn, database_of, signed_in
from pmp.api.problems import ProblemError
from pmp.core import (
    Role,
    RoleAssignment,
    UserError,
    UserView,
    create_user,
    list_users,
    reset_password,
    set_active,
    set_roles,
)

router = APIRouter(prefix="/api/v1/users", tags=["administration"])
User = Annotated[SignedIn, Depends(signed_in)]


class RoleIn(BaseModel):
    role: Role
    scope_asset_id: int | None = Field(default=None, description="null: everywhere")


class UserAdminOut(BaseModel):
    id: int
    username: str
    display_name: str
    email: str | None
    active: bool
    roles: list[RoleIn]
    locked_until: datetime | None
    last_login_at: datetime | None


class NewUser(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    display_name: str = ""
    email: str | None = None
    password: str = Field(min_length=1, max_length=1024)
    roles: list[RoleIn] = Field(min_length=1)


class UserPatch(BaseModel):
    roles: list[RoleIn] | None = Field(default=None, min_length=1)
    active: bool | None = None
    password: str | None = Field(default=None, description="reset: unlocks, ends sessions")


def _out(v: UserView) -> UserAdminOut:
    return UserAdminOut(
        id=v.id,
        username=v.username,
        display_name=v.display_name,
        email=v.email,
        active=v.active,
        roles=[RoleIn(role=a.role, scope_asset_id=a.scope_asset_id) for a in v.assignments],
        locked_until=v.locked_until,
        last_login_at=v.last_login_at,
    )


def _assignments(roles: list[RoleIn]) -> list[RoleAssignment]:
    return [RoleAssignment(r.role, r.scope_asset_id) for r in roles]


def _refused(error: UserError) -> ProblemError:
    return ProblemError(400, "user_refused", "User change refused", str(error))


def _by_id(session: Session, user: SignedIn, user_id: int) -> UserView:
    found = [u for u in list_users(session, user.actor) if u.id == user_id]
    if not found:
        raise ProblemError(404, "not_found", "User not found")
    return found[0]


@router.get("", response_model=list[UserAdminOut], summary="Users and their roles")
def get_users(request: Request, user: User) -> list[UserAdminOut]:
    with database_of(request).session() as session:
        return [_out(u) for u in list_users(session, user.actor)]


@router.post("", status_code=201, response_model=UserAdminOut, summary="Create a user")
def post_user(request: Request, user: User, body: NewUser) -> UserAdminOut:
    try:
        with database_of(request).session() as session:
            return _out(
                create_user(
                    session,
                    user.actor,
                    username=body.username,
                    display_name=body.display_name,
                    password=body.password,
                    assignments=_assignments(body.roles),
                    email=body.email,
                )
            )
    except UserError as error:
        raise _refused(error) from None


@router.patch(
    "/{user_id}", response_model=UserAdminOut, summary="Change roles, (de)activate, reset password"
)
def patch_user(request: Request, user: User, user_id: int, body: UserPatch) -> UserAdminOut:
    try:
        with database_of(request).session() as session:
            target = _by_id(session, user, user_id)
            if body.roles is not None:
                set_roles(session, user.actor, target.username, _assignments(body.roles))
            if body.active is not None:
                set_active(session, user.actor, target.username, body.active)
            if body.password is not None:
                reset_password(session, user.actor, target.username, body.password)
            return _out(_by_id(session, user, user_id))
    except UserError as error:
        raise _refused(error) from None
