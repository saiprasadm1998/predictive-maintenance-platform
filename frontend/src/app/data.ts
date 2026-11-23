/** Shared reads, cached under the query keys the live event stream refreshes. */
import { useQuery } from "@tanstack/react-query";

import { fetchSensorHealth } from "../api/admin";
import { fetchAllAlerts } from "../api/alerts";
import { fetchCases } from "../api/cases";
import { fetchFleetKpis } from "../api/fleet";
import { fetchModels } from "../api/models";

/** Every alert that is not closed. */
export function useOpenAlerts() {
  return useQuery({
    queryKey: ["alerts", "open-all"],
    queryFn: async ({ signal }) => (await fetchAllAlerts({}, signal)).items,
  });
}

export function useModels() {
  return useQuery({ queryKey: ["models", "all"], queryFn: ({ signal }) => fetchModels(signal) });
}

export function useCases(openOnly = false) {
  return useQuery({
    queryKey: ["cases", openOnly ? "open" : "all"],
    queryFn: ({ signal }) => fetchCases({ open_only: openOnly }, signal),
  });
}

export function useSensorHealth() {
  return useQuery({
    queryKey: ["sensors", "health"],
    queryFn: ({ signal }) => fetchSensorHealth(signal),
  });
}

export function useKpis() {
  return useQuery({ queryKey: ["fleet", "kpis"], queryFn: ({ signal }) => fetchFleetKpis(signal) });
}

export const WINDOWS = [
  { value: "12h", label: "12 h", ms: 12 * 3_600_000 },
  { value: "24h", label: "24 h", ms: 24 * 3_600_000 },
  { value: "7d", label: "7 days", ms: 7 * 86_400_000 },
] as const;
export type WindowKey = (typeof WINDOWS)[number]["value"];

export function windowMs(key: string | null): number {
  return WINDOWS.find((w) => w.value === key)?.ms ?? 7 * 86_400_000;
}
