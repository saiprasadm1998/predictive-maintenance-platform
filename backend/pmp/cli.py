"""Command line: `pmp web | worker | migrate | registry | ingest | dq | algorithms | model |
score | demo | apikey`.

See ARC-001 §10.1 and §12.

One image runs both roles. `pmp registry import` and `pmp dq` stand in for the REST
endpoints (5.2) and screens (6.6) until they arrive. `pmp backup` is added in sub-phase 9.1.
"""

from __future__ import annotations

import argparse
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
    DEFAULT_SENSOR_ALERT,
    DEFAULT_SENSOR_WARNING,
    AlertRuleError,
    AlertRuleSpec,
    RuleKind,
    list_alert_rules,
    require_di_rule,
    set_alert_rules,
)
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
from pmp.ingestion import (
    BACKFILL_JOB,
    BackfillError,
    BackfillOptions,
    Layout,
    OverlapMode,
    make_backfill_handler,
    run_backfill,
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
    get_model,
    list_active_versions,
    list_models,
    make_training_handler,
    run_training,
    save_draft,
    start_training,
)
from pmp.registry import ImportFailedError, ImportReport, TagView, import_files, list_tags
from pmp.scoring import (
    CycleResult,
    Scheduler,
    get_runtime_statuses,
    latest_due_cycle,
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
    registry.register(TRAIN_JOB, make_training_handler(database, Path(settings.artefact_dir)))
    stop = threading.Event()
    scheduler = Scheduler(database, grace_s=settings.scoring_grace_s)
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
            if args.dq_command == "status":
                tags = list_tags(session, args.asset)
                at = args.at or datetime.now(UTC)
                evaluate_sensors(session, at, [t.id for t in tags])
                print(f"Sensor status at {at:%Y-%m-%d %H:%M:%S} UTC")
                for v in get_sensor_statuses(session, [t.id for t in tags]):
                    print(
                        f"{v.asset_code:<10} {v.source_name:<28} {v.status.value:<22} "
                        f"{v.rule.value:<18} {v.effect.value:<16} since {v.since:%Y-%m-%d %H:%M}"
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
            report = preview_rules(session, scope, proposed, days=args.days)
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


def _rules_from_dict(raw: object, model: ModelView) -> list[AlertRuleSpec]:
    """The alert_rules part of a model definition file."""
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise AlertRuleError("alert_rules must be an object")
    sensor_ids = {s.source_name: s.tag_id for s in model.latest.sensors}
    options = (
        "persistence_n",
        "persistence_m",
        "on_delay_s",
        "deadband",
        "clear_cycles",
        "enabled",
    )

    def extra(rule: dict[str, object]) -> dict[str, object]:
        return {k: rule[k] for k in options if k in rule}

    rules: list[AlertRuleSpec] = []
    try:
        if raw.get("di") is not None:
            di = raw["di"]
            rules.append(
                AlertRuleSpec(
                    RuleKind.DI,
                    float(di["warning"]),
                    float(di["alert"]),
                    **extra(di),  # type: ignore[arg-type]
                )
            )
        for rule in raw.get("sensors", []):
            name = str(rule["tag"])
            if name not in sensor_ids:
                raise AlertRuleError(f"Sensor rule on {name}, which is not a model sensor")
            rules.append(
                AlertRuleSpec(
                    RuleKind.SENSOR,
                    float(rule.get("warning", DEFAULT_SENSOR_WARNING)),
                    float(rule.get("alert", DEFAULT_SENSOR_ALERT)),
                    tag_id=sensor_ids[name],
                    **extra(rule),  # type: ignore[arg-type]
                )
            )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, AlertRuleError):
            raise
        raise AlertRuleError(f"alert_rules is malformed: {error}") from None
    return rules


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
            f"deadband {spec.deadband:.0%} for {spec.clear_cycles}"
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
                    session, actor, model.id, _rules_from_dict(data.get("alert_rules"), model)
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


def _run_demo(settings: Settings, args: argparse.Namespace) -> int:
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
    elif args.command == "dq":
        sys.exit(_run_dq(settings, args))
    elif args.command == "algorithms":
        sys.exit(_run_algorithms())
    elif args.command == "model":
        sys.exit(_run_model(settings, args))
    elif args.command == "score":
        sys.exit(_run_score(settings, args))
    elif args.command == "demo":
        sys.exit(_run_demo(settings, args))
    elif args.command == "apikey":
        sys.exit(_run_apikey(settings, args))


if __name__ == "__main__":
    main()
