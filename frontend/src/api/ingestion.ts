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

export interface Broker {
  configured: boolean;
  url: string | null;
  topic: string | null;
  connected: boolean;
  last_message_at: string | null;
  last_error: string | null;
  updated_at: string | null;
}

export interface IngestionHealth {
  checked_at: string;
  sources: SourceHealth[];
  tags: TagHealth[];
  broker: Broker;
  topic_prefix: string;
  accepted_24h: number;
  rejected_24h: number;
}

export interface Reject {
  received_at: string;
  source: string;
  transport: string;
  tag: string | null;
  sample_ts: string | null;
  value: number | null;
  reason: string;
  detail: string | null;
}

export function fetchRejects(signal?: AbortSignal): Promise<Reject[]> {
  return api<Reject[]>("/ingest/rejects", { signal });
}

export function testBroker(): Promise<{ ok: boolean; message: string }> {
  return api("/ingest/broker/test", { method: "POST" });
}

export function fetchIngestionHealth(signal?: AbortSignal): Promise<IngestionHealth> {
  return api<IngestionHealth>("/ingest/health", { signal });
}
