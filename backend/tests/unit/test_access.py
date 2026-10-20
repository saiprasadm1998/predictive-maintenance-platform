"""The ARC §9.2 permission matrix and role scoping (FR-SEC-02, AC-07)."""

from __future__ import annotations

import logging

import pytest

from pmp.core import (
    MATRIX,
    AccessDeniedError,
    Actor,
    ActorType,
    Grant,
    Permission,
    Principal,
    Role,
    RoleAssignment,
    authorize,
)

# ARC-001 §9.2 as printed: ✔ allowed, "assigned" only on assigned cases, blank refused.
# Columns: Viewer, Analyst, Maintenance, Model Engineer, Administrator.
ARC_9_2 = """
view               | ✔ | ✔ | ✔        | ✔ | ✔
alert_actions      |   | ✔ |          | ✔ |
run_forecasts      |   | ✔ |          | ✔ |
manage_cases       |   | ✔ | assigned | ✔ |
work_on_cases      |   | ✔ | assigned | ✔ |
sensor_exclusion   |   | ✔ |          | ✔ |
registry           |   |   |          | ✔ | ✔
data_quality_rules |   |   |          | ✔ |
models             |   |   |          | ✔ |
failure_modes      |   |   |          | ✔ |
administration     |   |   |          |   | ✔
audit_log          |   |   |          |   | ✔
own_subscriptions  | ✔ | ✔ | ✔        | ✔ | ✔
"""
COLUMNS = [Role.VIEWER, Role.ANALYST, Role.MAINTENANCE, Role.MODEL_ENGINEER, Role.ADMINISTRATOR]


def arc_table() -> dict[tuple[Permission, Role], str]:
    table = {}
    for line in ARC_9_2.strip().splitlines():
        name, *cells = (c.strip() for c in line.split("|"))
        for role, cell in zip(COLUMNS, cells, strict=True):
            table[(Permission(name), role)] = cell
    return table


def principal(*assignments: RoleAssignment) -> Principal:
    return Principal(1, "sam", assignments)


def test_the_matrix_is_arc_9_2_word_for_word() -> None:
    expected = arc_table()
    assert {p for p, _ in expected} == set(Permission)
    for (permission, role), cell in expected.items():
        grant = MATRIX[permission].get(role)
        assert grant == {"✔": Grant.YES, "assigned": Grant.ASSIGNED, "": None}[cell], (
            permission,
            role,
        )


@pytest.mark.parametrize(("permission", "role"), list(arc_table()))
def test_every_role_can_do_exactly_what_the_matrix_allows(
    permission: Permission, role: Role
) -> None:
    """AC-07: generated from ARC §9.2, every role against every function."""
    cell = arc_table()[(permission, role)]
    user = principal(RoleAssignment(role))
    assert user.grant(permission, "1.2.3") is (cell == "✔")
    assert user.grant(permission, "1.2.3", assigned=True) is (cell in ("✔", "assigned"))
    actor = Actor.user(user)
    if cell == "✔":
        authorize(actor, permission, "1.2.3")
    else:
        with pytest.raises(AccessDeniedError):
            authorize(actor, permission, "1.2.3")


def test_a_scoped_role_covers_its_subtree_only() -> None:
    analyst_site_a = principal(RoleAssignment(Role.ANALYST, scope_asset_id=5))
    assert analyst_site_a.grant(Permission.ALERT_ACTIONS, "1.5")  # the site itself
    assert analyst_site_a.grant(Permission.ALERT_ACTIONS, "1.5.9.12")  # below it
    assert not analyst_site_a.grant(Permission.ALERT_ACTIONS, "1.6.9")  # another site
    assert not analyst_site_a.grant(Permission.ALERT_ACTIONS, "1.15")  # not a prefix match
    assert not analyst_site_a.grant(Permission.ALERT_ACTIONS)  # no asset: needs unscoped


def test_assignments_add_up() -> None:
    user = principal(
        RoleAssignment(Role.VIEWER), RoleAssignment(Role.MODEL_ENGINEER, scope_asset_id=5)
    )
    assert user.grant(Permission.VIEW, "1.6")
    assert user.grant(Permission.MODELS, "1.5.7")
    assert not user.grant(Permission.MODELS, "1.6.7")
    assert user.visible_scopes() is None  # Viewer everywhere
    assert user.visible_scopes(Permission.MODELS) == [5]
    assert principal(RoleAssignment(Role.VIEWER)).visible_scopes(Permission.MODELS) == []


def test_the_system_actor_is_trusted_and_others_need_a_principal(
    caplog: pytest.LogCaptureFixture,
) -> None:
    authorize(Actor.system(), Permission.ADMINISTRATION)
    with caplog.at_level(logging.WARNING, logger="pmp.security"):
        with pytest.raises(AccessDeniedError, match="administration"):
            authorize(Actor(ActorType.API_KEY), Permission.ADMINISTRATION)
        with pytest.raises(AccessDeniedError, match="users"):
            authorize(
                Actor.user(principal(RoleAssignment(Role.VIEWER))),
                Permission.ADMINISTRATION,
                what="users",
            )
    denials = [r for r in caplog.records if getattr(r, "event", None) == "permission_denied"]
    assert len(denials) == 2
