"""Command line: `pmp web | worker | migrate | registry | ingest | dq | algorithms | model |
score | alert | health | user | audit | retention | demo | apikey`.

See ARC-001 §10.1 and §12.

One image runs both roles. `pmp registry import` and `pmp dq` stand in for the REST
endpoints (5.2) and screens (6.6) until they arrive. `pmp backup` is added in sub-phase 9.1.
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import re
import signal
import sys
import threading
import urllib.error
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FrameType

import uvicorn
from sqlalchemy.orm import Session

from pmp.alerting import (
    AlertChanged,
    AlertError,
    AlertRuleError,
    AlertState,
    AlertView,
    RuleKind,
    Severity,
    acknowledge,
    alert_history,
    get_alert,
    get_priority_matrix,
    list_alert_rules,
    list_alerts,
    require_di_rule,
    rule_states,
    rules_from_dict,
    set_alert_rules,
    set_priority,
    shelve,
    unshelve,
)
from pmp.api import create_app
from pmp.core import (
    RETENTION_JOB,
    Actor,
    ApiKeyError,
    ApiKeyScope,
    AuditFilter,
    Database,
    JobRegistry,
    RetentionError,
    Role,
    RoleAssignment,
    Settings,
    UserError,
    Worker,
    apply_retention,
    audit_csv,
    configure_logging,
    create_user,
    get_retention,
    get_settings,
    get_user,
    issue_api_key,
    list_api_keys,
    list_users,
    query_audit,
    reset_password,
    revoke_api_key,
    rotate_api_key,
    run_migrations,
    set_active,
    set_retention,
    set_roles,
)
from pmp.dataquality import (
    DEFAULTS,
    PARAM_NAMES,
    DataQualityError,
    RuleScope,
    effective_params,
    evaluate_sensors,
    get_rule_set,
    get_sensor_statuses,
    list_rule_versions,
    preview_rules,
    save_rule_set,
)
from pmp.demo import DEFAULT_SEED, PlantSimulator, demo_tags, load_history, replay
from pmp.demo_story import back_score, latest_sample_time, setup_models
from pmp.diagnostics import diagnose, import_library, list_modes
from pmp.evaluation import EvaluationError, evaluate, format_report, read_events
from pmp.ingestion import (
    BACKFILL_JOB,
    MAX_GRACE_S,
    BackfillError,
    BackfillOptions,
    IngestError,
    Layout,
    OverlapMode,
    make_backfill_handler,
    run_backfill,
    set_source_grace,
)
from pmp.modelling import (
    TRAIN_JOB,
    Action,
    ModelCache,
    ModelError,
    ModelView,
    available_detectors,
    change_status,
    definition_from_dict,
    find_model,
    get_model,
    list_active_versions,
    list_models,
    make_training_failure_handler,
    make_training_handler,
    run_training,
    save_draft,
    start_training,
)
from pmp.registry import (
    ImportFailedError,
    ImportReport,
    RegistryError,
    TagView,
    find_asset,
    get_asset_by_id,
    get_tags,
    import_files,
    list_tags,
)
from pmp.scoring import (
    RETAINED_TABLES,
    Band,
    CycleResult,
    NodeHealth,
    Scheduler,
    deployed_references,
    get_runtime_statuses,
    health_tree,
    latest_due_cycle,
    make_retention_handler,
    score_models,
)

logger = logging.getLogger(__name__)


def _date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _when(value: str) -> datetime:
    match = re.fullmatch(r"-(\d+)([mhd])", value.strip())
    if match:
        amount, unit = int(match.group(1)), match.group(2)
        delta = {
            "m": timedelta(minutes=amount),
            "h": timedelta(hours=amount),
            "d": timedelta(days=amount),
        }[unit]
        return datetime.now(UTC) - delta
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


_TIME_OPTIONS = ("--from", "--at")
_RELATIVE = re.compile(r"-\d+[mhd]")


_DURATION = re.compile(r"^(\d+)([mhd])$")


def _duration(value: str) -> timedelta:
    """A duration such as 30m, 8h or 2d."""
    match = _DURATION.match(value.strip())
    if not match:
        raise argparse.ArgumentTypeError(f"{value!r} is not a duration such as 30m, 8h or 2d")
    unit = {"m": "minutes", "h": "hours", "d": "days"}[match.group(2)]
    return timedelta(**{unit: int(match.group(1))})


def _attach_relative_times(argv: Sequence[str]) -> list[str]:
    """Turn `--from -2h` into `--from=-2h`: argparse reads a bare -2h as an option."""
    args = list(argv)
    joined: list[str] = []
    i = 0
    while i < len(args):
        if args[i] in _TIME_OPTIONS and i + 1 < len(args) and _RELATIVE.fullmatch(args[i + 1]):
            joined.append(f"{args[i]}={args[i + 1]}")
            i += 2
        else:
            joined.append(args[i])
            i += 1
    return joined


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pmp", description="Predictive Maintenance Platform")
    commands = parser.add_subparsers(dest="command", required=True)

    web = commands.add_parser("web", help="run the web role (REST API, live events, front end)")
    web.add_argument("--host", help="bind address (default: PMP_WEB_HOST)")
    web.add_argument("--port", type=int, help="port (default: PMP_WEB_PORT)")
    web.add_argument(
        "--no-migrate", action="store_true", help="skip running database migrations on start"
    )

    commands.add_parser("worker", help="run the worker role (jobs; scheduler from phase 4)")
    commands.add_parser("migrate", help="upgrade the database to the latest migration")

    registry = commands.add_parser("registry", help="asset and tag registry")
    registry_commands = registry.add_subparsers(dest="registry_command", required=True)
    registry_import = registry_commands.add_parser(
        "import",
        help="import asset types, roles, assets and tags from an .xlsx workbook or .csv files",
    )
    registry_import.add_argument("files", nargs="+", type=Path, help=".xlsx or <sheet>.csv files")
    registry_import.add_argument(
        "--dry-run", action="store_true", help="validate only; change nothing"
    )

    ingest = commands.add_parser("ingest", help="data ingestion")
    ingest_commands = ingest.add_subparsers(dest="ingest_command", required=True)
    backfill = ingest_commands.add_parser(
        "backfill", help="import a history file (CSV or Parquet, long or wide) directly"
    )
    backfill.add_argument("file", type=Path)
    backfill.add_argument("--source", required=True, help="gateway source the tags belong to")
    backfill.add_argument("--layout", choices=[x.value for x in Layout], help="default: detect")
    backfill.add_argument(
        "--mode",
        choices=[m.value for m in OverlapMode],
        default=OverlapMode.SKIP.value,
        help="what to do with samples that already exist (default: skip)",
    )
    backfill.add_argument(
        "--naive-as-utc", action="store_true", help="read timestamps without an offset as UTC"
    )
    backfill.add_argument("--preview", action="store_true", help="validate only; store nothing")
    grace = ingest_commands.add_parser(
        "grace", help="how long scoring waits for a source's late samples (ARC §5.1)"
    )
    grace.add_argument("source", help="gateway source")
    grace.add_argument("seconds", help=f"0 to {MAX_GRACE_S}, or 'default'")

    dq = commands.add_parser("dq", help="sensor data-quality rules and NE 107 status (UC-04)")
    dq_commands = dq.add_subparsers(dest="dq_command", required=True)
    for name, text in (
        ("show", "show the overrides and effective parameters for a scope"),
        ("set", "save overrides for a scope as a new version (previews first)"),
        ("preview", "show the effect of the rules (optionally changed) on recent data"),
    ):
        command = dq_commands.add_parser(name, help=text)
        where = command.add_mutually_exclusive_group()
        where.add_argument("--role", metavar="TYPE/ROLE", help="an asset-type role")
        where.add_argument("--tag", metavar="NAME", help="a tag's source name")
        command.add_argument("--source", help="the tag's source, if the name is not unique")
        if name != "show":
            command.add_argument(
                "params",
                nargs="*",
                metavar="NAME=VALUE",
                help=f"e.g. spike_pct=30 flatline=off; VALUE 'default' removes an override. "
                f"Names: {', '.join(PARAM_NAMES)}",
            )
            command.add_argument("--days", type=int, default=30, help="preview length (30)")
    dq_commands.choices["set"].add_argument("--comment", default="", help="why it changed")
    dq_commands.choices["set"].add_argument(
        "--yes", action="store_true", help="save even if more than 20 %% would be excluded"
    )
    dq_status = dq_commands.add_parser("status", help="evaluate the rules now and list statuses")
    dq_status.add_argument("--asset", help="only this asset's tags")
    dq_status.add_argument("--at", type=_when, help="cycle time: e.g. -1h or ISO 8601 (now)")

    algorithms = commands.add_parser("algorithms", help="normal-behaviour algorithms (detectors)")
    algorithm_commands = algorithms.add_subparsers(dest="algorithms_command", required=True)
    algorithm_commands.add_parser(
        "list", help="list detectors found and whether they passed the contract suite"
    )

    model = commands.add_parser("model", help="model definitions and alert rules (UC-05)")
    model_commands = model.add_subparsers(dest="model_command", required=True)
    model_create = model_commands.add_parser(
        "create",
        help="create a model, or update its draft, from a JSON definition file "
        "(see data/demo/models/k101.json)",
    )
    model_create.add_argument("file", type=Path)
    model_show = model_commands.add_parser("show", help="show a model, its versions and rules")
    model_show.add_argument("asset")
    model_show.add_argument("name")
    model_train = model_commands.add_parser(
        "train", help="train the model's Draft version (a job for the worker, or --now)"
    )
    model_train.add_argument("asset")
    model_train.add_argument("name")
    model_train.add_argument(
        "--now", action="store_true", help="train here and wait, instead of queuing a job"
    )
    for action, text in (
        ("deploy", "put a Validated version in service (the previous one is superseded)"),
        ("pause", "pause the version in service"),
        ("resume", "resume a paused version"),
        ("retire", "take the version in service out of service for good"),
        ("reject", "send a Validated version back to Draft"),
    ):
        command = model_commands.add_parser(action, help=text)
        command.add_argument("asset")
        command.add_argument("name")
        command.add_argument("--version", type=int, help="a specific version number")
    model_list = model_commands.add_parser("list", help="list models")
    model_list.add_argument("--asset", help="only this asset's models")

    score = commands.add_parser("score", help="scoring: run a cycle by hand, show statuses")
    score_commands = score.add_subparsers(dest="score_command", required=True)
    score_once = score_commands.add_parser(
        "once", help="score one cycle of a deployed model now (or --at a past cycle)"
    )
    score_once.add_argument("asset")
    score_once.add_argument("name")
    score_once.add_argument("--at", type=_when, help="cycle time: e.g. -5m or ISO 8601")
    score_commands.add_parser("status", help="each model's runtime status and latest score")

    alert = commands.add_parser("alert", help="alerts: list, acknowledge, shelve; priority matrix")
    alert_commands = alert.add_subparsers(dest="alert_command", required=True)
    alert_list = alert_commands.add_parser("list", help="open alerts (or --all)")
    alert_list.add_argument("--all", action="store_true", help="include closed (Normal) alerts")
    alert_show = alert_commands.add_parser("show", help="one alert with its trace and history")
    alert_show.add_argument("id", type=int)
    alert_ack = alert_commands.add_parser("ack", help="acknowledge one or more alerts")
    alert_ack.add_argument("ids", type=int, nargs="+")
    alert_ack.add_argument("--comment")
    alert_shelve = alert_commands.add_parser("shelve", help="shelve alerts for a limited time")
    alert_shelve.add_argument("ids", type=int, nargs="+")
    alert_shelve.add_argument("--reason", required=True)
    alert_shelve.add_argument(
        "--for",
        dest="duration",
        type=_duration,
        required=True,
        help="how long: e.g. 30m, 8h, 2d (at most PMP_ALERT_MAX_SHELVE_DAYS, default 7)",
    )
    alert_unshelve = alert_commands.add_parser("unshelve", help="end shelving early")
    alert_unshelve.add_argument("ids", type=int, nargs="+")
    matrix = alert_commands.add_parser("matrix", help="priority matrix (FR-ALM-04)")
    matrix_commands = matrix.add_subparsers(dest="matrix_command", required=True)
    matrix_commands.add_parser("show", help="criticality x severity -> priority")
    matrix_set = matrix_commands.add_parser("set", help="change one cell")
    matrix_set.add_argument("criticality", choices=["A", "B", "C"])
    matrix_set.add_argument("severity", choices=[s.value for s in Severity])
    matrix_set.add_argument("priority", choices=["P1", "P2", "P3", "P4"])

    health = commands.add_parser("health", help="health roll-up over the asset hierarchy")
    health_commands = health.add_subparsers(dest="health_command", required=True)
    health_tree_cmd = health_commands.add_parser(
        "tree", help="band, Health and counts for every asset (or one asset's subtree)"
    )
    health_tree_cmd.add_argument("asset", nargs="?", help="only this asset and below")

    library = commands.add_parser("library", help="the failure-mode library (UC-16)")
    library_commands = library.add_subparsers(dest="library_command", required=True)
    library_import = library_commands.add_parser(
        "import", help="save the modes of a library file (JSON); unchanged modes are skipped"
    )
    library_import.add_argument("file", type=Path)
    library_import.add_argument("--comment", default="imported", help="kept with each version")
    library_list = library_commands.add_parser("list", help="current failure modes")
    library_list.add_argument("--type", dest="asset_type", help="only this asset type")

    diagnose_cmd = commands.add_parser(
        "diagnose", help="failure-mode match scores for a model's latest cycle (UC-09 step 4)"
    )
    diagnose_cmd.add_argument("asset")
    diagnose_cmd.add_argument("--name", default="main", help="model name (main)")

    demo = commands.add_parser("demo", help="synthetic demo plant data (development and demos)")
    demo_commands = demo.add_subparsers(dest="demo_command", required=True)
    for name, text in (
        ("history", "generate and import 1-minute history for every registered tag"),
        ("replay", "play the OT gateway: send live samples to the ingestion API"),
    ):
        command = demo_commands.add_parser(name, help=text)
        command.add_argument("--seed", type=int, default=DEFAULT_SEED)
        command.add_argument(
            "--anchor", type=_date, help="the story's reference day (default: today, UTC)"
        )
    demo_history = demo_commands.choices["history"]
    demo_history.add_argument("--days", type=int, default=180, help="history length (180)")
    demo_replay = demo_commands.choices["replay"]
    demo_replay.add_argument("--key", required=True, help="API key with scope 'ingest'")
    demo_replay.add_argument("--url", default="http://127.0.0.1:8000")
    demo_replay.add_argument(
        "--from", dest="start", type=_when, help="start time: e.g. -6h, -30m, -2d or ISO 8601"
    )
    demo_replay.add_argument(
        "--speed", type=float, default=60.0, help="catch-up speed: minutes per second (60)"
    )
    demo_replay.add_argument("--minutes", type=int, help="stop after this many minutes")
    demo_models = demo_commands.add_parser(
        "models", help="create, train and deploy the demo models (skips models in service)"
    )
    demo_models.add_argument(
        "folder",
        nargs="?",
        type=Path,
        default=Path("../data/demo/models"),
        help="folder of model definition files (../data/demo/models)",
    )
    demo_score = demo_commands.add_parser(
        "score",
        help="score the last hours of data, oldest first, as the worker would have live",
    )
    demo_score.add_argument("--hours", type=float, default=24.0, help="how far back (24)")

    evaluate = commands.add_parser(
        "evaluate",
        help="AC-04: compare the alerts raised in a period with an event history (CSV)",
    )
    evaluate.add_argument(
        "events", type=Path, help="CSV: asset, start, end, description[, detectable]"
    )
    evaluate.add_argument("--days", type=float, default=30.0, help="period to evaluate (30)")
    evaluate.add_argument(
        "--anchor",
        type=_when,
        help="end of the period and the reference for relative event times "
        "(default: just after the newest sample)",
    )

    user = commands.add_parser("user", help="user accounts and roles (UC-17)")
    user_commands = user.add_subparsers(dest="user_command", required=True)
    roles_help = (
        "role, optionally scoped: viewer, analyst, maintenance, model_engineer, "
        "administrator; e.g. analyst@SITE-A (repeat for several)"
    )
    user_create = user_commands.add_parser("create", help="create a user (password prompted)")
    user_create.add_argument("username")
    user_create.add_argument("--name", default="", help="display name")
    user_create.add_argument("--email")
    user_create.add_argument(
        "--role", dest="roles", action="append", required=True, help=roles_help
    )
    user_commands.add_parser("list", help="list users with their roles")
    user_roles = user_commands.add_parser("set-roles", help="replace a user's roles")
    user_roles.add_argument("username")
    user_roles.add_argument("--role", dest="roles", action="append", required=True, help=roles_help)
    for name, text in (
        ("reset-password", "set a new password (prompted); unlocks the account, ends sessions"),
        ("deactivate", "a leaver: no sign-in, sessions end (the account is kept for the audit)"),
        ("activate", "allow a deactivated user to sign in again"),
    ):
        user_commands.add_parser(name, help=text).add_argument("username")

    audit = commands.add_parser("audit", help="search or export the audit trail (UC-19)")
    audit.add_argument("--from", dest="since", type=_when, help="e.g. -7d or ISO 8601")
    audit.add_argument("--to", dest="until", type=_when)
    audit.add_argument("--user", help="username")
    audit.add_argument("--entity", help="entity type, e.g. alert, model_version, user")
    audit.add_argument("--entity-id")
    audit.add_argument("--limit", type=int, default=50)
    audit.add_argument("--csv", type=Path, help="write a CSV file instead of printing")

    retention = commands.add_parser("retention", help="how long data is kept (NFR-DATA-01)")
    retention_commands = retention.add_subparsers(dest="retention_command", required=True)
    retention_commands.add_parser("show", help="the policy and the last run")
    retention_set = retention_commands.add_parser("set", help="change the policy")
    retention_set.add_argument("--raw-months", type=int, required=True)
    retention_set.add_argument("--aggregate-months", type=int, required=True)
    retention_commands.add_parser("run", help="apply it now (the worker does this daily)")

    apikey = commands.add_parser("apikey", help="machine API keys for the gateway (FR-SEC-02)")
    apikey_commands = apikey.add_subparsers(dest="apikey_command", required=True)
    create = apikey_commands.add_parser("create", help="issue a key (shown once)")
    create.add_argument("--name", required=True, help="who uses it, e.g. 'Site A gateway'")
    create.add_argument(
        "--scope", required=True, choices=[s.value for s in ApiKeyScope], help="what it may do"
    )
    apikey_commands.add_parser("list", help="list keys (never shows the secret)")
    revoke = apikey_commands.add_parser("revoke", help="revoke a key immediately")
    revoke.add_argument("id", type=int)
    rotate = apikey_commands.add_parser(
        "rotate", help="issue a replacement; revoke the old key once the gateway has switched"
    )
    rotate.add_argument("id", type=int)
    return parser


def _run_web(settings: Settings, args: argparse.Namespace) -> None:
    if not args.no_migrate:
        run_migrations(settings.database_url.get_secret_value())
    uvicorn.run(
        create_app(settings=settings),
        host=args.host or settings.web_host,
        port=args.port or settings.web_port,
        log_config=None,
    )


def _run_worker(settings: Settings) -> None:
    database = Database(settings.database_url.get_secret_value())
    registry = JobRegistry()
    uploads = Path(settings.artefact_dir) / "uploads"
    registry.register(BACKFILL_JOB, make_backfill_handler(database, uploads))
    registry.register(RETENTION_JOB, make_retention_handler(database))
    registry.register(
        TRAIN_JOB,
        make_training_handler(database, Path(settings.artefact_dir)),
        on_failed=make_training_failure_handler(database),
    )
    stop = threading.Event()
    scheduler = Scheduler(
        database, grace_s=settings.scoring_grace_s, retention_months=settings.retention_months
    )
    scheduler_thread = threading.Thread(
        target=scheduler.run_forever, args=(stop,), name="scoring-scheduler", daemon=True
    )

    def _request_stop(signum: int, _frame: FrameType | None) -> None:
        logger.info("Received signal %s, finishing the current job", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    scheduler_thread.start()
    try:
        Worker(database, registry).run_forever(stop)
    finally:
        stop.set()
        scheduler_thread.join(timeout=30)
        database.dispose()


def _run_registry_import(settings: Settings, args: argparse.Namespace) -> int:
    database = Database(settings.database_url.get_secret_value())
    report: ImportReport
    try:
        with database.session() as session:
            report = import_files(session, Actor.system(), args.files, dry_run=args.dry_run)
    except ImportFailedError as failure:  # raised inside the transaction, so nothing was written
        report = failure.report
    finally:
        database.dispose()
    print(report.summary())
    return 0 if report.ok else 1


def _parse_roles(session: Session, specs: Sequence[str]) -> list[RoleAssignment]:
    assignments = []
    for spec in specs:
        role_name, _, scope = spec.partition("@")
        try:
            role = Role(role_name.strip().lower())
        except ValueError:
            raise UserError(
                f"Unknown role {role_name!r}; use one of {', '.join(r.value for r in Role)}"
            ) from None
        scope_id = None
        if scope:
            asset = find_asset(session, scope.strip())
            if asset is None:
                raise UserError(f"Asset {scope!r} does not exist")
            scope_id = asset.id
        assignments.append(RoleAssignment(role, scope_id))
    return assignments


def _roles_text(session: Session, assignments: Sequence[RoleAssignment]) -> str:
    return ", ".join(
        a.role.label
        + (f" @ {get_asset_by_id(session, a.scope_asset_id).code}" if a.scope_asset_id else "")
        for a in assignments
    )


def _ask_password(username: str) -> str:
    first = getpass.getpass(f"New password for {username}: ")
    if getpass.getpass("Repeat it: ") != first:
        raise UserError("The passwords do not match")
    return first


def _run_user(settings: Settings, args: argparse.Namespace) -> int:
    database = Database(settings.database_url.get_secret_value())
    actor = Actor.system()  # the command line is trusted: whoever runs it runs the server
    try:
        with database.session() as session:
            command = args.user_command
            if command == "create":
                assignments = _parse_roles(session, args.roles)
                password = _ask_password(args.username)
                view = create_user(
                    session,
                    actor,
                    username=args.username,
                    display_name=args.name,
                    password=password,
                    assignments=assignments,
                    email=args.email,
                )
                print(f"Created {view.username}: {_roles_text(session, view.assignments)}")
            elif command == "list":
                for u in list_users(session, actor):
                    state = "active" if u.active else "deactivated"
                    if u.locked_until and u.locked_until > datetime.now(UTC):
                        state = f"locked until {u.locked_until:%H:%M} UTC"
                    last = f"{u.last_login_at:%Y-%m-%d %H:%M}" if u.last_login_at else "never"
                    print(
                        f"{u.id:>4}  {u.username:<20} {u.display_name:<24} {state:<20} "
                        f"last sign-in {last:<16}  {_roles_text(session, u.assignments)}"
                    )
            elif command == "set-roles":
                view = set_roles(session, actor, args.username, _parse_roles(session, args.roles))
                print(f"{view.username}: {_roles_text(session, view.assignments)}")
            elif command == "reset-password":
                reset_password(session, actor, args.username, _ask_password(args.username))
                print(f"Password reset for {args.username}; their sessions have ended.")
            else:
                view = set_active(session, actor, args.username, command == "activate")
                print(f"{view.username} is now {'active' if view.active else 'deactivated'}.")
    except UserError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        database.dispose()
    return 0


def _run_audit(settings: Settings, args: argparse.Namespace) -> int:
    database = Database(settings.database_url.get_secret_value())
    try:
        with database.session() as session:
            user_id = get_user(session, args.user).id if args.user else None
            filters = AuditFilter(args.since, args.until, user_id, args.entity, args.entity_id)
            limit = 10_000 if args.csv else args.limit
            rows = query_audit(session, Actor.system(), filters, limit=limit)
        if args.csv:
            args.csv.write_text(audit_csv(rows), encoding="utf-8")
            print(f"Wrote {len(rows)} entries to {args.csv}")
            return 0
        for r in rows:
            who = r.user_id if r.user_id is not None else r.actor_type
            print(f"{r.ts:%Y-%m-%d %H:%M:%S}  {r.entity}:{r.entity_id:<10} {r.action:<16} by {who}")
        return 0
    except UserError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        database.dispose()


def _run_retention(settings: Settings, args: argparse.Namespace) -> int:
    database = Database(settings.database_url.get_secret_value())
    default = settings.retention_months
    try:
        with database.session() as session:
            if args.retention_command == "set":
                set_retention(
                    session,
                    Actor.system(),
                    raw_months=args.raw_months,
                    aggregate_months=args.aggregate_months,
                    default_raw_months=default,
                )
            elif args.retention_command == "run":
                print(apply_retention(session, datetime.now(UTC), default, RETAINED_TABLES))
            policy = get_retention(session, default)
        last = f"{policy.last_run_at:%Y-%m-%d %H:%M} UTC" if policy.last_run_at else "never"
        print(
            f"Raw data kept {policy.raw_months} months, hourly aggregates "
            f"{policy.aggregate_months} months. Last run: {last}"
        )
        return 0
    except RetentionError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        database.dispose()


def _run_apikey(settings: Settings, args: argparse.Namespace) -> int:
    database = Database(settings.database_url.get_secret_value())
    actor = Actor.system()
    try:
        with database.session() as session:
            if args.apikey_command == "create":
                issued = issue_api_key(
                    session, actor, name=args.name, scope=ApiKeyScope(args.scope)
                )
                print(f"Key {issued.id} ({args.scope}). Copy it now; it is not shown again:")
                print(issued.key)
            elif args.apikey_command == "rotate":
                issued = rotate_api_key(session, actor, args.id)
                print(f"Replacement key {issued.id}. Copy it now; it is not shown again:")
                print(issued.key)
                print(f"Revoke key {args.id} once the gateway uses the new key.")
            elif args.apikey_command == "revoke":
                revoke_api_key(session, actor, args.id)
                print(f"Key {args.id} revoked.")
            else:
                for key in list_api_keys(session, actor):
                    status = "active" if key.active else f"revoked {key.revoked_at:%Y-%m-%d}"
                    used = f"{key.last_used_at:%Y-%m-%d %H:%M}" if key.last_used_at else "never"
                    print(
                        f"{key.id:>4}  pmp_{key.prefix}_…  {key.scope.value:<12} "
                        f"{status:<20} last used {used}  {key.name}"
                    )
    except ApiKeyError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        database.dispose()
    return 0


def _run_grace(settings: Settings, args: argparse.Namespace) -> int:
    seconds = None if args.seconds == "default" else args.seconds
    if seconds is not None and not seconds.isdigit():
        print(f"Error: give whole seconds (0 to {MAX_GRACE_S}) or 'default'", file=sys.stderr)
        return 2
    database = Database(settings.database_url.get_secret_value())
    try:
        with database.session() as session:
            set_source_grace(
                session, Actor.system(), args.source, int(seconds) if seconds else None
            )
    except IngestError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        database.dispose()
    shown = f"{seconds} s" if seconds is not None else f"the default ({settings.scoring_grace_s} s)"
    print(f"Scoring now waits {shown} for {args.source}'s late samples.")
    return 0


def _run_backfill(settings: Settings, args: argparse.Namespace) -> int:
    database = Database(settings.database_url.get_secret_value())
    options = BackfillOptions(
        source=args.source,
        layout=Layout(args.layout) if args.layout else None,
        mode=OverlapMode(args.mode),
        naive_as_utc=args.naive_as_utc,
    )
    last = [-10.0]

    def show(percent: float) -> None:
        if percent - last[0] >= 5 or percent >= 100:
            last[0] = percent
            print(f"  {percent:5.1f} %", flush=True)

    try:
        report = run_backfill(database, args.file, options, preview=args.preview, on_progress=show)
    except BackfillError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        database.dispose()
    print(report.summary())
    return 0 if report.reconciles else 1


def _pairs(items: Sequence[str]) -> dict[str, str]:
    pairs = {}
    for item in items:
        name, sep, value = item.partition("=")
        if not sep or not name:
            raise DataQualityError(f"Expected NAME=VALUE, got {item!r}")
        pairs[name.strip()] = value.strip()
    return pairs


def _find_tag(tags: Sequence[TagView], name: str, source: str | None) -> TagView:
    found = [t for t in tags if t.source_name == name and (source is None or t.source == source)]
    if not found:
        raise DataQualityError(f"Tag {name!r} is not registered")
    if len(found) > 1:
        raise DataQualityError(f"Tag {name!r} exists in several sources; add --source")
    return found[0]


def _scope(tags: Sequence[TagView], args: argparse.Namespace) -> RuleScope:
    if args.role:
        asset_type, sep, role = args.role.partition("/")
        if not sep:
            raise DataQualityError("--role must be TYPE/ROLE, e.g. centrifugal_pump/motor_current")
        return RuleScope.role(asset_type, role)
    if args.tag:
        return RuleScope.tag(_find_tag(tags, args.tag, args.source).id)
    return RuleScope.everywhere()


def _run_dq(settings: Settings, args: argparse.Namespace) -> int:
    database = Database(settings.database_url.get_secret_value())
    try:
        with database.session() as session:
            references = deployed_references(session, ModelCache())
            if args.dq_command == "status":
                # evaluated with the deployed models' training statistics, as the scoring
                # cycle does, and shown without storing: the scheduler owns stored statuses
                tags = list_tags(session, args.asset)
                at = args.at or datetime.now(UTC)
                states = evaluate_sensors(
                    session, at, [t.id for t in tags], references=references, store=False
                )
                stored = {v.tag_id: v for v in get_sensor_statuses(session, states)}
                print(f"Sensor status at {at:%Y-%m-%d %H:%M:%S} UTC")
                for t in sorted(tags, key=lambda t: (t.asset_code, t.source_name)):
                    state = states[t.id]
                    known = stored.get(t.id)
                    since = (
                        f"since {known.since:%Y-%m-%d %H:%M}"
                        if known and (known.status, known.rule) == (state.status, state.rule)
                        else ""
                    )
                    print(
                        f"{t.asset_code:<10} {t.source_name:<28} {state.status.value:<22} "
                        f"{state.rule.value:<18} {state.effect.value:<16} {since}"
                    )
                return 0

            tags = list_tags(session)
            scope = _scope(tags, args)
            current = get_rule_set(session, scope)
            if args.dq_command == "show":
                print(f"Scope: {scope}  (version {current.version or 'none saved'})")
                print(f"Overrides: {current.overrides or 'none'}")
                for older in list_rule_versions(session, scope)[1:]:
                    when = f"{older.created_at:%Y-%m-%d %H:%M}" if older.created_at else ""
                    print(f"  v{older.version} {when}  {older.overrides}")
                if scope.kind == "tag":
                    effective = effective_params(session, int(scope.key))
                else:  # defaults, then global, then this role's overrides
                    base = get_rule_set(session, RuleScope.everywhere()).overrides
                    effective = DEFAULTS.with_overrides(base).with_overrides(current.overrides)
                print("Effective parameters:")
                for name, value in effective.as_dict().items():
                    print(f"  {name:<20} {value}")
                return 0

            proposed = dict(current.overrides)
            for name, value in _pairs(args.params).items():
                if value.lower() == "default":
                    proposed.pop(name, None)
                else:
                    proposed[name] = value
            report = preview_rules(session, scope, proposed, days=args.days, references=references)
            print(report.summary())
            if args.dq_command == "preview":
                return 0
            if report.warning and not args.yes:
                print("Not saved. Re-run with --yes to save anyway.", file=sys.stderr)
                return 1
            saved = save_rule_set(session, Actor.system(), scope, proposed, args.comment)
            print(f"Saved {scope} as version {saved.version}: {saved.overrides or 'no overrides'}")
            return 0
    except DataQualityError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        database.dispose()


def _run_algorithms() -> int:
    detectors = available_detectors()
    for info in detectors:
        state = "enabled" if info.enabled else "REFUSED"
        print(f"{info.name:<16} {info.version:<10} {state:<9} {info.source}")
        for failure in info.failures:
            print(f"    - {failure}")
    return 0 if all(d.enabled for d in detectors) else 1


def _print_model(session: Session, model: ModelView) -> None:
    latest = model.latest
    print(f"{model.asset_code} / {model.name}  (model {model.id})  {model.description}")
    for v in model.versions:
        note = f"  error: {v.error}" if v.error else ""
        if v.metrics:
            note += (
                f"  trained on {v.metrics['training_retained']:,} of "
                f"{v.metrics['training_cycles']:,} cycles, validated on "
                f"{v.metrics['validation_retained']:,}"
            )
        created = f"{v.created_at:%Y-%m-%d %H:%M}"
        print(f"  v{v.version}  {v.status.value:<10} {v.algorithm:<8} {created}{note}")
    if latest.artefact_path:
        print(f"Artefact: {latest.artefact_path}  (SHA-256 {latest.artefact_sha256})")
        floored = (latest.metrics or {}).get("floored_sensors") or []
        if floored:
            print(f"  scale floored for: {', '.join(floored)}")
    print(f"Version {latest.version} definition:")
    required = sum(s.required for s in latest.sensors)
    print(f"  sensors ({len(latest.sensors)}, {required} required):")
    for s in latest.sensors:
        print(f"    {'*' if s.required else ' '} {s.source_name:<20} {s.description}")
    for i, period in enumerate(latest.training_periods, start=1):
        print(f"  training period {i}: {period}")
    if latest.validation_period:
        print(f"  validation period:  {latest.validation_period}")
    for text in latest.mode_filters:
        print(f"  operating mode:     {text}")
    names = {s.tag_id: s.source_name for s in latest.sensors}
    print("Alert rules:")
    states = rule_states(session, model.id)
    for rule in list_alert_rules(session, model.id):
        spec = rule.spec
        target = (
            "DI (%)"
            if spec.kind is RuleKind.DI
            else f"|z| {names.get(spec.tag_id or 0, spec.tag_id)}"
        )
        print(
            f"  {target:<24} warning {spec.warning:g}  alert {spec.alert:g}  "
            f"{spec.persistence_n} of {spec.persistence_m}  on-delay {spec.on_delay_s} s  "
            f"deadband {spec.deadband:.0%} for {spec.clear_cycles}  "
            f"[{states.get(rule.id, AlertState.NORMAL).value}]"
            + ("" if spec.enabled else "  (disabled)")
        )


def _run_model(settings: Settings, args: argparse.Namespace) -> int:
    database = Database(settings.database_url.get_secret_value())
    actor = Actor.system()
    try:
        with database.session() as session:
            if args.model_command == "create":
                try:
                    data = json.loads(args.file.read_text(encoding="utf-8"))
                except (OSError, ValueError) as error:
                    raise ModelError(f"Cannot read {args.file}: {error}") from None
                definition = definition_from_dict(data, datetime.now(UTC))
                model = save_draft(session, actor, definition)
                set_alert_rules(
                    session,
                    actor,
                    model.id,
                    rules_from_dict(
                        data.get("alert_rules"),
                        {x.source_name: x.tag_id for x in model.latest.sensors},
                    ),
                )
                version = model.latest.version
                print(f"Saved {model.asset_code} / {model.name} version {version} (Draft)")
                _print_model(session, model)
            elif args.model_command == "show":
                _print_model(session, get_model(session, args.asset, args.name))
            elif args.model_command == "train":
                view, job_id = start_training(
                    session, actor, args.asset, args.name, queue=not args.now
                )
                if job_id is not None:
                    print(
                        f"Version {view.version} is Training: job {job_id} queued. "
                        "The worker runs it (`make worker`)."
                    )
            elif args.model_command in {a.value for a in Action}:
                model = change_status(
                    session,
                    actor,
                    args.asset,
                    args.name,
                    Action(args.model_command),
                    version=args.version,
                    deploy_checks=(require_di_rule,),
                )
                print(f"{args.model_command.capitalize()}: done.")
                _print_model(session, model)
            else:
                for m in list_models(session, args.asset):
                    v = m.latest
                    print(
                        f"{m.id:>4}  {m.asset_code:<10} {m.name:<20} v{v.version} "
                        f"{v.status.value:<10} {len(v.sensors)} sensors  {v.algorithm}"
                    )
        if args.model_command == "train" and args.now:
            print(f"Training {args.asset} / {args.name} ...", flush=True)
            result = run_training(database, view.id, Path(settings.artefact_dir))
            with database.session() as session:
                _print_model(session, get_model(session, args.asset, args.name))
            return 0 if result.get("status") == "Validated" else 1
    except (ModelError, AlertRuleError) as error:
        message = "\n  ".join(getattr(error, "problems", None) or [str(error)])
        print(f"Error: {message}", file=sys.stderr)
        return 1
    finally:
        database.dispose()
    return 0


def _print_cycle(result: CycleResult) -> None:
    output = result.output
    head = f"{result.ts:%Y-%m-%d %H:%M:%S} UTC  {result.status.value}"
    if output is not None and output.di is not None:
        head += f"  DI {output.di:.1f} %  Health {output.health:.0f}  {output.band.value}"
    if result.reason:
        head += f"  ({result.reason})"
    if not result.written:
        head += "  [already scored; nothing written]"
    print(head)
    if output is not None and output.di is not None:
        print("  top contributors:")
        for s in output.top_contributors():
            print(
                f"    {s.tag:<20} {(s.contribution or 0):6.1%}  z {s.z:+.1f}  "
                f"actual {s.actual:.2f}  predicted {s.predicted:.2f}"
            )
        excluded = [s.tag for s in output.sensors if not s.usable]
        if excluded:
            print(f"  excluded: {', '.join(excluded)}")
    for change in result.alerts:
        _print_change(change)


def _print_change(change: AlertChanged) -> None:
    previous = change.previous.value if change.previous else "-"
    print(
        f"  alert {change.alert_id}: {change.action}  {previous} -> {change.state.value}  "
        f"{change.severity.value} {change.priority}"
    )


def _alert_line(alert: AlertView, models: dict[int, str], tags: dict[int, str]) -> str:
    what = "DI" if alert.tag_id is None else tags.get(alert.tag_id, f"tag {alert.tag_id}")
    condition = "active" if alert.condition_active else "cleared"
    shelved = f"  until {alert.shelved_until:%Y-%m-%d %H:%M}" if alert.shelved_until else ""
    return (
        f"{alert.id:>5}  {alert.priority or '—':<2}  {alert.severity.value:<7} "
        f"{alert.state.value:<24} "
        f"{models.get(alert.model_id, alert.model_id)!s:<20} {what:<18} "
        f"raised {alert.raised_at:%Y-%m-%d %H:%M}  {condition}{shelved}"
    )


_BAND_ORDER = (Band.ALERT, Band.WATCH, Band.UNKNOWN, Band.HEALTHY)


def _print_node(node: NodeHealth, depth: int = 0) -> None:
    band = node.band.value if node.band else "No model"
    health = f"{node.health:3.0f}" if node.health is not None else "  -"
    counts = " · ".join(f"{b.value} {node.counts[b]}" for b in _BAND_ORDER if node.counts.get(b))
    label = f"{'  ' * depth}{node.code}"
    worst = f"  worst: {node.worst}" if node.children and node.worst else ""
    print(f"{label:<28} {band:<14} {health}  {counts}{worst}")
    for model in node.models:
        detail = model.why or (model.status.value if model.status else "")
        print(f"{'  ' * (depth + 1)}- model {model.name}: {model.band.value} ({detail})")
    for child in node.children:
        _print_node(child, depth + 1)


def _run_health(settings: Settings, args: argparse.Namespace) -> int:
    database = Database(settings.database_url.get_secret_value())
    try:
        with database.session() as session:
            roots = health_tree(session, args.asset)
        if not roots:
            print("No assets.")
        print(f"{'Asset':<28} {'Band':<14} Health  Assets by band")
        for root in roots:
            _print_node(root)
        return 0
    except RegistryError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        database.dispose()


def _run_alert(settings: Settings, args: argparse.Namespace) -> int:
    database = Database(settings.database_url.get_secret_value())
    actor = Actor.system()
    now = datetime.now(UTC)
    try:
        with database.session() as session:
            command = args.alert_command
            changes: list[AlertChanged] = []
            if command in ("list", "show"):
                models = {m.id: f"{m.asset_code} / {m.name}" for m in list_models(session)}
                alerts = (
                    list_alerts(session, open_only=not args.all)
                    if command == "list"
                    else [get_alert(session, args.id)]
                )
                tag_ids = {a.tag_id for a in alerts if a.tag_id is not None}
                tags = {t.id: t.source_name for t in get_tags(session, tag_ids)}
                if not alerts:
                    print("No open alerts.")
                for a in alerts:
                    print(_alert_line(a, models, tags))
                if command == "show":
                    print(json.dumps(alerts[0].trace, indent=2, default=str))
                    for e in alert_history(session, args.id):
                        print(
                            f"  {e.ts:%Y-%m-%d %H:%M:%S}  {e.action:<14} "
                            f"{e.from_state or '-'} -> {e.to_state}  {e.comment or ''}"
                        )
            elif command == "ack":
                changes = acknowledge(session, actor, args.ids, now, args.comment)
            elif command == "shelve":
                changes = shelve(
                    session,
                    actor,
                    args.ids,
                    now,
                    reason=args.reason,
                    duration=args.duration,
                    max_duration=timedelta(days=settings.alert_max_shelve_days),
                )
            elif command == "unshelve":
                changes = unshelve(session, actor, args.ids, now)
            elif args.matrix_command == "set":
                changes = set_priority(
                    session, actor, args.criticality, Severity(args.severity), args.priority, now
                )
                print(f"{args.criticality} / {args.severity} -> {args.priority}")
            else:
                matrix = get_priority_matrix(session)
                print("Criticality  Warning  Alert")
                for c in ("A", "B", "C"):
                    warning = matrix.get((c, Severity.WARNING), "-")
                    alarm = matrix.get((c, Severity.ALERT), "-")
                    print(f"{c:<12} {warning:<8} {alarm}")
            for change in changes:
                _print_change(change)
    except AlertError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        database.dispose()
    return 0


def _run_score(settings: Settings, args: argparse.Namespace) -> int:
    database = Database(settings.database_url.get_secret_value())
    try:
        with database.session() as session:
            if args.score_command == "status":
                names = {m.id: f"{m.asset_code} / {m.name}" for m in list_models(session)}
                for v in get_runtime_statuses(session):
                    score = (
                        f"DI {v.di:5.1f} %  Health {v.health:3.0f}"
                        if v.di is not None and v.health is not None
                        else " " * 23
                    )
                    last = f"{v.last_cycle:%Y-%m-%d %H:%M}" if v.last_cycle else "-"
                    print(
                        f"{names.get(v.model_id, v.model_id)!s:<20} {v.status.value:<22} "
                        f"{v.band.value:<8} {score}  last cycle {last}  {v.reason or ''}"
                    )
                return 0
            model = get_model(session, args.asset, args.name)
            active = [a for a in list_active_versions(session) if a.model_id == model.id]
        if not active:
            print(f"Error: {args.asset} / {args.name} has no version in service", file=sys.stderr)
            return 1
        if args.at:
            at = latest_due_cycle(args.at, active[0].cycle_s, 0)
        else:
            at = latest_due_cycle(datetime.now(UTC), active[0].cycle_s, settings.scoring_grace_s)
        for result in score_models(database, at, active, ModelCache()):
            _print_cycle(result)
        return 0
    except ModelError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        database.dispose()


def _run_library(settings: Settings, args: argparse.Namespace) -> int:
    database = Database(settings.database_url.get_secret_value())
    try:
        with database.session() as session:
            if args.library_command == "import":
                try:
                    data = json.loads(args.file.read_text(encoding="utf-8"))
                    modes = import_library(session, Actor.system(), data, args.comment)
                except (OSError, ValueError) as error:  # LibraryError is a ValueError
                    print(f"Error: {error}", file=sys.stderr)
                    return 1
                print(f"{len(modes)} failure modes in the library:")
            else:
                modes = list_modes(session, args.asset_type)
            for m in modes:
                symptoms = ", ".join(
                    f"{s.role} {s.direction.value} x{s.weight:g}" for s in m.spec.symptoms
                )
                print(f"  {m.asset_type:<26} {m.spec.name:<32} v{m.version}  {symptoms}")
        return 0
    finally:
        database.dispose()


def _run_diagnose(settings: Settings, args: argparse.Namespace) -> int:
    database = Database(settings.database_url.get_secret_value())
    try:
        with database.session() as session:
            model = find_model(session, args.asset, args.name)
            if model is None:
                print(f"Error: no model {args.asset} / {args.name}", file=sys.stderr)
                return 1
            result = diagnose(session, model.id)
        if result.at is None:
            print("Not scored yet.")
            return 0
        print(f"{result.asset_code} ({result.asset_type}) at {result.at:%Y-%m-%d %H:%M} UTC")
        print("Relative match, not probability (UCS §6.7.2):")
        for d in result.modes:
            score = (
                "insufficient evidence"
                if d.match.insufficient or d.match.score is None
                else f"{d.match.score:5.1f} %"
            )
            print(f"  {d.mode.spec.name:<34} {score}")
        return 0
    finally:
        database.dispose()


def _run_evaluate(settings: Settings, args: argparse.Namespace) -> int:
    database = Database(settings.database_url.get_secret_value())
    try:
        anchor = args.anchor
        if anchor is None:
            newest = latest_sample_time(database)
            if newest is None:
                print("Error: no data to evaluate", file=sys.stderr)
                return 1
            anchor = newest.replace(second=0, microsecond=0) + timedelta(minutes=1)
        try:
            events = read_events(args.events, anchor)
        except EvaluationError as error:
            print(f"Error: {error}", file=sys.stderr)
            return 1
        with database.session() as session:
            result = evaluate(session, events, anchor - timedelta(days=args.days), anchor)
        for line in format_report(result):
            print(line)
        return 0
    finally:
        database.dispose()


def _run_demo_story(settings: Settings, args: argparse.Namespace) -> int:
    database = Database(settings.database_url.get_secret_value())
    try:
        if args.demo_command == "models":
            files = sorted(args.folder.glob("*.json"))
            if not files:
                print(f"Error: no .json model definitions in {args.folder}", file=sys.stderr)
                return 1
            print(f"Demo models from {args.folder} ({len(files)} definitions):")
            results = setup_models(database, files, Path(settings.artefact_dir))
            return 0 if all(r.ok for r in results) else 1
        if args.hours <= 0:
            print("Error: --hours must be more than 0", file=sys.stderr)
            return 1
        print(f"Scoring the last {args.hours:g} h of data, oldest cycle first:")
        result = back_score(database, args.hours)
        if result.start is None:
            print("Nothing to score: no model in service or no data (run `pmp demo models`).")
            return 1
        print(
            f"Done: {result.cycles} cycles ({result.start:%Y-%m-%d %H:%M} to "
            f"{result.end:%H:%M} UTC), {result.scored} model cycles written, "
            f"{result.alert_changes} alert changes."
        )
        return 0
    finally:
        database.dispose()


def _run_demo(settings: Settings, args: argparse.Namespace) -> int:
    if args.demo_command in {"models", "score"}:
        return _run_demo_story(settings, args)
    database = Database(settings.database_url.get_secret_value())
    try:
        with database.session() as session:
            tags = demo_tags(session)
        if not tags:
            print(
                "No tags registered. Import the demo registry first:\n"
                "  uv run pmp registry import ../data/demo/registry/registry.xlsx",
                file=sys.stderr,
            )
            return 1
        simulator = PlantSimulator(tags, seed=args.seed, anchor=args.anchor)
        print(
            f"SYNTHETIC demo data: {len(tags)} tags, seed {args.seed}, "
            f"story anchored at {simulator.anchor:%Y-%m-%d %H:%M} UTC"
        )
        if args.demo_command == "history":
            last: dict[str, float] = {}

            def show(stage: str, percent: float) -> None:
                if percent - last.get(stage, -100) >= 10 or percent >= 100:
                    last[stage] = percent
                    print(f"  {stage:<22} {percent:5.1f} %", flush=True)

            reports = load_history(
                database,
                simulator,
                days=args.days,
                work_dir=Path(settings.artefact_dir) / "demo",
                on_progress=show,
            )
            for source, report in reports.items():
                print(f"[{source}]")
                print(report.summary())
            return 0 if all(r.reconciles for r in reports.values()) else 1
        stats = replay(
            simulator,
            url=args.url.rstrip("/") + "/api/v1/ingest/samples",
            key=args.key,
            start=args.start,
            speed=args.speed,
            minutes=args.minutes,
        )
        print(
            f"Replay finished: {stats.minutes} minutes, {stats.accepted} samples accepted, "
            f"{stats.rejected} rejected, {stats.failed_batches} failed batches"
        )
        return 0 if stats.failed_batches == 0 else 1
    except urllib.error.URLError as error:  # refused, not an HTTP error response
        print(
            f"Error: cannot reach {args.url} ({error.reason}). Is the web role running "
            "(`make web` in another terminal)?",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("Stopped.")
        return 0
    finally:
        database.dispose()


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(_attach_relative_times(sys.argv[1:] if argv is None else argv))
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    if args.command == "migrate":
        run_migrations(settings.database_url.get_secret_value())
    elif args.command == "web":
        _run_web(settings, args)
    elif args.command == "worker":
        _run_worker(settings)
    elif args.command == "registry" and args.registry_command == "import":
        sys.exit(_run_registry_import(settings, args))
    elif args.command == "ingest" and args.ingest_command == "backfill":
        sys.exit(_run_backfill(settings, args))
    elif args.command == "ingest" and args.ingest_command == "grace":
        sys.exit(_run_grace(settings, args))
    elif args.command == "dq":
        sys.exit(_run_dq(settings, args))
    elif args.command == "algorithms":
        sys.exit(_run_algorithms())
    elif args.command == "model":
        sys.exit(_run_model(settings, args))
    elif args.command == "score":
        sys.exit(_run_score(settings, args))
    elif args.command == "health":
        sys.exit(_run_health(settings, args))
    elif args.command == "alert":
        sys.exit(_run_alert(settings, args))
    elif args.command == "demo":
        sys.exit(_run_demo(settings, args))
    elif args.command == "retention":
        sys.exit(_run_retention(settings, args))
    elif args.command == "library":
        sys.exit(_run_library(settings, args))
    elif args.command == "diagnose":
        sys.exit(_run_diagnose(settings, args))
    elif args.command == "evaluate":
        sys.exit(_run_evaluate(settings, args))
    elif args.command == "audit":
        sys.exit(_run_audit(settings, args))
    elif args.command == "user":
        sys.exit(_run_user(settings, args))
    elif args.command == "apikey":
        sys.exit(_run_apikey(settings, args))


if __name__ == "__main__":
    main()
