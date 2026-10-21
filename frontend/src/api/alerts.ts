import { api } from "./client";
import type { Page } from "./assets";
import type { Alert, AlertDetail, PriorityCell } from "./types";

export interface AlertFilter {
  asset?: string;
  modelId?: number;
  includeClosed?: boolean;
  limit?: number;
  states?: readonly string[];
  priorities?: readonly string[];
  severities?: readonly string[];
  kind?: "di" | "sensor";
  cursor?: string | null;
}

function alertQuery(filter: AlertFilter): string {
  const params = new URLSearchParams();
  if (filter.asset) params.set("asset", filter.asset);
  if (filter.modelId) params.set("model_id", String(filter.modelId));
  if (filter.includeClosed) params.set("include_closed", "true");
  if (filter.kind) params.set("kind", filter.kind);
  if (filter.cursor) params.set("cursor", filter.cursor);
  params.set("limit", String(filter.limit ?? 100));
  for (const s of filter.states ?? []) params.append("state", s);
  for (const p of filter.priorities ?? []) params.append("priority", p);
  for (const s of filter.severities ?? []) params.append("severity", s);
  return params.toString();
}

/** One page of the alert list (unacknowledged first, then priority, then age). */
export function fetchAlerts(filter: AlertFilter = {}, signal?: AbortSignal): Promise<Page<Alert>> {
  return api<Page<Alert>>(`/alerts?${alertQuery(filter)}`, { signal });
}

/** Every alert matching the filter, page by page (at most `max`). */
export async function fetchAllAlerts(
  filter: AlertFilter,
  signal?: AbortSignal,
  max = 10_000,
): Promise<{ items: Alert[]; truncated: boolean }> {
  const items: Alert[] = [];
  let cursor: string | null = null;
  do {
    const page: Page<Alert> = await fetchAlerts({ ...filter, cursor, limit: 1000 }, signal);
    items.push(...page.items);
    cursor = page.next_cursor;
  } while (cursor && items.length < max);
  return { items, truncated: cursor !== null };
}

export function fetchAlert(id: number, signal?: AbortSignal): Promise<AlertDetail> {
  return api<AlertDetail>(`/alerts/${id}`, { signal });
}

export function fetchPriorityMatrix(signal?: AbortSignal): Promise<PriorityCell[]> {
  return api<PriorityCell[]>("/priority-matrix", { signal });
}

/** Shelve alerts for `minutes` (UCS §6.6: reason mandatory, limited time). */
export function shelveAlerts(
  ids: readonly number[],
  reason: string,
  minutes: number,
): Promise<Alert[]> {
  return api<Alert[]>("/alerts/shelve", { method: "POST", body: { ids, reason, minutes } });
}

export function unshelveAlerts(ids: readonly number[]): Promise<Alert[]> {
  return api<Alert[]>("/alerts/unshelve", { method: "POST", body: { ids } });
}

/** Acknowledge alerts (ISA-18.2: explicit; viewing never acknowledges). */
export function acknowledgeAlerts(
  ids: readonly number[],
  comment: string | null,
): Promise<Alert[]> {
  return api<Alert[]>("/alerts/ack", { method: "POST", body: { ids, comment: comment || null } });
}
