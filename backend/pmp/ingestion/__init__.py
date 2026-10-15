"""ingestion.

Transport adapters (REST now, MQTT optional later), validation, tag mapping, quality
mapping, idempotent sample writes and ingestion statistics.

Public interface of the module (ARC-001 §4.1). Other modules may import only
what this file exports, never the module's internal files.
"""

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
    IngestResult,
    Rejection,
    SampleRow,
    SourceStats,
    UnmappedTagView,
    count_samples,
    ingest_batch,
    list_unmapped_tags,
    promote_unmapped_tag,
    read_samples,
    server_now,
    source_stats,
    write_samples,
)

__all__ = [
    "MAX_BODY_BYTES",
    "MAX_SAMPLES",
    "BatchIn",
    "IngestResult",
    "Quality",
    "RejectReason",
    "Rejection",
    "SampleIn",
    "SampleRow",
    "SourceStats",
    "UnmappedTagView",
    "count_samples",
    "ingest_batch",
    "list_unmapped_tags",
    "map_quality",
    "promote_unmapped_tag",
    "read_samples",
    "server_now",
    "source_stats",
    "write_samples",
]
