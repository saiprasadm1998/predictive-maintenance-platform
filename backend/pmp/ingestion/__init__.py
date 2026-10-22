"""ingestion.

Transport adapters (REST now, MQTT optional later), validation, tag mapping, quality
mapping, idempotent sample writes and ingestion statistics.

Public interface of the module (ARC-001 §4.1). Other modules may import only
what this file exports, never the module's internal files.
"""

from pmp.ingestion.backfill import (
    BACKFILL_JOB,
    BackfillError,
    BackfillOptions,
    BackfillReport,
    Layout,
    OverlapMode,
    check_file,
    make_backfill_handler,
    run_backfill,
)
from pmp.ingestion.domain import (
    MAX_BODY_BYTES,
    MAX_SAMPLES,
    BatchIn,
    Quality,
    RejectReason,
    SampleIn,
    map_quality,
)
from pmp.ingestion.service import (
    MAX_GRACE_S,
    IngestError,
    IngestResult,
    Rejection,
    SampleRow,
    SourceStats,
    UnmappedTagView,
    count_samples,
    ingest_batch,
    list_unmapped_tags,
    promote_unmapped_tag,
    read_last_samples,
    read_last_samples_many,
    read_samples,
    server_now,
    set_source_grace,
    source_graces,
    source_stats,
    write_samples,
)

__all__ = [
    "BACKFILL_JOB",
    "MAX_BODY_BYTES",
    "MAX_GRACE_S",
    "MAX_SAMPLES",
    "BackfillError",
    "BackfillOptions",
    "BackfillReport",
    "BatchIn",
    "IngestError",
    "IngestResult",
    "Layout",
    "OverlapMode",
    "Quality",
    "RejectReason",
    "Rejection",
    "SampleIn",
    "SampleRow",
    "SourceStats",
    "UnmappedTagView",
    "check_file",
    "count_samples",
    "ingest_batch",
    "list_unmapped_tags",
    "make_backfill_handler",
    "map_quality",
    "promote_unmapped_tag",
    "read_last_samples",
    "read_last_samples_many",
    "read_samples",
    "run_backfill",
    "server_now",
    "set_source_grace",
    "source_graces",
    "source_stats",
    "write_samples",
]
