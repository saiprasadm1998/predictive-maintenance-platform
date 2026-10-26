/** Pure helpers behind the alert list (SCR-02). */

import type { AlertFilter } from "../../api/alerts";
import type { Alert } from "../../api/types";

export const STATES = [
  ["Active-Unacknowledged", "Active · unack"],
  ["Active-Acknowledged", "Active · ack"],
  ["RTN-Unacknowledged", "RTN · unack"],
  ["Shelved", "Shelved"],
  ["Out of service", "Out of service"],
] as const;
export const PRIORITIES = ["P1", "P2", "P3", "P4"] as const;
export const SEVERITIES = ["Alert", "Warning"] as const;
/** The server's sort orders (default: unacknowledged first, then priority, then age). */
export const SORTS = [
  ["default", "Unacknowledged first"],
  ["newest", "Newest first"],
  ["oldest", "Oldest first"],
  ["priority", "Priority"],
  ["severity", "Severity"],
] as const;
export type Sort = (typeof SORTS)[number][0];
export const KINDS = [
  ["di", "Deviation Index"],
  ["sensor", "Sensor residual"],
] as const;

/** The list's filters, as they live in the URL (PDS §2.2: every state in the URL). */
export interface ListFilter {
  scope: string | null; // asset code
  states: string[];
  priorities: string[];
  severities: string[];
  kind: "di" | "sensor" | null;
  closed: boolean;
  sort: Sort;
}

const KEYS = ["scope", "state", "priority", "severity", "kind", "closed", "sort"] as const;

export function readFilter(params: URLSearchParams): ListFilter {
  const list = (key: string, allowed: readonly string[]) =>
    params.getAll(key).filter((v) => allowed.includes(v));
  const kind = params.get("kind");
  const sort = SORTS.find(([v]) => v === params.get("sort"))?.[0] ?? "default";
  return {
    scope: params.get("scope") || null,
    states: list(
      "state",
      STATES.map(([v]) => v),
    ),
    priorities: list("priority", PRIORITIES),
    severities: list("severity", SEVERITIES),
    kind: kind === "di" || kind === "sensor" ? kind : null,
    closed: params.get("closed") === "true",
    sort,
  };
}

/** Write a filter into URL parameters, keeping everything else (time range, alert). */
export function writeFilter(params: URLSearchParams, filter: ListFilter): URLSearchParams {
  const next = new URLSearchParams(params);
  KEYS.forEach((k) => next.delete(k));
  if (filter.scope) next.set("scope", filter.scope);
  filter.states.forEach((s) => next.append("state", s));
  filter.priorities.forEach((p) => next.append("priority", p));
  filter.severities.forEach((s) => next.append("severity", s));
  if (filter.kind) next.set("kind", filter.kind);
  if (filter.closed) next.set("closed", "true");
  if (filter.sort !== "default") next.set("sort", filter.sort);
  return next;
}

export function toApiFilter(filter: ListFilter): AlertFilter {
  return {
    asset: filter.scope ?? undefined,
    states: filter.states,
    priorities: filter.priorities,
    severities: filter.severities,
    kind: filter.kind ?? undefined,
    includeClosed: filter.closed,
    sort: filter.sort,
  };
}

/** "State: Active · unack, Shelved" or "State: All". */
export function menuLabel(
  name: string,
  chosen: readonly string[],
  labels?: ReadonlyMap<string, string>,
): string {
  if (!chosen.length) return `${name}: All`;
  return `${name}: ${chosen.map((c) => labels?.get(c) ?? c).join(", ")}`;
}

// ---- saved filters, per user (PDS §4.2) ----

export interface SavedFilter {
  name: string;
  query: string; // the filter's URL parameters
}

function storageKey(username: string): string {
  return `pmp.alertFilters.${username}`;
}

export function loadSaved(username: string): SavedFilter[] {
  try {
    const raw = localStorage.getItem(storageKey(username));
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? parsed.filter(
          (f): f is SavedFilter =>
            typeof f === "object" &&
            f !== null &&
            typeof (f as SavedFilter).name === "string" &&
            typeof (f as SavedFilter).query === "string",
        )
      : [];
  } catch {
    return [];
  }
}

export function storeSaved(username: string, filters: readonly SavedFilter[]): void {
  try {
    localStorage.setItem(storageKey(username), JSON.stringify(filters));
  } catch {
    // storage blocked: saved filters last for this page only
  }
}

/** Only the filter part of the URL, for saving. */
export function filterQuery(filter: ListFilter): string {
  return writeFilter(new URLSearchParams(), filter).toString();
}

// ---- live updates without re-sorting under the cursor (PDS §6) ----

export interface Shown {
  rows: Alert[]; // in the order the user is looking at, with fresh values
  incoming: number; // alerts not shown yet ("3 new alerts")
}

/**
 * Keep the order the user sees; take fresh values for those rows; count what is new.
 * `accepted` is the ID order last shown (null: show the fresh list as it comes).
 */
export function liveView(fresh: readonly Alert[], accepted: readonly number[] | null): Shown {
  if (accepted === null) return { rows: [...fresh], incoming: 0 };
  const byId = new Map(fresh.map((a) => [a.id, a]));
  const known = new Set(accepted);
  const rows = accepted.map((id) => byId.get(id)).filter((a): a is Alert => a !== undefined);
  const incoming = fresh.filter((a) => !known.has(a.id)).length;
  return { rows, incoming };
}

/** "5 of 5"; "—" while shelved or out of service, or without a rule memory. */
export function persistenceText(alert: Alert): string {
  if (alert.state === "Shelved" || alert.state === "Out of service") return "—";
  if (alert.persistence_n === null || alert.persistence_m === null) return "—";
  return `${alert.persistence_n} of ${alert.persistence_m}`;
}

/** "K-101 v3 · DI", "P-104A v1 · TI1044". */
export function modelText(alert: Alert): string {
  const rule =
    alert.kind === "di"
      ? "DI"
      : (alert.tag ?? "sensor").replace(/^[^.]+\./, "").replace(/\.PV$/, "");
  return `${alert.asset_code}${alert.version ? ` v${alert.version}` : ""} · ${rule}`;
}

const SHELVE_FOR: readonly (readonly [number, string])[] = [
  [60, "1 hour"],
  [4 * 60, "4 hours"],
  [8 * 60, "8 hours"],
  [24 * 60, "24 hours"],
  [3 * 24 * 60, "3 days"],
  [7 * 24 * 60, "7 days"],
  [14 * 24 * 60, "14 days"],
  [30 * 24 * 60, "30 days"],
];

/** The shelf lengths up to the configured maximum, the longest one marked. */
export function shelveChoices(maxDays: number): (readonly [number, string])[] {
  const max = maxDays * 24 * 60;
  const choices = SHELVE_FOR.filter(([m]) => m < max);
  return [...choices, [max, `${maxDays} day${maxDays === 1 ? "" : "s"} (the most allowed)`]];
}
/** What the selection allows (bulk actions are all or nothing on the server). */
export function allowed(selected: readonly Alert[]) {
  const any = selected.length > 0;
  return {
    ack:
      any &&
      selected.every(
        (a) => a.state === "Active-Unacknowledged" || a.state === "RTN-Unacknowledged",
      ),
    // UCS Figure 6: only an active alert can be shelved.
    shelve:
      any &&
      selected.every(
        (a) => a.state === "Active-Unacknowledged" || a.state === "Active-Acknowledged",
      ),
    unshelve: any && selected.every((a) => a.state === "Shelved"),
  };
}
