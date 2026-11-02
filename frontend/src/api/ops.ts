import { api } from "./client";

/** A built-in operational alert (ARC §10.3), for administrators. */
export interface OpsAlert {
  kind: "source_stale" | "cycle_overrun" | "scheduler_silent" | "job_queue" | "backup_failed";
  severity: "warning" | "critical";
  text: string;
  since: string | null;
  link: string | null;
}

export function fetchOpsAlerts(signal?: AbortSignal): Promise<OpsAlert[]> {
  return api<OpsAlert[]>("/ops/alerts", { signal });
}
