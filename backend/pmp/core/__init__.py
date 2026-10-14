"""core.

Shared kernel: configuration, database sessions, migrations, security, RBAC, audit, event bus,
job queue, scheduler, logging and metrics.

Public interface of the module (ARC-001 §4.1). Other modules may import only
what this file exports, never the module's internal files.
"""

from pmp.core.audit import ActorType, AuditLog, record_audit
from pmp.core.config import LogFormat, Settings, get_settings
from pmp.core.db import Base, Database, LockKey, advisory_lock, try_advisory_lock
from pmp.core.events import Event, EventBus
from pmp.core.jobs import (
    Job,
    JobHandler,
    JobRegistry,
    JobStatus,
    Worker,
    claim,
    complete,
    enqueue,
    fail,
    fail_expired,
    queue_depth,
)
from pmp.core.logging import configure_logging, log_context, request_id_var, user_id_var
from pmp.core.migrate import run_migrations

__all__ = [
    "ActorType",
    "AuditLog",
    "Base",
    "Database",
    "Event",
    "EventBus",
    "Job",
    "JobHandler",
    "JobRegistry",
    "JobStatus",
    "LockKey",
    "LogFormat",
    "Settings",
    "Worker",
    "advisory_lock",
    "claim",
    "complete",
    "configure_logging",
    "enqueue",
    "fail",
    "fail_expired",
    "get_settings",
    "log_context",
    "queue_depth",
    "record_audit",
    "request_id_var",
    "run_migrations",
    "try_advisory_lock",
    "user_id_var",
]
