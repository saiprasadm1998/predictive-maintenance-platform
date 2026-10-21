import { api } from "./client";
import type { Page } from "./assets";
import type { Alert } from "./types";

export interface AlertFilter {
  asset?: string;
  modelId?: number;
  includeClosed?: boolean;
  limit?: number;
}

/** One page of the alert list (unacknowledged first, then priority, then age). */
export function fetchAlerts(filter: AlertFilter = {}, signal?: AbortSignal): Promise<Page<Alert>> {
  return api<Page<Alert>>("/alerts", {
    query: {
      asset: filter.asset,
      model_id: filter.modelId,
      include_closed: filter.includeClosed || undefined,
      limit: filter.limit ?? 100,
    },
    signal,
  });
}

/** Acknowledge alerts (ISA-18.2: explicit; viewing never acknowledges). */
export function acknowledgeAlerts(
  ids: readonly number[],
  comment: string | null,
): Promise<Alert[]> {
  return api<Alert[]>("/alerts/ack", { method: "POST", body: { ids, comment: comment || null } });
}
