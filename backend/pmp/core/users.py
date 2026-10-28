"""Users, sign-in and sessions (FR-SEC-01, UC-17, ARC §9.3).

- Passwords are hashed with Argon2id (argon2-cffi defaults). Rules: at least 12
  characters and not containing the username (decision 5.1).
- Sign-in fails with the same message whether the username is unknown, the password is
  wrong or the account is locked or inactive, so usernames cannot be discovered. After 5
  failures in a row the account is locked for 15 minutes.
- A session is a random token; only its SHA-256 hash is stored. It ends after 30 minutes
  without use (idle timeout) or 12 hours in all (decision 5.1), on sign-out, and for all
  of a user's sessions when the user is deactivated or their password is reset.
- Roles are read on every request (`resolve_session`), so access changes take effect at
  once (UC-17). Users are deactivated, never deleted, so the audit trail always names a
  real account.

Every administrative change is audited; sign-in events go to the security log.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    delete,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, Session, mapped_column

from pmp.core.access import Permission, Principal, Role, RoleAssignment, authorize
from pmp.core.audit import Actor, audit_change
from pmp.core.db import Base

security_log = logging.getLogger("pmp.security")
_hasher = PasswordHasher()  # Argon2id
_DUMMY_HASH = _hasher.hash("pmp-timing-equaliser")
_USERNAME = re.compile(r"^[A-Za-z0-9._@-]{3,100}$")
MIN_PASSWORD = 12
TOUCH_EVERY = timedelta(seconds=60)  # how often a session's last-seen time is written


class UserError(ValueError):
    """A user administration request was refused."""


class SignInError(Exception):
    """Sign-in failed. The message is deliberately the same for every cause."""

    def __init__(self) -> None:
        super().__init__("Invalid username or password")


# ------------------------------------------------------------------ tables


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserRole(Base):
    __tablename__ = "user_role"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(30))
    scope_asset_id: Mapped[int | None] = mapped_column(Integer)


class UserSession(Base):
    __tablename__ = "user_session"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(INET)


# ------------------------------------------------------------------ views and policy


@dataclass(frozen=True)
class SignInPolicy:
    """ARC §9.3: lockout after 5 failures for 15 minutes; 30-minute idle timeout."""

    max_failures: int = 5
    lockout: timedelta = timedelta(minutes=15)
    idle_timeout: timedelta = timedelta(minutes=30)
    max_age: timedelta = timedelta(hours=12)


@dataclass(frozen=True)
class UserView:
    id: int
    username: str
    display_name: str
    email: str | None
    active: bool
    assignments: tuple[RoleAssignment, ...]
    locked_until: datetime | None
    last_login_at: datetime | None


@dataclass(frozen=True)
class NewSession:
    token: str  # give it to the client once; only its hash is stored
    csrf_token: str
    user: UserView


@dataclass(frozen=True)
class ActiveSession:
    principal: Principal
    csrf_token: str
    session_id: int


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _assignments(session: Session, user_id: int) -> tuple[RoleAssignment, ...]:
    rows = session.scalars(
        select(UserRole).where(UserRole.user_id == user_id).order_by(UserRole.id)
    ).all()
    return tuple(RoleAssignment(Role(r.role), r.scope_asset_id) for r in rows)


def _view(session: Session, user: AppUser) -> UserView:
    return UserView(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        active=user.active,
        assignments=_assignments(session, user.id),
        locked_until=user.locked_until,
        last_login_at=user.last_login_at,
    )


def _find(session: Session, username: str) -> AppUser | None:
    return session.scalars(
        select(AppUser).where(func.lower(AppUser.username) == username.strip().lower())
    ).one_or_none()


def _require(session: Session, username: str) -> AppUser:
    user = _find(session, username)
    if user is None:
        raise UserError(f"No user {username!r}")
    return user


def _snapshot(session: Session, user: AppUser) -> dict[str, object]:
    return {
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "active": user.active,
        "roles": [
            f"{a.role.value}@{a.scope_asset_id}" if a.scope_asset_id else a.role.value
            for a in _assignments(session, user.id)
        ],
    }


# ------------------------------------------------------------------ passwords


def check_password(username: str, password: str) -> None:
    """Password rules (decision 5.1): at least 12 characters, not containing the
    username. Length matters more than character classes (NIST SP 800-63B)."""
    if len(password) < MIN_PASSWORD:
        raise UserError(f"Passwords need at least {MIN_PASSWORD} characters")
    if username.strip().lower() in password.lower():
        raise UserError("A password may not contain the username")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def _verify(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# ------------------------------------------------------------------ administration (UC-17)


def _check_assignments(assignments: Sequence[RoleAssignment]) -> None:
    if not assignments:
        raise UserError("A user needs at least one role")
    if len(set(assignments)) != len(assignments):
        raise UserError("The same role and scope are given twice")


def _set_assignments(session: Session, user_id: int, assignments: Sequence[RoleAssignment]) -> None:
    session.execute(delete(UserRole).where(UserRole.user_id == user_id))
    for a in assignments:
        session.add(UserRole(user_id=user_id, role=a.role.value, scope_asset_id=a.scope_asset_id))
    session.flush()


def create_user(
    session: Session,
    actor: Actor,
    *,
    username: str,
    display_name: str,
    password: str,
    assignments: Sequence[RoleAssignment],
    email: str | None = None,
) -> UserView:
    authorize(actor, Permission.ADMINISTRATION, what="create users")
    username = username.strip()
    if not _USERNAME.fullmatch(username):
        raise UserError("Usernames are 3 to 100 letters, digits, '.', '_', '@' or '-'")
    if _find(session, username) is not None:
        raise UserError(f"User {username!r} already exists")
    check_password(username, password)
    _check_assignments(assignments)
    user = AppUser(
        username=username,
        display_name=display_name.strip() or username,
        email=email,
        password_hash=hash_password(password),
        active=True,
        failed_attempts=0,
    )
    session.add(user)
    session.flush()
    _set_assignments(session, user.id, assignments)
    audit_change(
        session,
        actor,
        entity="user",
        entity_id=user.id,
        action="create",
        after=_snapshot(session, user),
    )
    return _view(session, user)


def set_roles(
    session: Session, actor: Actor, username: str, assignments: Sequence[RoleAssignment]
) -> UserView:
    authorize(actor, Permission.ADMINISTRATION, what="change roles")
    user = _require(session, username)
    _check_assignments(assignments)
    before = _snapshot(session, user)
    _set_assignments(session, user.id, assignments)
    audit_change(
        session,
        actor,
        entity="user",
        entity_id=user.id,
        action="set_roles",
        before=before,
        after=_snapshot(session, user),
    )
    return _view(session, user)


def set_active(session: Session, actor: Actor, username: str, active: bool) -> UserView:
    """Deactivate (leaver) or reactivate a user. Deactivation ends their sessions."""
    authorize(actor, Permission.ADMINISTRATION, what="activate or deactivate users")
    user = _require(session, username)
    if actor.user_id == user.id and not active:
        raise UserError("You cannot deactivate your own account")
    before = _snapshot(session, user)
    user.active = active
    if not active:
        session.execute(delete(UserSession).where(UserSession.user_id == user.id))
    audit_change(
        session,
        actor,
        entity="user",
        entity_id=user.id,
        action="activate" if active else "deactivate",
        before=before,
        after=_snapshot(session, user),
    )
    return _view(session, user)


def reset_password(session: Session, actor: Actor, username: str, password: str) -> UserView:
    """Set a new password (administrator). Unlocks the account and ends its sessions."""
    authorize(actor, Permission.ADMINISTRATION, what="reset passwords")
    user = _require(session, username)
    check_password(user.username, password)
    user.password_hash = hash_password(password)
    user.password_changed_at = func.now()
    user.failed_attempts, user.locked_until = 0, None
    session.execute(delete(UserSession).where(UserSession.user_id == user.id))
    audit_change(session, actor, entity="user", entity_id=user.id, action="reset_password")
    return _view(session, user)


def change_own_password(
    session: Session, actor: Actor, current: str, new: str, keep_session_id: int | None = None
) -> None:
    """A signed-in user changes their own password; their other sessions end."""
    if actor.user_id is None:
        raise UserError("Only a signed-in user can change their own password")
    user = session.get_one(AppUser, actor.user_id)
    if not _verify(user.password_hash, current):
        raise UserError("The current password is wrong")
    check_password(user.username, new)
    user.password_hash = hash_password(new)
    user.password_changed_at = func.now()
    query = delete(UserSession).where(UserSession.user_id == user.id)
    if keep_session_id is not None:
        query = query.where(UserSession.id != keep_session_id)
    session.execute(query)
    audit_change(session, actor, entity="user", entity_id=user.id, action="change_password")


def list_users(session: Session, actor: Actor) -> list[UserView]:
    authorize(actor, Permission.ADMINISTRATION, what="users")
    users = session.scalars(select(AppUser).order_by(func.lower(AppUser.username))).all()
    return [_view(session, u) for u in users]


def get_user(session: Session, username: str) -> UserView:
    return _view(session, _require(session, username))


def count_users(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(AppUser)) or 0


# ------------------------------------------------------------------ sign-in and sessions


def sign_in(
    session: Session,
    username: str,
    password: str,
    now: datetime,
    *,
    ip: str | None = None,
    policy: SignInPolicy = SignInPolicy(),  # noqa: B008  (frozen, never mutated)
) -> NewSession:
    """Check the credentials and start a session, or raise SignInError.

    Runs in the caller's transaction, which must be committed even when SignInError is
    raised, so failed attempts are counted.
    """
    user = _find(session, username)
    if user is None:
        _verify(_DUMMY_HASH, password)  # same time as a real check: no username probing
        _log("sign_in_failed", username, ip, "unknown user")
        raise SignInError()
    if user.locked_until is not None and user.locked_until > now:
        _log("sign_in_refused", user.username, ip, "account locked")
        raise SignInError()
    if not _verify(user.password_hash, password):
        user.failed_attempts += 1
        if user.failed_attempts >= policy.max_failures:
            user.locked_until = now + policy.lockout
            user.failed_attempts = 0
            _log("account_locked", user.username, ip, f"until {user.locked_until:%H:%M} UTC")
        else:
            _log("sign_in_failed", user.username, ip, "wrong password")
        raise SignInError()
    if not user.active:
        _log("sign_in_refused", user.username, ip, "inactive account")
        raise SignInError()
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.failed_attempts, user.locked_until, user.last_login_at = 0, None, now
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    session.add(
        UserSession(
            token_hash=_hash_token(token),
            user_id=user.id,
            csrf_token=csrf,
            created_at=now,
            last_seen_at=now,
            ip=ip,
        )
    )
    session.flush()
    _log("sign_in", user.username, ip)
    return NewSession(token, csrf, _view(session, user))


def resolve_session(
    session: Session,
    token: str,
    now: datetime,
    *,
    policy: SignInPolicy = SignInPolicy(),  # noqa: B008
    touch: bool = True,
) -> ActiveSession | None:
    """The session for a token, with the user's current roles, or None if it does not
    exist, has expired (idle or too old) or its user is inactive. Using a session keeps it
    alive, unless `touch` is False (an open live stream is not user activity)."""
    row = session.scalars(
        select(UserSession).where(UserSession.token_hash == _hash_token(token))
    ).one_or_none()
    if row is None:
        return None
    user = session.get(AppUser, row.user_id)
    expired = now - row.last_seen_at > policy.idle_timeout or now - row.created_at > policy.max_age
    if user is None or not user.active or expired:
        session.delete(row)
        if user is not None and expired:
            _log("session_expired", user.username, None)
        return None
    if touch and now - row.last_seen_at >= TOUCH_EVERY:
        row.last_seen_at = now
    principal = Principal(user.id, user.username, _assignments(session, user.id))
    return ActiveSession(principal, row.csrf_token, row.id)


def sign_out(session: Session, token: str) -> None:
    row = session.scalars(
        select(UserSession).where(UserSession.token_hash == _hash_token(token))
    ).one_or_none()
    if row is not None:
        user = session.get(AppUser, row.user_id)
        session.delete(row)
        _log("sign_out", user.username if user else str(row.user_id), None)


def csrf_matches(expected: str, supplied: str | None) -> bool:
    return supplied is not None and hmac.compare_digest(expected, supplied)


def _log(event: str, username: str, ip: str | None, detail: str = "") -> None:
    level = logging.INFO if event in ("sign_in", "sign_out", "session_expired") else logging.WARNING
    security_log.log(
        level,
        "%s: %s%s",
        event.replace("_", " ").capitalize(),
        username,
        f" ({detail})" if detail else "",
        extra={"event": event, "username": username, "ip": ip},
    )


@dataclass(frozen=True)
class Person:
    """An active user as others see them: to assign work to (cases, plan 8.4)."""

    principal: Principal
    display_name: str


def active_people(session: Session, user_ids: Iterable[int] | None = None) -> list[Person]:
    """Active users with their roles, by display name (no permission needed: callers
    choose whom to show)."""
    query = select(AppUser).where(AppUser.active.is_(True))
    if user_ids is not None:
        query = query.where(AppUser.id.in_(sorted(set(user_ids))))
    users = session.scalars(query.order_by(func.lower(AppUser.display_name))).all()
    return [
        Person(Principal(u.id, u.username, _assignments(session, u.id)), u.display_name)
        for u in users
    ]


def user_names(session: Session, user_ids: Iterable[int]) -> dict[int, str]:
    """Usernames by ID, to say who did what in a history (no permission needed: a name
    is shown wherever the action it took is)."""
    ids = sorted(set(user_ids))
    if not ids:
        return {}
    rows = session.execute(select(AppUser.id, AppUser.username).where(AppUser.id.in_(ids))).all()
    return {row.id: row.username for row in rows}
