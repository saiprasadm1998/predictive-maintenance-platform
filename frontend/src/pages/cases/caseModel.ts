import type { User } from "../../api/auth";
import type { CaseDetail, CaseFilter, CaseStatus, CaseSummary, Outcome } from "../../api/cases";
import type { Alert } from "../../api/types";

/** The status stepper of wireframe 05 (Cancelled is shown apart). */
export const STEPS: CaseStatus[] = [
  "Open",
  "Investigating",
  "Action required",
  "Monitoring",
  "Closed",
];

export const STATUSES: CaseStatus[] = [...STEPS, "Cancelled"];

/** UCS Figure 7 edges a user takes by hand (closing has its own form). */
export const MANUAL_TRANSITIONS: Record<CaseStatus, Exclude<CaseStatus, "Open" | "Closed">[]> = {
  Open: ["Investigating", "Cancelled"],
  Investigating: ["Action required", "Monitoring", "Cancelled"],
  "Action required": ["Monitoring"],
  Monitoring: ["Action required"],
  Closed: [],
  Cancelled: [],
};

export const CLOSABLE: CaseStatus[] = ["Action required", "Monitoring"];

export const OUTCOMES: { value: Outcome; label: string }[] = [
  { value: "true_finding", label: "True finding" },
  { value: "false_alert", label: "False alert" },
  { value: "sensor_issue", label: "Sensor issue" },
  { value: "known_condition", label: "Known condition" },
];

export function outcomeLabel(outcome: Outcome | null): string {
  return OUTCOMES.find((o) => o.value === outcome)?.label ?? "—";
}

export function isOpen(status: CaseStatus): boolean {
  return status !== "Closed" && status !== "Cancelled";
}

/** The label of a state-change button ("Start investigating", "Cancel case…"). */
export function transitionLabel(target: CaseStatus, current: CaseStatus): string {
  if (target === "Investigating") return "Start investigating";
  if (target === "Cancelled") return "Cancel case…";
  if (target === "Monitoring")
    return current === "Investigating" ? "Monitor (no action yet)" : "Monitor";
  return current === "Monitoring" ? "Condition worsened: action required" : "Action required";
}

function roles(user: User | null | undefined): string[] {
  return user?.roles.map((r) => r.role) ?? [];
}

/** ARC §9.2: analysts and model engineers create cases; nobody else may. */
export function canCreateCases(user: User | null | undefined): boolean {
  return roles(user).some((r) => r === "analyst" || r === "model_engineer");
}

/** ARC §9.2: analysts and model engineers; a maintenance engineer on a case assigned to them. */
export function canWorkOn(user: User | null | undefined, c: Pick<CaseSummary, "assignee_id">) {
  if (canCreateCases(user)) return true;
  return !!user && roles(user).includes("maintenance") && c.assignee_id === user.id;
}

/** Why the selected alerts cannot become one case, or null when they can. */
export function caseBlocker(alerts: Pick<Alert, "asset_id" | "case_number">[]): string | null {
  if (!alerts.length) return "Select the alerts first.";
  const inCase = alerts.find((a) => a.case_number);
  if (inCase) return `An alert is already in open case ${inCase.case_number}.`;
  if (new Set(alerts.map((a) => a.asset_id)).size > 1) {
    return "A case covers the alerts of one asset: select alerts of one asset.";
  }
  return null;
}

/** "Due 12-Oct", "overdue since 12-Oct". */
export function dueText(c: Pick<CaseSummary, "due" | "overdue">): string {
  if (!c.due) return "—";
  const [y = 1970, m = 1, d = 1] = c.due.split("-").map(Number);
  const label = new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
  });
  return c.overdue ? `${label.replace(" ", "-")} (overdue)` : label.replace(" ", "-");
}

/** The list's filter, kept in the URL (SCR-09). */
export function readCaseFilter(params: URLSearchParams): CaseFilter {
  const status = params.get("status");
  const outcome = params.get("outcome");
  return {
    status: STATUSES.includes(status as CaseStatus) ? (status as CaseStatus) : null,
    open_only: params.get("open_only") === "true",
    priority: params.get("priority"),
    mine: params.get("mine") === "true",
    overdue: params.get("overdue") === "true",
    outcome: OUTCOMES.some((o) => o.value === outcome) ? (outcome as Outcome) : null,
    q: params.get("q"),
  };
}

export function writeCaseFilter(current: URLSearchParams, filter: CaseFilter): URLSearchParams {
  const next = new URLSearchParams(current);
  const set = (key: string, value: string | null | undefined) => {
    if (value) next.set(key, value);
    else next.delete(key);
  };
  set("status", filter.status);
  set("open_only", filter.open_only ? "true" : null);
  set("priority", filter.priority);
  set("mine", filter.mine ? "true" : null);
  set("overdue", filter.overdue ? "true" : null);
  set("outcome", filter.outcome);
  set("q", filter.q);
  return next;
}

/** One line per activity, as the wireframe's log reads. */
export function activityText(a: CaseDetail["activities"][number]): string {
  if (a.type === "state_change") {
    const to = text(a.data.to);
    const how = a.data.automatic ? " (automatic)" : "";
    return `Status: ${text(a.data.from)} → ${to}${how}${a.body ? `. ${a.body}` : ""}`;
  }
  return a.body;
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function statusClass(status: CaseStatus): string {
  return status.toLowerCase().replace(/ /g, "-");
}
