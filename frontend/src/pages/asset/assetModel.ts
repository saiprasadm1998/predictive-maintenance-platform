/** Pure helpers behind asset analysis (SCR-03). */

import type {
  Alert,
  ModelDetail,
  SensorNow,
  SensorTrend,
  StatusPeriod,
  Trend,
} from "../../api/types";
import type { Point, TrendData } from "../../components/trendOptions";

const PRIORITY_ORDER = ["P1", "P2", "P3", "P4"];

export interface Contributor {
  sensor: SensorNow;
  share: number; // 0..1 of the DI
  direction: "up" | "down" | null;
}

/** "Top contributors now": sensors used in the latest cycle, by their share of the DI. */
export function topContributors(sensors: readonly SensorNow[], limit = 5): Contributor[] {
  return sensors
    .filter((s) => s.used !== false && s.contribution !== null && s.contribution > 0)
    .sort((a, b) => (b.contribution ?? 0) - (a.contribution ?? 0))
    .slice(0, limit)
    .map((sensor) => ({
      sensor,
      share: sensor.contribution ?? 0,
      direction: sensor.z === null || sensor.z === 0 ? null : sensor.z > 0 ? "up" : "down",
    }));
}

/** The sensor table: largest deviation first; sensors without a z last. */
export function sensorOrder(sensors: readonly SensorNow[]): SensorNow[] {
  const size = (s: SensorNow) => (s.z === null ? -1 : Math.abs(s.z));
  return [...sensors].sort((a, b) => size(b) - size(a));
}

/** "TI-1012 DE bearing temp." from source name K101.TI1012.PV and its description. */
export function sensorLabel(sensor: { source_name: string; description: string }): string {
  const tag = sensor.source_name.replace(/^[^.]+\./, "").replace(/\.PV$/, "");
  const pretty = tag.replace(/^([A-Z]+)(\d)/, "$1-$2");
  if (!sensor.description) return pretty;
  const description = sensor.description.replace(new RegExp(`^${pretty}\\s*`), "");
  return `${pretty} ${description}`;
}

/**
 * A downsampled series as a line (PDS §3.4 density): raw cycles as they are; buckets as
 * their minimum then maximum, so a spike inside a bucket still shows.
 */
export function linePoints(trend: Trend, series: string): Point[] {
  const lo = trend.min[series] ?? [];
  const hi = trend.max[series] ?? [];
  const points: Point[] = [];
  trend.ts.forEach((ts, i) => {
    const t = Date.parse(ts);
    if (trend.raw || trend.bucket_s === null) {
      points.push([t, hi[i] ?? null]);
      return;
    }
    const half = (trend.bucket_s * 1000) / 2;
    const low = lo[i] ?? null;
    const high = hi[i] ?? null;
    points.push([t, low], [t + half, high]);
  });
  return points;
}

/** One sensor's chart data: actual, predicted, and the expected band ± warning × σ. */
export function sensorChartData(
  trend: SensorTrend,
  sensor: SensorNow | undefined,
  alerts: TrendData["alerts"] = [],
): TrendData {
  const actual = linePoints(trend, "actual");
  const predicted = linePoints(trend, "predicted");
  const width = sensor?.sigma ? sensor.warning * sensor.sigma : null;
  const band =
    width === null
      ? undefined
      : predicted
          .filter((p): p is [number, number] => p[1] !== null)
          .map(([t, v]) => [t, v - width, v + width] as [number, number, number]);
  const excluded = (trend.unused ?? []).map((u) => ({
    from: Date.parse(u.start),
    to: Date.parse(u.end) + 60_000, // the last unused cycle covers its minute
    reason: `not used in scoring (${u.status}${u.rule ? `, ${u.rule.replace(/_/g, " ")}` : ""})`,
  }));
  return { actual, predicted, band, alerts, excluded };
}

/** Alert bars under the time axis: from raise to close (or until now). */
export function alertPeriods(
  alerts: readonly Alert[],
  now: number = Date.now(),
): TrendData["alerts"] {
  // While the condition was active: raise to clear, or until now while it still is.
  return alerts.map((a) => {
    const end = a.cleared_at ?? a.closed_at;
    return { from: Date.parse(a.raised_at), to: end ? Date.parse(end) : now, severity: a.severity };
  });
}

/** Shaded columns: when the model was not scoring normally, with the reason on hover. */
export function excludedPeriods(
  periods: readonly StatusPeriod[],
  runtime: ModelDetail["runtime"],
  rangeEnd: number,
): NonNullable<TrendData["excluded"]> {
  const out = periods.map((p) => ({
    from: Date.parse(p.start),
    to: Math.max(Date.parse(p.end), Date.parse(p.start) + 60_000),
    reason: p.reason ? `${p.status}: ${p.reason}` : p.status,
  }));
  // Paused or out of service: everything since then is greyed (PDS §4.3 states).
  if (runtime && (runtime.status === "Paused" || runtime.status === "Out of service")) {
    out.push({ from: Date.parse(runtime.since), to: rangeEnd, reason: runtime.status });
  }
  return out;
}

/** The asset's most urgent open alert, for the summary card ("P1 · active · unack"). */
export function worstAlert(alerts: readonly Alert[]): Alert | null {
  const open = alerts.filter((a) => !a.closed_at && a.state !== "Normal");
  open.sort(
    (a, b) =>
      rank(a.priority) - rank(b.priority) ||
      Number(needsAck(b)) - Number(needsAck(a)) ||
      b.raised_at.localeCompare(a.raised_at),
  );
  return open[0] ?? null;
}

function rank(priority: string | null): number {
  const i = PRIORITY_ORDER.indexOf(priority ?? "");
  return i < 0 ? 99 : i;
}

export function needsAck(alert: Alert): boolean {
  return alert.state === "Active-Unacknowledged" || alert.state === "RTN-Unacknowledged";
}

export function alertSummary(alert: Alert): string {
  const state: Record<string, string> = {
    "Active-Unacknowledged": "active · unack",
    "Active-Acknowledged": "active · ack",
    "RTN-Unacknowledged": "RTN · unack",
    Shelved: "shelved",
    "Out of service": "out of service",
  };
  return `${alert.priority ?? "—"} · ${state[alert.state] ?? alert.state}`;
}

/** The window an alert link opens on: from half a day before it was raised until it
 * cleared (plus a margin) or now. */
export function alertWindow(alert: Alert, now: number = Date.now()): { from: Date; to: Date } {
  const raised = Date.parse(alert.raised_at);
  const end = alert.closed_at ? Math.min(now, Date.parse(alert.closed_at) + 2 * 3_600_000) : now;
  return {
    from: new Date(raised - 12 * 3_600_000),
    to: new Date(Math.max(end, raised + 3_600_000)),
  };
}

/** The versions worth comparing: the ones that were ever in service. */
export function comparableVersions(model: ModelDetail): ModelDetail["versions"] {
  return model.versions.filter((v) =>
    ["Deployed", "Paused", "Superseded", "Retired"].includes(v.status),
  );
}
