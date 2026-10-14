"""Command line: `pmp web | worker | migrate` (ARC-001 §10.1, §12).

One image runs both roles. `pmp backup` is added in sub-phase 9.1.
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
from collections.abc import Sequence
from types import FrameType

import uvicorn

from pmp.api import create_app
from pmp.core import (
    Database,
    JobRegistry,
    Settings,
    Worker,
    configure_logging,
    get_settings,
    run_migrations,
)

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
    return parser


def _run_web(settings: Settings, args: argparse.Namespace) -> None:
    if not args.no_migrate:
        run_migrations(settings.database_url.get_secret_value())
    uvicorn.run(
        create_app(),
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


if __name__ == "__main__":
    main()
