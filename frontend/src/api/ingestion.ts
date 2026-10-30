import { api } from "./client";

/** One gateway source on the ingestion-health screen (FR-ING-07). */
export interface SourceHealth {
  source: string;
  last_received_at: string | null;
  last_sample_ts: string | null;
  accepted_total: number;
  rejected_total: number;
  per_minute: number;
  interval_s: number;
  tags: number;
  stale: boolean;
  stale_after_s: number;
  skew_s: number | null;
  skewed: boolean;
}

export interface TagHealth {
  tag_id: number;
  source: string;
  source_name: string;
  asset_code: string;
  interval_s: number;
  last_sample_ts: string | null;
  stale: boolean;
}

export interface IngestionHealth {
  checked_at: string;
  sources: SourceHealth[];
  tags: TagHealth[];
}

export function fetchIngestionHealth(signal?: AbortSignal): Promise<IngestionHealth> {
  return api<IngestionHealth>("/ingest/health", { signal });
}
