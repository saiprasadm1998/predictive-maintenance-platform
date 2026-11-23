import type { Pt } from "./Chart";

/** A downsampled series as points: raw values as they are, buckets as min then max. */
export function trendPoints(
  trend: {
    ts: string[];
    raw: boolean;
    bucket_s: number | null;
    min: Record<string, (number | null)[]>;
    max: Record<string, (number | null)[]>;
  },
  series: string,
): Pt[] {
  const lo = trend.min[series] ?? [];
  const hi = trend.max[series] ?? [];
  const out: Pt[] = [];
  trend.ts.forEach((ts, i) => {
    const t = Date.parse(ts);
    if (trend.raw || trend.bucket_s === null) {
      out.push([t, hi[i] ?? null]);
    } else {
      out.push([t, lo[i] ?? null], [t + (trend.bucket_s * 1000) / 2, hi[i] ?? null]);
    }
  });
  return out;
}
