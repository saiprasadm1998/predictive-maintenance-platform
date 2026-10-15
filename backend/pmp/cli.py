"""Command line: `pmp web | worker | migrate | registry | apikey` (ARC-001 §10.1, §12).

One image runs both roles. `pmp registry import` loads registry files until the REST
endpoints arrive (5.2). `pmp backup` is added in sub-phase 9.1.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from types import FrameType

import uvicorn

from pmp.api import create_app
from pmp.core import (
    Actor,
    ApiKeyError,
    ApiKeyScope,
    Database,
    JobRegistry,
    Settings,
    Worker,
    configure_logging,
    get_settings,
    issue_api_key,
    list_api_keys,
    revoke_api_key,
    rotate_api_key,
    run_migrations,
)
from pmp.registry import ImportFailedError, ImportReport, import_files

logger = logging.getLogger(__name__)


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
    registry = JobRegistry()  # modules register their job handlers here from phase 1
    stop = threading.Event()

    def _request_stop(signum: int, _frame: FrameType | None) -> None:
        logger.info("Received signal %s, finishing the current job", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    try:
        Worker(database, registry).run_forever(stop)
    finally:
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
                for key in list_api_keys(session):
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


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
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
    elif args.command == "apikey":
        sys.exit(_run_apikey(settings, args))


if __name__ == "__main__":
    main()
