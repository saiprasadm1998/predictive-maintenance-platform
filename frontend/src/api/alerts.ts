import { api } from "./client";
import type { Page } from "./assets";
import type { Alert } from "./types";

export interface AlertFilter {
  asset?: string;
  includeClosed?: boolean;
  limit?: number;
}

/** One page of the alert list (unacknowledged first, then priority, then age). */
export function fetchAlerts(filter: AlertFilter = {}, signal?: AbortSignal): Promise<Page<Alert>> {
  return api<Page<Alert>>("/alerts", {
    query: {
      asset: filter.asset,
      include_closed: filter.includeClosed || undefined,
      limit: filter.limit ?? 100,
    },
    signal,
  });
}
