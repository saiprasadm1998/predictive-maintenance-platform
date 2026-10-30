import type { IngestionHealth, SourceHealth, TagHealth } from "../../api/ingestion";

/** "45 s", "3 min", "2 h 5 min": how long ago, from the server's clock. */
export function ageText(iso: string | null, now: string): string {
  if (!iso) return "never";
  const seconds = Math.max(0, Math.round((Date.parse(now) - Date.parse(iso)) / 1000));
  if (seconds < 120) return `${seconds} s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 120) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ${minutes % 60} min ago`;
  return `${Math.floor(hours / 24)} d ago`;
}

/** The source's state in words, worst first: never sent, stale, clock skew, receiving. */
export function sourceState(s: SourceHealth): { text: string; warn: boolean } {
  if (!s.last_received_at) return { text: "Nothing received yet", warn: true };
  if (s.stale) return { text: `Stale: nothing for over ${s.stale_after_s} s`, warn: true };
  if (s.skewed) return { text: "Receiving · clock skew", warn: true };
  return { text: "Receiving", warn: false };
}

/** "+90 s": receive time minus newest sample time (ARC T-02, warned above 60 s). */
export function skewText(s: SourceHealth): string {
  if (s.skew_s === null) return "—";
  const sign = s.skew_s > 0 ? "+" : "";
  return `${sign}${Math.round(s.skew_s)} s`;
}

/** Tags in view: by source, optionally stale only, filtered by tag or asset text. */
export function tagsInView(
  health: IngestionHealth,
  source: string,
  staleOnly: boolean,
  text: string,
): TagHealth[] {
  const needle = text.trim().toLowerCase();
  return health.tags.filter(
    (t) =>
      (!source || t.source === source) &&
      (!staleOnly || t.stale) &&
      (!needle ||
        t.source_name.toLowerCase().includes(needle) ||
        t.asset_code.toLowerCase().includes(needle)),
  );
}
