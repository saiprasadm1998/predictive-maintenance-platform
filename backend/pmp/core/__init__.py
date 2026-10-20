"""core.

Shared kernel: configuration, database sessions, migrations, security, RBAC, audit, event bus,
job queue, scheduler, logging and metrics.

Public interface of the module (ARC-001 §4.1). Other modules may import only
what this file exports, never the module's internal files.
"""

from pmp.core.apikeys import (
    ApiKeyError,
    ApiKeyScope,
    ApiKeyView,
    IssuedKey,
    issue_api_key,
    list_api_keys,
    revoke_api_key,
    rotate_api_key,
    verify_api_key,
)
from pmp.core.audit import Actor, ActorType, AuditLog, audit_change, record_audit
from pmp.core.config import LogFormat, Settings, get_settings
from pmp.core.db import (
    Base,
    Database,
    LockKey,
    advisory_lock,
    holds_advisory_lock,
    lock_for_transaction,
    try_advisory_lock,
)
from pmp.core.events import EVENT_CHANNEL, Event, EventBus, notify
from pmp.core.jobs import (
    Job,
    JobHandler,
    JobRegistry,
    JobStatus,
    JobStatusView,
    Worker,
    claim,
    complete,
    enqueue,
    fail,
    fail_expired,
    get_job,
    heartbeat,
    queue_depth,
    report_progress,
)
from pmp.core.logging import configure_logging, log_context, request_id_var, user_id_var
from pmp.core.migrate import run_migrations

__all__ = [
    "EVENT_CHANNEL",
    "Actor",
    "ActorType",
    "ApiKeyError",
    "ApiKeyScope",
    "ApiKeyView",
    "AuditLog",
    "Base",
    "Database",
    "Event",
    "EventBus",
    "IssuedKey",
    "Job",
    "JobHandler",
    "JobRegistry",
    "JobStatus",
    "JobStatusView",
    "LockKey",
    "LogFormat",
    "Settings",
    "Worker",
    "advisory_lock",
    "audit_change",
    "claim",
    "complete",
    "configure_logging",
    "enqueue",
    "fail",
    "fail_expired",
    "get_job",
    "get_settings",
    "heartbeat",
    "holds_advisory_lock",
    "issue_api_key",
    "list_api_keys",
    "lock_for_transaction",
    "log_context",
    "notify",
    "queue_depth",
    "record_audit",
    "report_progress",
    "request_id_var",
    "revoke_api_key",
    "rotate_api_key",
    "run_migrations",
    "try_advisory_lock",
    "user_id_var",
    "verify_api_key",
]
