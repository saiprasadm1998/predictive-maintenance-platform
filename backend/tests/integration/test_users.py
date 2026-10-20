"""Users, sign-in, sessions and authorisation in the services (plan 5.1; FR-SEC-01, -02,
UC-17, ARC §9.2, §9.3, AC-07)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from pmp import cli
from pmp.api import create_app
from pmp.core import (
    AccessDeniedError,
    Actor,
    ApiKeyScope,
    AuditLog,
    Database,
    Role,
    RoleAssignment,
    Settings,
    SignInError,
    UserError,
    create_user,
    get_settings,
    issue_api_key,
    reset_password,
    resolve_session,
    set_active,
    set_roles,
    sign_in,
)
from pmp.dataquality import RuleScope, save_rule_set
from pmp.registry import AssetLevel, AssetSpec, Criticality, find_asset, upsert_asset

pytestmark = pytest.mark.integration
SYSTEM = Actor.system()
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
PASSWORD = "correct horse battery"


@pytest.fixture
def db(clean_registry: Database) -> Database:
    with clean_registry.session() as s:
        s.execute(text("TRUNCATE app_user RESTART IDENTITY CASCADE"))
        for code, parent in (("SITE-A", None), ("SITE-B", None)):
            upsert_asset(s, SYSTEM, AssetSpec(code, code, AssetLevel.SITE, parent))
        upsert_asset(
            s, SYSTEM, AssetSpec("P-1", "Pump", AssetLevel.EQUIPMENT, "SITE-A", Criticality.A)
        )
    return clean_registry


def _create(db: Database, username: str, *assignments: RoleAssignment) -> None:
    with db.session() as s:
        create_user(
            s,
            SYSTEM,
            username=username,
            display_name=username.title(),
            password=PASSWORD,
            assignments=assignments or (RoleAssignment(Role.VIEWER),),
        )


def _asset_id(db: Database, code: str) -> int:
    with db.session() as s:
        asset = find_asset(s, code)
        assert asset is not None
        return asset.id


def _sign_in(db: Database, username: str, password: str, now: datetime) -> Any:
    """Like the API: the transaction commits even when sign-in fails."""
    with db.session() as s:
        try:
            return sign_in(s, username, password, now)
        except SignInError:
            return None


def _actor(db: Database, username: str) -> Actor:
    new = _sign_in(db, username, PASSWORD, T0)
    assert new is not None
    with db.session() as s:
        active = resolve_session(s, new.token, T0)
    assert active is not None
    return Actor.user(active.principal)


# ------------------------------------------------------------------ administration


def test_users_are_unique_whatever_the_case_and_changes_are_audited(db: Database) -> None:
    _create(db, "alice")
    with pytest.raises(UserError, match="already exists"):
        _create(db, "ALICE")
    with db.session() as s:
        set_roles(s, SYSTEM, "Alice", [RoleAssignment(Role.ANALYST, _asset_id(db, "SITE-A"))])
        actions = s.scalars(
            select(AuditLog.action).where(AuditLog.entity == "user").order_by(AuditLog.id)
        ).all()
        last = s.scalars(
            select(AuditLog).where(AuditLog.entity == "user").order_by(AuditLog.id.desc())
        ).first()
    assert actions[-2:] == ["create", "set_roles"]
    assert last is not None
    assert "password" not in str(last.before_after)


def test_only_administrators_manage_users(db: Database) -> None:
    _create(db, "admin", RoleAssignment(Role.ADMINISTRATOR))
    _create(db, "eve", RoleAssignment(Role.MODEL_ENGINEER))
    with db.session() as s, pytest.raises(AccessDeniedError):
        set_roles(s, _actor(db, "eve"), "eve", [RoleAssignment(Role.ADMINISTRATOR)])
    with db.session() as s:
        set_roles(s, _actor(db, "admin"), "eve", [RoleAssignment(Role.VIEWER)])
    with db.session() as s, pytest.raises(UserError, match="your own"):
        set_active(s, _actor(db, "admin"), "admin", False)


# ------------------------------------------------------------------ sign-in and sessions


def test_lockout_after_five_failures_for_fifteen_minutes(db: Database) -> None:
    _create(db, "bob")
    for i in range(5):
        assert _sign_in(db, "bob", "wrong password!!", T0 + timedelta(seconds=i)) is None
    assert _sign_in(db, "bob", PASSWORD, T0 + timedelta(minutes=14)) is None  # locked
    assert _sign_in(db, "bob", PASSWORD, T0 + timedelta(minutes=15, seconds=5)) is not None


def test_a_reset_password_unlocks_and_ends_sessions(db: Database) -> None:
    _create(db, "bob")
    new = _sign_in(db, "bob", PASSWORD, T0)
    for _ in range(5):
        _sign_in(db, "bob", "wrong password!!", T0)
    with db.session() as s:
        reset_password(s, SYSTEM, "bob", "another long passphrase")
        assert resolve_session(s, new.token, T0) is None
    assert _sign_in(db, "bob", "another long passphrase", T0) is not None


def test_sessions_end_after_thirty_idle_minutes_or_twelve_hours(db: Database) -> None:
    _create(db, "carol")
    new = _sign_in(db, "carol", PASSWORD, T0)
    with db.session() as s:
        assert resolve_session(s, new.token, T0 + timedelta(minutes=29)) is not None
        # used at 29 min: alive until 59 min
        assert resolve_session(s, new.token, T0 + timedelta(minutes=58)) is not None
    later = T0
    with db.session() as s:
        for _ in range(26):  # kept busy, but 12 h is the most a session lasts
            later += timedelta(minutes=29)
            alive = resolve_session(s, new.token, later)
            if later - T0 > timedelta(hours=12):
                assert alive is None
                break
            assert alive is not None
    with db.session() as s:
        other = sign_in(s, "carol", PASSWORD, T0)
    with db.session() as s:
        assert resolve_session(s, other.token, T0 + timedelta(minutes=31)) is None


def test_deactivation_ends_sessions_and_blocks_sign_in(db: Database) -> None:
    _create(db, "dave")
    new = _sign_in(db, "dave", PASSWORD, T0)
    with db.session() as s:
        set_active(s, SYSTEM, "dave", False)
        assert resolve_session(s, new.token, T0) is None
    assert _sign_in(db, "dave", PASSWORD, T0) is None


def test_role_changes_apply_to_open_sessions(db: Database) -> None:
    _create(db, "erin")
    new = _sign_in(db, "erin", PASSWORD, T0)
    with db.session() as s:
        set_roles(s, SYSTEM, "erin", [RoleAssignment(Role.ADMINISTRATOR)])
        active = resolve_session(s, new.token, T0)
    assert active is not None
    assert active.principal.roles == {Role.ADMINISTRATOR}


# ------------------------------------------------------------------ authorisation in services


def test_services_check_roles_and_scopes(db: Database) -> None:
    """ARC §9.2: checked in the services, so every caller (API, later screens) is held to
    the matrix. One service per permission built so far; the full matrix is unit-tested."""
    site_a, site_b = _asset_id(db, "SITE-A"), _asset_id(db, "SITE-B")
    _create(db, "eng-a", RoleAssignment(Role.MODEL_ENGINEER, site_a))
    _create(db, "eng", RoleAssignment(Role.MODEL_ENGINEER))
    _create(db, "admin", RoleAssignment(Role.ADMINISTRATOR))
    _create(db, "viewer", RoleAssignment(Role.VIEWER))
    eng_a, eng, admin, viewer = (_actor(db, u) for u in ("eng-a", "eng", "admin", "viewer"))

    def tried(actor: Actor, action: Any) -> bool:
        try:
            with db.session() as s:
                action(s, actor)
        except AccessDeniedError:
            return False
        return True

    def pump_on(site: str) -> Any:
        return lambda s, a: upsert_asset(
            s, a, AssetSpec(f"P-{site}", "Pump", AssetLevel.EQUIPMENT, site, Criticality.B)
        )

    assert tried(eng_a, pump_on("SITE-A"))  # registry, in scope
    assert not tried(eng_a, pump_on("SITE-B"))  # out of scope
    assert tried(admin, pump_on("SITE-B"))  # administrators have the registry
    assert not tried(viewer, pump_on("SITE-B"))

    global_rules = lambda s, a: save_rule_set(s, a, RuleScope.everywhere(), {"spike_pct": 30})  # noqa: E731
    assert tried(eng, global_rules)
    assert not tried(eng_a, global_rules)  # global rules need an unscoped Model Engineer
    assert not tried(admin, global_rules)  # not an administrator's job (§9.2)

    key = lambda s, a: issue_api_key(s, a, name="gw", scope=ApiKeyScope.INGEST)  # noqa: E731
    assert tried(admin, key)
    assert not tried(eng, key)
    assert site_b


# ------------------------------------------------------------------ API


@pytest.fixture
def client(db: Database, database_url: str, tmp_path: Path) -> Iterator[TestClient]:
    _create(db, "frank", RoleAssignment(Role.ANALYST))
    settings = Settings(
        database_url=database_url, secret_key="t", artefact_dir=tmp_path, _env_file=None
    )
    with TestClient(create_app(settings=settings, database=db), base_url="https://testserver") as c:
        yield c


def _login(client: TestClient, password: str = PASSWORD) -> Any:
    return client.post("/api/v1/auth/login", json={"username": "frank", "password": password})


def test_browser_sign_in_sets_a_safe_cookie_and_needs_csrf_for_changes(client: TestClient) -> None:
    response = _login(client)
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["roles"] == [{"role": "analyst", "scope_asset_id": None}]
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie
    assert client.get("/api/v1/auth/me").status_code == 200

    change = {"current_password": PASSWORD, "new_password": "a different passphrase"}
    refused = client.post("/api/v1/auth/password", json=change)
    assert (refused.status_code, refused.json()["code"]) == (403, "csrf_failed")
    headers = {"X-CSRF-Token": body["csrf_token"]}
    assert client.post("/api/v1/auth/password", json=change, headers=headers).status_code == 204

    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_api_clients_use_bearer_tokens_without_csrf(client: TestClient) -> None:
    response = client.post("/api/v1/auth/token", json={"username": "frank", "password": PASSWORD})
    assert response.status_code == 200
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/auth/me", headers=headers).json()["user"]["username"] == "frank"
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_failed_sign_in_says_the_same_whatever_the_cause(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="pmp.security"):
        unknown = client.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})
        wrong = _login(client, "not the password")
        _login(client)
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"] == "Invalid username or password"
    events = [e for r in caplog.records if (e := getattr(r, "event", None))]
    assert events == ["sign_in_failed", "sign_in_failed", "sign_in"]


# ------------------------------------------------------------------ command line


def test_user_commands(
    db: Database,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PMP_DATABASE_URL", database_url)
    monkeypatch.setenv("PMP_SECRET_KEY", "k")
    monkeypatch.setenv("PMP_LOG_FORMAT", "text")
    get_settings.cache_clear()
    monkeypatch.setattr("getpass.getpass", lambda prompt="": PASSWORD)

    def run(*argv: str) -> int:
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["user", *argv])
        return int(exit_info.value.code or 0)

    assert run("create", "grace", "--name", "Grace H", "--role", "administrator") == 0
    assert run("create", "heidi", "--role", "analyst@SITE-A", "--role", "viewer") == 0
    assert run("create", "ivan", "--role", "wizard") == 1
    assert run("set-roles", "heidi", "--role", "model_engineer@SITE-B") == 0
    assert run("deactivate", "heidi") == 0
    assert run("reset-password", "heidi") == 0
    assert run("list") == 0
    out, err = capsys.readouterr()
    assert "Created grace: Administrator" in out
    assert "Created heidi: Analyst @ SITE-A, Viewer" in out
    assert "heidi: Model Engineer @ SITE-B" in out
    assert "deactivated" in out
    assert "Unknown role 'wizard'" in err
    assert PASSWORD not in out + err


def _bearer(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/token", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_administrators_manage_api_keys_over_the_api(db: Database, client: TestClient) -> None:
    _create(db, "root", RoleAssignment(Role.ADMINISTRATOR))
    admin, analyst = _bearer(client, "root"), _bearer(client, "frank")
    new_key = {"name": "gw", "scope": "ingest"}
    refused = client.post(
        "/api/v1/api-keys", json={"name": "gw", "scope": "ingest"}, headers=analyst
    )
    assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")

    issued = client.post("/api/v1/api-keys", json=new_key, headers=admin)
    assert issued.status_code == 201
    key = issued.json()
    assert key["key"].startswith(f"pmp_{key['prefix']}_")
    listed = {k["id"]: k for k in client.get("/api/v1/api-keys", headers=admin).json()}
    assert listed[key["id"]]["prefix"] == key["prefix"]
    assert "key" not in listed[key["id"]]  # never shown again
    rotated = client.post(f"/api/v1/api-keys/{key['id']}/rotate", headers=admin)
    assert rotated.status_code == 201
    assert client.post(f"/api/v1/api-keys/{key['id']}/revoke", headers=admin).status_code == 204
    states = {
        k["id"]: k["revoked_at"] is None
        for k in client.get("/api/v1/api-keys", headers=admin).json()
    }
    assert (states[key["id"]], states[rotated.json()["id"]]) == (False, True)


def test_administrators_search_and_export_the_audit_trail(db: Database, client: TestClient) -> None:
    _create(db, "root", RoleAssignment(Role.ADMINISTRATOR))
    admin, analyst = _bearer(client, "root"), _bearer(client, "frank")
    assert client.get("/api/v1/audit", headers=analyst).status_code == 403

    page = client.get("/api/v1/audit", params={"entity": "user", "limit": 1}, headers=admin)
    assert page.status_code == 200
    first = page.json()
    assert [i["action"] for i in first["items"]] == ["create"]
    assert first["next_cursor"] is not None
    older = client.get(
        "/api/v1/audit",
        params={"entity": "user", "limit": 1, "cursor": first["next_cursor"]},
        headers=admin,
    ).json()
    assert older["items"][0]["id"] < first["items"][0]["id"]
    naive = client.get("/api/v1/audit", params={"from": "2026-10-01T00:00:00"}, headers=admin)
    assert naive.status_code == 400

    exported = client.get("/api/v1/audit.csv", params={"entity": "user"}, headers=admin)
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    lines = exported.text.splitlines()
    assert lines[0] == "id,ts,user_id,actor_type,entity,entity_id,action,before,after,ip"
    assert len(lines) >= 3  # frank and root at least (the audit log is append-only)
    assert all(",user," in line for line in lines[1:])


def test_audit_command(
    db: Database,
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _create(db, "judy")
    monkeypatch.setenv("PMP_DATABASE_URL", database_url)
    monkeypatch.setenv("PMP_SECRET_KEY", "k")
    monkeypatch.setenv("PMP_LOG_FORMAT", "text")
    get_settings.cache_clear()
    target = tmp_path / "audit.csv"
    for argv in (["audit", "--entity", "user"], ["audit", "--from", "-1d", "--csv", str(target)]):
        with pytest.raises(SystemExit) as exit_info:
            cli.main(argv)
        assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "user:1" in out
    assert "create" in out
    assert target.read_text().startswith("id,ts,")
