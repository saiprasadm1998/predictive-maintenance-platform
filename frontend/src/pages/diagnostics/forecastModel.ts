import type { Forecast, Urgency } from "../../api/forecasts";
import type { User } from "../../api/auth";
import type { Point, TrendData } from "../../components/trendOptions";

const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const STEPS = 60;

/** ARC §9.2: analysts and model engineers run forecasts. */
export function canRunForecast(user: User | null | undefined): boolean {
  return !!user?.roles.some((r) => r.role === "analyst" || r.role === "model_engineer");
}

export const WINDOW_CHOICES = [1, 3, 7, 14, 30] as const;

/** "18 h", "6.5 d": a median time to threshold. */
export function medianText(hours: number): string {
  if (hours < 1) return "now";
  if (hours < 48) return `${Math.round(hours)} h`;
  const days = hours / 24;
  return `${days < 10 ? days.toFixed(1) : Math.round(days)} d`;
}

/** "4–9 d", "6–30 h", "more than 40 d": an 80 % interval (wireframes 02 and 04). */
export function intervalText(lower: number, upper: number | null): string {
  if (upper === null) return `more than ${medianText(lower)}`;
  if (upper < 48) return `${Math.round(lower)}–${Math.round(upper)} h`;
  return `${Math.floor(lower / 24)}–${Math.ceil(upper / 24)} d`;
}

/** The alert list's "Forecast urgency" ("High · 4–9 d"); "—" without a forecast. */
export function urgencyText(
  urgency: Urgency | null | undefined,
  lower: number | null | undefined,
  upper: number | null | undefined,
): string {
  if (!urgency) return "—";
  if (urgency === "None" || lower === null || lower === undefined) return "None";
  return `${urgency} · ${intervalText(lower, upper ?? null)}`;
}

/** The asset summary's line: "High · 4–9 d to DI alert limit 25". */
export function forecastBrief(f: Forecast): string {
  if (!f.valid || f.lower_h === null) return "None · no trend to threshold";
  return `${urgencyText(f.urgency, f.lower_h, f.upper_h)} to ${targetText(f)} ${thresholdText(f)}`;
}

/** The fitted curve at `t` days from the forecast time. */
export function fitValue(fit: Forecast["fit"], t: number): number {
  const p = fit.params;
  if (fit.method === "exponential") return p.c! + p.a! * Math.exp(p.b! * t);
  return p.a! + p.b! * t;
}

/** "DI", "TI-1012", "TI-1012 residual". */
export function targetText(f: Pick<Forecast, "target" | "tag">): string {
  if (f.target === "di") return "DI";
  return f.target === "residual" ? `${f.tag ?? "sensor"} residual` : (f.tag ?? "sensor");
}

/** "alert limit 25", "warning limit 15", "90". */
export function thresholdText(f: Pick<Forecast, "threshold_kind" | "threshold">): string {
  const value = Number(f.threshold.toPrecision(6)).toString();
  return f.threshold_kind === "custom" ? value : `${f.threshold_kind} limit ${value}`;
}

/** "method: exponential fit, 7-day window, R² 0.91" (PDS §4.4). */
export function methodText(f: Forecast): string {
  const window = `${Number(f.window_days.toFixed(1))}-day window`;
  if (!f.fit.method) return window;
  const r2 = f.fit.r2 === null ? "" : `, R² ${f.fit.r2.toFixed(2)}`;
  return `method: ${f.fit.method} fit, ${window}${r2}`;
}

/**
 * The forecast chart (PDS §3.4 "Forecast", ForecastChart): the fitted history, a dashed
 * projection from the forecast time to beyond the median crossing, the 80 % interval as a
 * cone (the projection run faster to cross at the interval's lower bound and slower to
 * cross at its upper bound), the threshold and a line at the median crossing.
 */
export function forecastChart(f: Forecast): { data: TrendData; from: number; to: number } {
  const at = Date.parse(f.at);
  const actual: Point[] = f.series.map((p) => [Date.parse(p.ts), p.value]);
  const from = actual.length ? actual[0]![0] : at - f.window_days * DAY;
  const limits =
    f.threshold_kind === "warning" ? { warning: [f.threshold] } : { alert: [f.threshold] };
  if (!f.valid || f.median_h === null || !f.fit.method) {
    return { data: { actual, limits }, from, to: at };
  }
  const median = f.median_h;
  const horizon = Math.max(median * 1.3, Math.min(f.upper_h ?? median * 2, median * 2), 1);
  const now = fitValue(f.fit, 0);
  const span = Math.abs(f.threshold - now) || 1;
  const up = f.direction === "up";
  const clamp = (v: number) =>
    up
      ? Math.min(Math.max(v, now - span), f.threshold + span / 2)
      : Math.max(Math.min(v, now + span), f.threshold - span / 2);
  const predicted: Point[] = [];
  const band: [number, number, number][] = [];
  for (let i = 0; i <= STEPS; i += 1) {
    const hours = (horizon * i) / STEPS;
    const t = at + hours * HOUR;
    const days = hours / 24;
    predicted.push([t, clamp(fitValue(f.fit, days))]);
    const fast =
      f.lower_h && f.lower_h > 0 ? fitValue(f.fit, (days * median) / f.lower_h) : f.threshold;
    const slow = f.upper_h ? fitValue(f.fit, (days * median) / f.upper_h) : now;
    const a = clamp(fast);
    const b = clamp(slow);
    band.push([t, Math.min(a, b), Math.max(a, b)]);
  }
  return {
    data: {
      actual,
      predicted,
      band,
      limits,
      markers: [{ t: at + median * HOUR, name: "Median crossing" }],
    },
    from,
    to: at + horizon * HOUR,
  };
}
