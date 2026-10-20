"""Roles and permissions (FR-SEC-01, -02, ARC §9.2, PRD §4).

The permission matrix below is ARC-001 §9.2 row by row. Authorisation is checked in the
application services, not only at the router (ARC §9.2), with `authorize`. Tests are
generated from MATRIX.

A user holds one or more role assignments, each optionally scoped to a hierarchy node
("Analyst for Site A only"). An action on an asset is allowed if an assignment whose role
grants the permission covers that asset (unscoped, or scoped to the asset or one of its
ancestors). An action not tied to an asset (for example user administration) needs an
unscoped assignment.

Scopes are compared on asset paths: the registry's ltree path of asset IDs ("1.5.9"), so
core needs no registry import.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pmp.core.audit import Actor

security_log = logging.getLogger("pmp.security")


class Role(StrEnum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    MAINTENANCE = "maintenance"
    MODEL_ENGINEER = "model_engineer"
    ADMINISTRATOR = "administrator"

    @property
    def label(self) -> str:
        return {
            Role.VIEWER: "Viewer",
            Role.ANALYST: "Analyst",
            Role.MAINTENANCE: "Maintenance",
            Role.MODEL_ENGINEER: "Model Engineer",
            Role.ADMINISTRATOR: "Administrator",
        }[self]


class Permission(StrEnum):
    """The rows of the ARC §9.2 matrix."""

    VIEW = "view"  # fleet, assets, alerts, cases, reports
    ALERT_ACTIONS = "alert_actions"  # acknowledge / shelve alerts
    RUN_FORECASTS = "run_forecasts"
    MANAGE_CASES = "manage_cases"  # create cases; change case state
    WORK_ON_CASES = "work_on_cases"  # add case activity; close case
    SENSOR_EXCLUSION = "sensor_exclusion"  # manual sensor exclusion / override
    REGISTRY = "registry"  # registry and imports
    DATA_QUALITY_RULES = "data_quality_rules"
    MODELS = "models"  # build, deploy, pause, retire; alert limits
    FAILURE_MODES = "failure_modes"  # failure-mode library; approve proposals
    ADMINISTRATION = "administration"  # users, roles, API keys, notification settings, retention
    AUDIT_LOG = "audit_log"
    OWN_SUBSCRIPTIONS = "own_subscriptions"  # own notification subscriptions


class Grant(Enum):
    YES = "yes"
    ASSIGNED = "assigned"  # only on cases assigned to the user (Maintenance, Phase 8)


_V, _AN, _MA, _ME, _AD = (
    Role.VIEWER,
    Role.ANALYST,
    Role.MAINTENANCE,
    Role.MODEL_ENGINEER,
    Role.ADMINISTRATOR,
)
_ALL = (_V, _AN, _MA, _ME, _AD)
Y, A = Grant.YES, Grant.ASSIGNED

# ARC-001 §9.2, verbatim: function -> role -> grant (no entry: not allowed)
MATRIX: Mapping[Permission, Mapping[Role, Grant]] = {
    Permission.VIEW: dict.fromkeys(_ALL, Y),
    Permission.ALERT_ACTIONS: {_AN: Y, _ME: Y},
    Permission.RUN_FORECASTS: {_AN: Y, _ME: Y},
    Permission.MANAGE_CASES: {_AN: Y, _MA: A, _ME: Y},
    Permission.WORK_ON_CASES: {_AN: Y, _MA: A, _ME: Y},
    Permission.SENSOR_EXCLUSION: {_AN: Y, _ME: Y},
    Permission.REGISTRY: {_ME: Y, _AD: Y},
    Permission.DATA_QUALITY_RULES: {_ME: Y},
    Permission.MODELS: {_ME: Y},
    Permission.FAILURE_MODES: {_ME: Y},
    Permission.ADMINISTRATION: {_AD: Y},
    Permission.AUDIT_LOG: {_AD: Y},
    Permission.OWN_SUBSCRIPTIONS: dict.fromkeys(_ALL, Y),
}


class AccessDeniedError(PermissionError):
    """The actor may not do this (HTTP 403)."""


@dataclass(frozen=True)
class RoleAssignment:
    role: Role
    scope_asset_id: int | None = None  # None: everywhere

    def covers(self, asset_path: str | None) -> bool:
        if self.scope_asset_id is None:
            return True
        if asset_path is None:
            return False  # a scoped role never grants an action outside the hierarchy
        return str(self.scope_asset_id) in asset_path.split(".")


@dataclass(frozen=True)
class Principal:
    """A signed-in user and what they may do, loaded fresh for every request so that
    access changes take effect immediately (UC-17)."""

    user_id: int
    username: str
    assignments: tuple[RoleAssignment, ...]

    @property
    def roles(self) -> frozenset[Role]:
        return frozenset(a.role for a in self.assignments)

    def grant(
        self, permission: Permission, asset_path: str | None = None, *, assigned: bool = False
    ) -> bool:
        """Whether the user may do `permission` on the asset at `asset_path` (None: an
        action not tied to an asset). `assigned`: the case is assigned to this user."""
        for assignment in self.assignments:
            grant = MATRIX[permission].get(assignment.role)
            if grant is None or not assignment.covers(asset_path):
                continue
            if grant is Grant.YES or (grant is Grant.ASSIGNED and assigned):
                return True
        return False

    def visible_scopes(self, permission: Permission = Permission.VIEW) -> list[int] | None:
        """Asset IDs whose subtrees the user may see with `permission`; None means
        everywhere. For filtering lists and the event stream (5.2, 5.3)."""
        scopes: list[int] = []
        for assignment in self.assignments:
            if assignment.role not in MATRIX[permission]:
                continue
            if assignment.scope_asset_id is None:
                return None
            scopes.append(assignment.scope_asset_id)
        return scopes


def allowed_roles(permission: Permission) -> Iterable[Role]:
    return MATRIX[permission].keys()


def authorize(
    actor: Actor,
    permission: Permission,
    asset_path: str | None = None,
    *,
    what: str = "",
    assigned: bool = False,
) -> None:
    """Raise AccessDeniedError unless the actor may do `permission` (on the asset at
    `asset_path`). The system actor (CLI, scheduler, jobs) is trusted. API keys never
    reach these services: their scopes are checked at the endpoint (ARC §9.3). Denials
    are security events (ARC §9.3 FR 6)."""
    from pmp.core.audit import ActorType

    if actor.actor_type is ActorType.SYSTEM:
        return
    principal = actor.principal
    if principal is not None and principal.grant(permission, asset_path, assigned=assigned):
        return
    security_log.warning(
        "Permission denied: %s needs %s%s",
        principal.username if principal else f"{actor.actor_type.value} {actor.user_id}",
        permission.value,
        f" for {what}" if what else "",
        extra={
            "event": "permission_denied",
            "user_id": actor.user_id,
            "permission": permission.value,
            "ip": actor.ip,
        },
    )
    raise AccessDeniedError(
        f"Not allowed: {permission.value.replace('_', ' ')}" + (f" ({what})" if what else "")
    )
