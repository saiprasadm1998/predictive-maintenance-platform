/** Pure helpers behind SCR-07 sensor health and the exclusion dialog (plan 8.1, UC-14). */

import type { SensorHealth } from "../../api/admin";
import type { User } from "../../api/auth";
import { NE107 } from "../../components/status";
import { RULE_LABELS } from "../admin/adminModel";

/** ARC §9.2: analysts and model engineers exclude and override sensors. */
export function canExclude(user: User | null | undefined): boolean {
  return !!user?.roles.some((r) => r.role === "analyst" || r.role === "model_engineer");
}

/** Rules an override can force to Good (the server's OVERRIDABLE). */
const OVERRIDABLE = new Set(["out_of_range", "flatline", "spike", "uncertain_quality"]);

export function canOverride(sensor: SensorHealth): boolean {
  return OVERRIDABLE.has(sensor.rule);
}

export const UNTIL_CHOICES: readonly (readonly [number, string])[] = [
  [8, "8 hours"],
  [24, "24 hours"],
  [72, "3 days"],
  [168, "7 days"],
  [720, "30 days"],
  [2160, "90 days (the most allowed)"],
];

/** "6 h", "3 d", "45 min": how long a status has held. */
export function heldFor(since: Date, now: Date = new Date()): string {
  const minutes = Math.max(0, Math.round((now.getTime() - since.getTime()) / 60_000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} h` : `${Math.round(hours / 24)} d`;
}

/** Wireframe 07's "Rule / reason": "Flatline 6 h", "Manual: calibration until 10-Oct". */
export function ruleOrReason(sensor: SensorHealth, now: Date = new Date()): string {
  const manual = sensor.exclusion;
  if (manual) {
    const until = new Date(manual.expires_at).toLocaleDateString("en-GB", {
      day: "2-digit",
      month: "short",
    });
    const what = manual.kind === "override" ? "Overridden" : "Manual";
    return `${what}: ${manual.reason} until ${until.replace(" ", "-")}`;
  }
  return `${RULE_LABELS[sensor.rule] ?? sensor.rule} ${heldFor(new Date(sensor.since), now)}`;
}

/** Wireframe 07's "Scoring use". */
export function scoringUse(sensor: SensorHealth): string {
  if (sensor.exclusion?.kind === "exclude") return "Manually excluded";
  if (sensor.exclusion?.kind === "override") return "In use (overridden)";
  if (sensor.effect === "used") return "In use";
  if (sensor.effect === "used_flagged") return "In use, flagged";
  if (sensor.effect === "sample_excluded") return "Sample excluded";
  return "Auto-excluded";
}

const ORDER = new Map([...NE107.filter((s) => s !== "Good"), "Good"].map((s, i) => [s, i]));

/** Non-Good sensors and overridden ones (an override must stay visible, UC-14), worst
 * first; `status` keeps one category. */
export function listed(sensors: readonly SensorHealth[], status: string | null): SensorHealth[] {
  return sensors
    .filter((s) =>
      status ? s.status === status : s.status !== "Good" || s.exclusion?.kind === "override",
    )
    .sort(
      (a, b) =>
        (ORDER.get(a.status) ?? 9) - (ORDER.get(b.status) ?? 9) ||
        a.asset_code.localeCompare(b.asset_code) ||
        a.source_name.localeCompare(b.source_name),
    );
}

/** Wireframe 07's figures: sensors in models, each category, models impacted. */
export function figures(sensors: readonly SensorHealth[]) {
  const inModels = sensors.filter((s) => s.models.length > 0);
  const byStatus: Record<string, number> = {};
  for (const s of inModels) byStatus[s.status] = (byStatus[s.status] ?? 0) + 1;
  const impacted = new Set(inModels.filter((s) => s.status !== "Good").flatMap((s) => s.models));
  return { inModels: inModels.length, byStatus, impacted: impacted.size };
}
