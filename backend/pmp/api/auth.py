"""Sign-in, sessions and the signed-in user (FR-SEC-01, ARC §9.3, plan 5.1).

Browsers sign in with POST /auth/login and get a session cookie (HttpOnly, Secure,
SameSite=Lax) and a CSRF token to send in X-CSRF-Token on every change. API clients use
POST /auth/token and send `Authorization: Bearer <token>`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from pmp.api.deps import (
    SESSION_COOKIE,
    SignedIn,
    client_ip,
    database_of,
    policy_of,
    settings_of,
    signed_in,
)
from pmp.api.problems import ProblemError
from pmp.core import (
    NewSession,
    RoleAssignment,
    SignInError,
    UserError,
    change_own_password,
    get_user,
    sign_in,
    sign_out,
)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


class RoleOut(BaseModel):
    role: str
    scope_asset_id: int | None


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    email: str | None
    roles: list[RoleOut]


class SessionOut(BaseModel):
    user: UserOut
    csrf_token: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    idle_timeout_s: int


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


def _roles(assignments: tuple[RoleAssignment, ...]) -> list[RoleOut]:
    return [RoleOut(role=a.role.value, scope_asset_id=a.scope_asset_id) for a in assignments]


def _start(request: Request, body: Credentials) -> NewSession:
    """Sign in; failed attempts are committed (they count towards the lockout)."""
    with database_of(request).session() as session:
        try:
            return sign_in(
                session,
                body.username,
                body.password,
                datetime.now(UTC),
                ip=client_ip(request),
                policy=policy_of(request),
            )
        except SignInError as error:
            failure = error
    raise ProblemError(401, "invalid_credentials", "Sign-in failed", str(failure))


def _user_out(new: NewSession) -> UserOut:
    user = new.user
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        roles=_roles(user.assignments),
    )


@router.post("/login", response_model=SessionOut, summary="Sign in (browser session cookie)")
def login(request: Request, response: Response, body: Credentials) -> SessionOut:
    new = _start(request, body)
    response.set_cookie(
        SESSION_COOKIE,
        new.token,
        httponly=True,
        secure=settings_of(request).session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return SessionOut(user=_user_out(new), csrf_token=new.csrf_token)


@router.post("/token", response_model=TokenOut, summary="Sign in for API use (bearer token)")
def token(request: Request, body: Credentials) -> TokenOut:
    new = _start(request, body)
    idle = int(policy_of(request).idle_timeout.total_seconds())
    return TokenOut(access_token=new.token, idle_timeout_s=idle)


@router.post("/logout", status_code=204, summary="Sign out (ends this session)")
def logout(
    request: Request, response: Response, user: Annotated[SignedIn, Depends(signed_in)]
) -> Response:
    with database_of(request).session() as session:
        sign_out(session, user.token)
    response.status_code = 204
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me", response_model=SessionOut, summary="The signed-in user and their roles")
def me(request: Request, user: Annotated[SignedIn, Depends(signed_in)]) -> SessionOut:
    with database_of(request).session() as session:
        view = get_user(session, user.session.principal.username)
    out = UserOut(
        id=view.id,
        username=view.username,
        display_name=view.display_name,
        email=view.email,
        roles=_roles(view.assignments),
    )
    return SessionOut(user=out, csrf_token=user.session.csrf_token)


@router.post("/password", status_code=204, summary="Change your own password")
def change_password(
    request: Request, body: PasswordChange, user: Annotated[SignedIn, Depends(signed_in)]
) -> Response:
    try:
        with database_of(request).session() as session:
            change_own_password(
                session,
                user.actor,
                body.current_password,
                body.new_password,
                keep_session_id=user.session.session_id,
            )
    except UserError as error:
        raise ProblemError(400, "invalid_password", "Password not changed", str(error)) from None
    return Response(status_code=204)
