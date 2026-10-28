"""Cases against PostgreSQL (plan 8.4, UC-12, UC-13, FR-CAS-01 to -03).

The case is created from the alert-engine tests' DI warning on EQ-1 / main.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from pmp.cases import (
    CaseConflictError,
    CaseError,
    CaseStatus,
    Outcome,
    add_action,
    add_attachment,
    add_comment,
    assignable_people,
    change_status,
    close_case,
    complete_action,
    count_open_cases,
    create_case,
    get_case,
    link_alerts,
    list_cases,
    open_cases_for_alerts,
    update_case,
)
from pmp.cases.service import CaseQuery
from pmp.core import (
    AccessDeniedError,
    Actor,
    AuditLog,
    Database,
    Principal,
    Role,
    RoleAssignment,
    create_user,
)
from tests.integration.test_alerts import _raise_one, _run, _scheduler
from tests.integration.test_scoring_cycle import (  # noqa: F401  (deployed is a fixture)
    ACTOR,
    LIVE,
    deployed,
)

pytestmark = pytest.mark.integration
NOW = LIVE + timedelta(minutes=5)


@pytest.fixture
def db(deployed: Database) -> Database:  # noqa: F811
    with deployed.session() as s:
        s.execute(text("TRUNCATE app_user RESTART IDENTITY CASCADE"))
        s.execute(text('TRUNCATE "case" RESTART IDENTITY CASCADE'))
        for name, role in (
            ("ana", Role.ANALYST),
            ("max", Role.MAINTENANCE),
            ("vic", Role.VIEWER),
        ):
            create_user(
                s,
                ACTOR,
                username=name,
                display_name=name.capitalize(),
                password="correct horse battery",
                assignments=[RoleAssignment(role)],
            )
    return deployed


def actor(db: Database, username: str) -> Actor:
    with db.session() as s:
        row = s.execute(
            text("SELECT id FROM app_user WHERE username = :u"), {"u": username}
        ).scalar_one()
        role = s.execute(
            text("SELECT role FROM user_role WHERE user_id = :u"), {"u": row}
        ).scalar_one()
    return Actor.user(Principal(row, username, (RoleAssignment(Role(role)),)))


def copy_alert(db: Database, alert_id: int) -> int:
    """A second (closed) alert of the same model, to link to a case."""
    with db.session() as s:
        return int(
            s.execute(
                text(
                    "INSERT INTO alert (rule_id, model_id, kind, tag_id, state, severity, "
                    "priority, condition_active, raised_at, version_id, trace, closed_at) "
                    "SELECT rule_id, model_id, kind, tag_id, 'Normal', 'Alert', 'P1', false, "
                    "raised_at, version_id, trace, raised_at FROM alert WHERE id = :id "
                    "RETURNING id"
                ),
                {"id": alert_id},
            ).scalar_one()
        )


def test_detect_diagnose_act_close(db: Database, tmp_path: Path) -> None:
    alert_id = _raise_one(db)  # DI warning, P2
    ana, max_ = actor(db, "ana"), actor(db, "max")
    with db.session() as s:
        audited_before = int(s.scalar(select(func.max(AuditLog.id))) or 0)
    with db.session() as s:
        case = create_case(s, ana, [alert_id], now=NOW)
    assert (case.number, case.status, case.priority) == ("C-0001", CaseStatus.OPEN, "P2")
    assert case.title == "EQ-1 DI warning"
    snapshot = case.snapshot
    (model,) = snapshot["models"]
    assert model["asset_code"] == "EQ-1"
    assert model["limits"] == {"warning": 10, "alert": 200}
    assert model["trend"]["di"]
    assert {x["source_name"] for x in model["sensors"]} >= {"EQ1.T1"}
    assert snapshot["alerts"][0]["id"] == alert_id

    with db.session() as s:
        assert open_cases_for_alerts(s, [alert_id]) == {alert_id: case.id}
        assert count_open_cases(s, [case.asset_id]) == 1
        with pytest.raises(CaseConflictError, match="already in open case C-0001"):
            create_case(s, ana, [alert_id], now=NOW)
        # a second alert of the asset joins the case and raises its priority to P1
        second = copy_alert(db, alert_id)
        linked = link_alerts(s, ana, case.id, [second, alert_id], now=NOW)
    assert linked.alert_ids == (alert_id, second)
    assert linked.priority == "P1"

    with db.session() as s:
        people = {p.principal.username for p in assignable_people(s, case.asset_path)}
        assert people == {"ana", "max"}  # viewers cannot work on cases
        with pytest.raises(CaseError, match="Assign the case before investigating"):
            change_status(s, ana, case.id, CaseStatus.INVESTIGATING, now=NOW)
        assigned = update_case(
            s, ana, case.id, assignee_id=max_.user_id, due=date(2026, 6, 10), now=NOW
        )
    assert assigned.status is CaseStatus.INVESTIGATING  # assigning starts the investigation
    assert assigned.assignee_id == max_.user_id

    with db.session() as s:  # the maintenance engineer works on the case assigned to them
        add_comment(s, max_, case.id, "Oil sample: elevated iron particles.", now=NOW)
        add_attachment(s, max_, case.id, "../photo.png", "image/png", b"\x89PNG", tmp_path, now=NOW)
        acting = add_action(s, max_, case.id, "Reduce load to 85 %", owner_id=max_.user_id, now=NOW)
    assert acting.status is CaseStatus.ACTION_REQUIRED  # an action was defined
    (attachment,) = acting.attachments
    assert attachment.filename == "photo.png"
    assert (tmp_path / f"cases/{case.id}/{attachment.id}").read_bytes() == b"\x89PNG"
    (action,) = acting.actions

    with db.session() as s:
        with pytest.raises(CaseError, match="open actions"):
            change_status(s, ana, case.id, CaseStatus.MONITORING, now=NOW)
        monitoring = complete_action(s, max_, case.id, action.id, now=NOW)
    assert monitoring.status is CaseStatus.MONITORING  # the last action is done

    with db.session() as s:
        with pytest.raises(CaseError, match="outcome"):
            close_case(s, max_, case.id, None, now=NOW)
        with pytest.raises(CaseError, match="confirmed failure mode"):
            close_case(s, max_, case.id, Outcome.TRUE_FINDING, now=NOW)
        with pytest.raises(CaseError, match="does not exist"):
            close_case(s, max_, case.id, Outcome.TRUE_FINDING, 999_999, now=NOW)
        closed = close_case(
            s, max_, case.id, Outcome.FALSE_ALERT, lessons="Limits too tight", now=NOW
        )
    assert closed.status is CaseStatus.CLOSED
    assert closed.review_requested  # UC-13 2a: the model engineer is asked to review
    assert closed.snapshot == snapshot
    assert [a.type.value for a in closed.activities] == [
        "created",
        "link",
        "update",
        "assignment",
        "state_change",
        "comment",
        "attachment",
        "action",
        "state_change",
        "update",
        "state_change",
        "closure",
        "state_change",
    ]
    with db.session() as s:
        assert open_cases_for_alerts(s, [alert_id]) == {}  # free for a new case
        assert count_open_cases(s, [case.asset_id]) == 0
        transitions = s.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.entity == "case",
                AuditLog.action == "transition",
                AuditLog.id > audited_before,
            )
        )
        assert transitions == 4  # FR-CAS-02: every transition is audited
        with pytest.raises(CaseConflictError):
            add_comment(s, ana, case.id, "too late", now=NOW)
        again = create_case(s, ana, [alert_id], "Second look", now=NOW)
    assert again.number == "C-0002"
    with db.session() as s:
        listed = list_cases(s, CaseQuery())
        assert [c.number for c in listed] == ["C-0002", "C-0001"]  # open first
        assert [c.number for c in list_cases(s, CaseQuery(outcome=Outcome.FALSE_ALERT))] == [
            "C-0001"
        ]


def test_the_snapshot_never_changes(db: Database) -> None:
    alert_id = _raise_one(db)
    with db.session() as s:
        case = create_case(s, ACTOR, [alert_id], now=NOW)
    _run(_scheduler(db, minutes=2), 3)  # later cycles arrive
    with db.session() as s:
        assert get_case(s, case.id).snapshot == case.snapshot
    with pytest.raises(DBAPIError, match="cannot be changed"), db.session() as s:
        s.execute(text("""UPDATE "case" SET snapshot = '{}'::jsonb"""))


def test_who_may_do_what(db: Database) -> None:
    alert_id = _raise_one(db)
    ana, max_, vic = actor(db, "ana"), actor(db, "max"), actor(db, "vic")
    with db.session() as s, pytest.raises(AccessDeniedError):
        create_case(s, max_, [alert_id], now=NOW)  # maintenance: assigned cases only
    with db.session() as s, pytest.raises(AccessDeniedError):
        create_case(s, vic, [alert_id], now=NOW)
    with db.session() as s, pytest.raises(AccessDeniedError):
        create_case(s, vic, [999_999], now=NOW)  # refused before learning it does not exist
    with db.session() as s:
        case = create_case(s, ana, [alert_id], now=NOW)
    with db.session() as s, pytest.raises(AccessDeniedError):
        add_comment(s, max_, case.id, "not mine yet", now=NOW)
    with db.session() as s, pytest.raises(CaseError, match="cannot be the assignee"):
        update_case(s, ana, case.id, assignee_id=vic.user_id, now=NOW)
    with db.session() as s, pytest.raises(CaseError, match="reason"):
        change_status(s, ana, case.id, CaseStatus.CANCELLED, now=NOW)
    with db.session() as s:
        cancelled = change_status(s, ana, case.id, CaseStatus.CANCELLED, "Duplicate", now=NOW)
    assert cancelled.status is CaseStatus.CANCELLED
    assert cancelled.cancel_reason == "Duplicate"
    with db.session() as s, pytest.raises(CaseConflictError, match="cannot go from"):
        change_status(s, ana, case.id, CaseStatus.INVESTIGATING, now=NOW)


def test_attachments_are_limited_to_20_mb(db: Database, tmp_path: Path) -> None:
    alert_id = _raise_one(db)
    with db.session() as s:
        case = create_case(s, ACTOR, [alert_id], now=NOW)
        with pytest.raises(CaseError, match="20 MB"):
            add_attachment(
                s, ACTOR, case.id, "big.bin", "", b"0" * (20 * 1024 * 1024 + 1), tmp_path
            )
