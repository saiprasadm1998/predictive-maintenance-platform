import { ROLES, type RoleGrant } from "../../api/admin";
import type { Asset } from "../../api/assets";
import type { User } from "../../api/auth";
import type { AuditEntry } from "../../api/types";

/** ARC §9.2: users, keys, retention and the audit log are for Administrators. */
export function isAdministrator(user: User | null | undefined): boolean {
  return !!user?.roles.some((r) => r.role === "administrator");
}

/** ARC §9.2: data-quality rules are changed by Model Engineers. */
export function isModelEngineer(user: User | null | undefined): boolean {
  return !!user?.roles.some((r) => r.role === "model_engineer");
}

export function roleLabel(role: string): string {
  return ROLES.find((r) => r.value === role)?.label ?? role;
}

/** "Model engineer (SITE-A)", or without a scope "Administrator". */
export function grantText(grant: RoleGrant, assets: readonly Asset[]): string {
  if (grant.scope_asset_id === null) return roleLabel(grant.role);
  const scope =
    assets.find((a) => a.id === grant.scope_asset_id)?.code ?? `#${grant.scope_asset_id}`;
  return `${roleLabel(grant.role)} (${scope})`;
}

export const MIN_PASSWORD = 12;

/** The server's password rules (decision 5.1), checked before sending. */
export function passwordProblems(username: string, password: string): string[] {
  const problems: string[] = [];
  if (password.length < MIN_PASSWORD)
    problems.push(`The password needs at least ${MIN_PASSWORD} characters`);
  if (username.trim() && password.toLowerCase().includes(username.trim().toLowerCase()))
    problems.push("The password may not contain the username");
  return problems;
}

// ------------------------------------------------------------------ data quality

export interface RuleParam {
  name: string;
  label: string;
  kind: "switch" | "number";
  unit?: string;
}

/** The UCS §6.1 rule parameters, in the order an engineer reads them. */
export const RULE_PARAMS: readonly RuleParam[] = [
  { name: "stale", label: "Stale check", kind: "switch" },
  { name: "stale_factor", label: "Stale after", kind: "number", unit: "× the interval" },
  { name: "out_of_range", label: "Out-of-range check", kind: "switch" },
  { name: "flatline", label: "Flatline check", kind: "switch" },
  { name: "flatline_window", label: "Flatline window", kind: "number", unit: "samples" },
  { name: "flatline_std_pct", label: "Flatline below", kind: "number", unit: "% of range (std)" },
  {
    name: "flatline_guard_pct",
    label: "Flatline guard",
    kind: "number",
    unit: "% of range (training std)",
  },
  { name: "flatline_used", label: "Keep flatlined sensors in scoring", kind: "switch" },
  { name: "spike", label: "Spike check", kind: "switch" },
  { name: "spike_pct", label: "Spike above", kind: "number", unit: "% of range per sample" },
  { name: "uncertain_quality", label: "Flag Uncertain quality", kind: "switch" },
];

/** A form value per parameter: "" inherits; otherwise this scope's override. */
export type RuleForm = Record<string, string>;

export function ruleForm(overrides: Record<string, unknown>): RuleForm {
  return Object.fromEntries(
    RULE_PARAMS.map((p) => {
      const v = overrides[p.name];
      return [p.name, typeof v === "number" || typeof v === "boolean" ? String(v) : ""];
    }),
  );
}

export function overridesOf(form: RuleForm): Record<string, number | boolean> {
  const out: Record<string, number | boolean> = {};
  for (const p of RULE_PARAMS) {
    const v = form[p.name] ?? "";
    if (v === "") continue;
    out[p.name] = p.kind === "switch" ? v === "true" : Number(v);
  }
  return out;
}

export function ruleProblems(form: RuleForm): string[] {
  return RULE_PARAMS.filter((p) => p.kind === "number" && form[p.name] !== "")
    .filter((p) => !(Number(form[p.name]) > 0))
    .map((p) => `${p.label} must be a number above 0`);
}

export const RULE_LABELS: Record<string, string> = {
  bad_quality: "Bad source quality",
  stale: "Stale",
  manual_exclusion: "Manual exclusion",
  out_of_range: "Out of range",
  flatline: "Flatline",
  spike: "Spike",
  uncertain_quality: "Uncertain quality",
  override: "Overridden to Good",
  none: "—",
};

export const EFFECT_LABELS: Record<string, string> = {
  used: "In use",
  used_flagged: "In use, flagged",
  excluded: "Excluded",
  sample_excluded: "Sample excluded",
};

// ------------------------------------------------------------------ audit

/** What changed: the fields whose value differs between before and after. */
export function changedFields(entry: AuditEntry): string[] {
  const before = entry.before ?? {};
  const after = entry.after ?? {};
  return [...new Set([...Object.keys(before), ...Object.keys(after)])].filter(
    (k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]),
  );
}
