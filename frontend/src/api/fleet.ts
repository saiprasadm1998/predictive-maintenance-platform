import { api } from "./client";

export interface FleetKpis {
  assets_by_band: Record<string, number>;
  open_alerts: Record<string, number>;
  unacknowledged_alerts: Record<string, number>;
  sensors_by_status: Record<string, number>;
  models_by_status: Record<string, number>;
  stale_models: number[];
  last_cycle: string | null;
  open_cases?: number; // cases not closed or cancelled (8.4)
}

export function fetchFleetKpis(signal?: AbortSignal): Promise<FleetKpis> {
  return api<FleetKpis>("/fleet/kpis", { signal });
}
