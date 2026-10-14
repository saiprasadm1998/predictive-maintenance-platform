"""ingestion.

Transport adapters (REST, MQTT), validation, tag mapping, quality mapping, idempotent sample
writes and ingestion statistics.

Public interface of the module (ARC-001 §4.1). Other modules may import only
what this file exports, never the module's internal files.
"""
