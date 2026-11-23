/** Plain-language labels and tones for states shown across the screens. */
import type { ToneName } from "../components/ui";

export const ALERT_STATE: Record<string, { label: string; tone: ToneName }> = {
  "Active-Unacknowledged": { label: "Unacknowledged", tone: "warning" },
  "Active-Acknowledged": { label: "Acknowledged", tone: "info" },
  "RTN-Unacknowledged": { label: "Returned, unacknowledged", tone: "warning" },
  Shelved: { label: "Shelved", tone: "neutral" },
  "Out of service": { label: "Out of service", tone: "unknown" },
  Normal: { label: "Closed", tone: "neutral" },
};

export function alertState(state: string): { label: string; tone: ToneName } {
  return ALERT_STATE[state] ?? { label: state, tone: "neutral" };
}

export const CASE_STATUS_TONE: Record<string, ToneName> = {
  Open: "info",
  Investigating: "info",
  "Action required": "warning",
  Monitoring: "info",
  Closed: "success",
  Cancelled: "neutral",
};

/** A closed case is green only when it closed as a true finding; any other outcome is neutral. */
export function caseStatusTone(status: string, outcome: string | null | undefined): ToneName {
  if (status === "Closed") return outcome === "true_finding" ? "success" : "neutral";
  return CASE_STATUS_TONE[status] ?? "neutral";
}

export const OUTCOME_LABEL: Record<string, string> = {
  true_finding: "True finding",
  false_alert: "False alert",
  sensor_issue: "Sensor issue",
  known_condition: "Known condition",
};

export const NE107_CODE: Record<string, { code: string; cls: string; tone: ToneName }> = {
  Failure: { code: "F", cls: "d-f", tone: "danger" },
  "Function check": { code: "C", cls: "d-c", tone: "info" },
  "Out of specification": { code: "S", cls: "d-s", tone: "warning" },
  "Maintenance required": { code: "M", cls: "d-m", tone: "warning" },
  Good: { code: "", cls: "", tone: "success" },
};

/** "Deviation above alert limit" for a DI alert, "TI-1012 above warning" for a sensor. */
export function alertText(a: {
  kind: "di" | "sensor";
  tag: string | null;
  severity: string;
  condition_active: boolean;
}): string {
  const limit = a.severity === "Alert" ? "alert" : "warning";
  const what = a.kind === "di" ? "Deviation" : `${shortTag(a.tag ?? "")} residual`;
  return a.condition_active
    ? `${what} above ${limit} limit`
    : `${what} returned below ${limit} limit`;
}

/** "TI-1012" from source name "K101.TI1012.PV". */
export function shortTag(source: string): string {
  const tag = source.replace(/^[^.]+\./, "").replace(/\.PV$/, "");
  return tag.replace(/^([A-Z]+)(\d)/, "$1-$2");
}

export function sensorName(s: { source_name: string; description?: string | null }): string {
  const tag = shortTag(s.source_name);
  return s.description ? `${tag} ${s.description}` : tag;
}

/** A tag's description without the tag repeated at its start ("Motor current"). */
export function plainDescription(source: string, description: string | null | undefined): string {
  if (!description) return "";
  const tag = shortTag(source);
  return description.replace(new RegExp(`^(${tag}|${tag.replace("-", "")})\\s*[-:,]?\\s*`), "");
}

/** "Required sensor not usable" from "Insufficient data: Required sensor not usable: X". */
export function plainReason(reason: string | null | undefined): string {
  if (!reason) return "Data check needed";
  const text = reason.replace(/^Insufficient data:\s*/i, "");
  return text.split(":")[0] ?? text;
}
