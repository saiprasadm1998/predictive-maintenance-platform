/** Pure helpers behind SCR-04 diagnostics and SCR-12 the library (plan 8.2). */

import type { Direction, ModeMatch } from "../../api/diagnostics";
import type { User } from "../../api/auth";

export const NOT_PROBABILITY =
  "Score = weighted agreement of the observed residual signature with the mode's defined symptoms; relative ranking, not a calibrated probability.";

/** "78 %" or "insufficient evidence" (UCS §6.7.2). */
export function scoreText(m: ModeMatch): string {
  if (m.insufficient_evidence || m.score === null) return "insufficient evidence";
  return `${Math.round(m.score)} %`;
}

export const ARROW: Record<Direction, string> = { up: "↑", down: "↓", any: "any" };

/** "+3.1", "−2.0", "—". */
export function signed(z: number | null): string {
  if (z === null) return "—";
  return `${z >= 0 ? "+" : "−"}${Math.abs(z).toFixed(1)}`;
}

/** Sparkline points in a w × h box, scores 0 to 100; gaps where there is no score. */
export function sparkPaths(trend: readonly { score: number | null }[], w = 80, h = 18): string[] {
  if (trend.length < 2) return [];
  const step = w / (trend.length - 1);
  const paths: string[] = [];
  let current: string[] = [];
  trend.forEach((p, i) => {
    if (p.score === null) {
      if (current.length > 1) paths.push(current.join(" "));
      current = [];
      return;
    }
    const y = h - (Math.max(0, Math.min(100, p.score)) / 100) * h;
    current.push(`${(i * step).toFixed(1)},${y.toFixed(1)}`);
  });
  if (current.length > 1) paths.push(current.join(" "));
  return paths;
}

/** ARC §9.2: model engineers maintain the failure-mode library. */
export function canEditLibrary(user: User | null | undefined): boolean {
  return !!user?.roles.some((r) => r.role === "model_engineer");
}

/** A code from a name: "Thrust bearing wear" → "thrust_bearing_wear". */
export function codeFrom(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 64);
}
