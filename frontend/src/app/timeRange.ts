import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * The global time range (PDS §2.2): it applies to every trend on the page and lives in the
 * URL (`range=7d`, or `from` and `to` in ISO 8601), so a link opens the same period.
 */

export const PRESETS = ["1h", "24h", "7d", "30d", "90d"] as const;
export type Preset = (typeof PRESETS)[number];
export const DEFAULT_PRESET: Preset = "7d";

const PRESET_MS: Record<Preset, number> = {
  "1h": 3_600_000,
  "24h": 86_400_000,
  "7d": 7 * 86_400_000,
  "30d": 30 * 86_400_000,
  "90d": 90 * 86_400_000,
};

export const SLIDE_MS = 60_000;

export const PRESET_LABELS: Record<Preset, string> = {
  "1h": "Last 1 hour",
  "24h": "Last 24 hours",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  "90d": "Last 90 days",
};

export interface TimeRange {
  preset: Preset | null; // null: a custom from/to
  from: Date;
  to: Date;
}

function isPreset(value: string | null): value is Preset {
  return value !== null && (PRESETS as readonly string[]).includes(value);
}

function parseDate(value: string | null): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Read the range from URL parameters; anything missing or invalid falls back to 7 days. */
export function resolveTimeRange(params: URLSearchParams, now: Date = new Date()): TimeRange {
  const from = parseDate(params.get("from"));
  const to = parseDate(params.get("to"));
  if (from && to && from < to) return { preset: null, from, to };
  const raw = params.get("range");
  const preset = isPreset(raw) ? raw : DEFAULT_PRESET;
  return { preset, from: new Date(now.getTime() - PRESET_MS[preset]), to: now };
}

/** URL parameters that carry the time range onto another screen's link. */
export function timeRangeParams(params: URLSearchParams): URLSearchParams {
  const kept = new URLSearchParams();
  for (const key of ["range", "from", "to"]) {
    const value = params.get(key);
    if (value) kept.set(key, value);
  }
  return kept;
}

export function useTimeRange() {
  const [params, setParams] = useSearchParams();
  // A preset ("last 7 days") slides with the clock once a minute, the scoring cycle, so new
  // scores stay in view; a custom from/to stays where it was put.
  const sliding = !(params.get("from") && params.get("to"));
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!sliding) return;
    const timer = window.setInterval(() => setTick((t) => t + 1), SLIDE_MS);
    return () => window.clearInterval(timer);
  }, [sliding]);
  // tick: a new "now" each minute
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const range = useMemo(() => resolveTimeRange(params), [params, tick]);
  const setPreset = useCallback(
    (preset: Preset) =>
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          next.delete("from");
          next.delete("to");
          next.set("range", preset);
          return next;
        },
        { replace: false },
      ),
    [setParams],
  );
  const setCustom = useCallback(
    (from: Date, to: Date) =>
      setParams((current) => {
        const next = new URLSearchParams(current);
        next.delete("range");
        next.set("from", from.toISOString());
        next.set("to", to.toISOString());
        return next;
      }),
    [setParams],
  );
  return { range, setPreset, setCustom };
}

/** The time zone times are shown in (PDS §3.3); a user setting replaces this later. */
export function displayTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}
