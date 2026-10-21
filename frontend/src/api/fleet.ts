import { api } from "./client";

export interface FleetKpis {
  assets_by_band: Record<string, number>;
  open_alerts: Record<string, number>;
  unacknowledged_alerts: Record<string, number>;
  sensors_by_status: Record<string, number>;
  models_by_status: Record<string, number>;
  stale_models: number[];
  last_cycle: string | null;
}

export function fetchFleetKpis(signal?: AbortSignal): Promise<FleetKpis> {
  return api<FleetKpis>("/fleet/kpis", { signal });
}
