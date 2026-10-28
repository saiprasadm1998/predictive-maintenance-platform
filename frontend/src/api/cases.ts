import { api } from "./client";

export type CaseStatus =
  "Open" | "Investigating" | "Action required" | "Monitoring" | "Closed" | "Cancelled";
export type Outcome = "true_finding" | "false_alert" | "sensor_issue" | "known_condition";

/** A case in the list (SCR-09). */
export interface CaseSummary {
  id: number;
  number: string; // C-nnnn
  title: string;
  status: CaseStatus;
  priority: string;
  asset_id: number;
  asset_code: string;
  asset_path: string;
  assignee_id: number | null;
  assignee: string | null;
  due: string | null; // YYYY-MM-DD
  overdue: boolean;
  outcome: Outcome | null;
  review_requested: boolean;
  alert_ids: number[];
  created_at: string;
  updated_at: string;
  closed_at: string | null;
}

export interface CaseActivity {
  id: number;
  ts: string;
  type:
    | "created"
    | "comment"
    | "attachment"
    | "action"
    | "state_change"
    | "assignment"
    | "update"
    | "link"
    | "closure";
  author_id: number | null;
  author: string | null;
  body: string;
  data: Record<string, unknown>;
  attachment_id: number | null;
}

export interface CaseAction {
  id: number;
  description: string;
  owner_id: number | null;
  owner: string | null;
  due: string | null;
  status: "open" | "done";
  created_at: string;
  done_at: string | null;
}

export interface CaseAttachment {
  id: number;
  filename: string;
  content_type: string;
  size: number;
  sha256: string;
  created_at: string;
  created_by: number | null;
}

/** What was known when the case was created (immutable, FR-CAS-01). */
export interface CaseSnapshot {
  taken_at: string;
  alerts: {
    id: number;
    model_id: number;
    kind: "di" | "sensor";
    tag: string | null;
    state: string;
    severity: string;
    priority: string | null;
    raised_at: string;
  }[];
  models: {
    model_id: number;
    model: string;
    asset_code: string;
    version: number;
    at: string | null;
    limits: { warning: number; alert: number } | null;
    trend?: { ts: string[]; di: (number | null)[]; health: (number | null)[] };
    sensors?: {
      tag_id: number;
      source_name: string | null;
      actual: number | null;
      predicted: number | null;
      z: number | null;
      contribution: number | null;
      dq_status: string;
      dq_rule: string | null;
      used: boolean | null;
    }[];
    diagnosis?: {
      code: string;
      name: string;
      version: number;
      score: number | null;
      insufficient_evidence: boolean;
    }[];
    forecast: {
      id: number;
      target: string;
      tag: string | null;
      threshold: number;
      urgency: string;
      median_h: number | null;
      lower_h: number | null;
      upper_h: number | null;
      valid: boolean;
      at: string;
    } | null;
  }[];
}

export interface CaseDetail extends CaseSummary {
  priority_set: boolean;
  confirmed_mode_id: number | null;
  value_estimate: number | null;
  lessons: string | null;
  cancel_reason: string | null;
  created_by: number | null;
  snapshot: CaseSnapshot;
  activities: CaseActivity[];
  actions: CaseAction[];
  attachments: CaseAttachment[];
}

export interface CasePerson {
  id: number;
  username: string;
  display_name: string;
  roles: string[];
}

export interface CaseFilter {
  status?: CaseStatus | null;
  open_only?: boolean;
  priority?: string | null;
  mine?: boolean;
  overdue?: boolean;
  outcome?: Outcome | null;
  q?: string | null;
}

export function fetchCases(filter: CaseFilter, signal?: AbortSignal): Promise<CaseSummary[]> {
  return api<CaseSummary[]>("/cases", {
    query: {
      status: filter.status ?? null,
      open_only: filter.open_only || null,
      priority: filter.priority ?? null,
      mine: filter.mine || null,
      overdue: filter.overdue || null,
      outcome: filter.outcome ?? null,
      q: filter.q || null,
    },
    signal,
  });
}

export function fetchCase(id: number, signal?: AbortSignal): Promise<CaseDetail> {
  return api<CaseDetail>(`/cases/${id}`, { signal });
}

export function fetchCasePeople(id: number, signal?: AbortSignal): Promise<CasePerson[]> {
  return api<CasePerson[]>(`/cases/${id}/people`, { signal });
}

export function createCase(alertIds: number[], title: string | null): Promise<CaseDetail> {
  return api<CaseDetail>("/cases", { method: "POST", body: { alert_ids: alertIds, title } });
}

export interface CasePatch {
  title?: string;
  priority?: string;
  assignee_id?: number | null;
  due?: string | null;
}

export function updateCase(id: number, patch: CasePatch): Promise<CaseDetail> {
  return api<CaseDetail>(`/cases/${id}`, { method: "PATCH", body: patch });
}

export function transitionCase(
  id: number,
  status: Exclude<CaseStatus, "Open" | "Closed">,
  reason: string | null = null,
): Promise<CaseDetail> {
  return api<CaseDetail>(`/cases/${id}/transition`, {
    method: "POST",
    body: { status, reason },
  });
}

export function addComment(id: number, body: string): Promise<CaseDetail> {
  return api<CaseDetail>(`/cases/${id}/activities`, {
    method: "POST",
    body: { type: "comment", body },
  });
}

export function addAction(
  id: number,
  description: string,
  ownerId: number | null,
  due: string | null,
): Promise<CaseDetail> {
  return api<CaseDetail>(`/cases/${id}/activities`, {
    method: "POST",
    body: { type: "action", body: description, owner_id: ownerId, due },
  });
}

export function completeAction(id: number, actionId: number): Promise<CaseDetail> {
  return api<CaseDetail>(`/cases/${id}/actions/${actionId}/done`, { method: "POST" });
}

export function addAttachment(id: number, file: File, comment: string): Promise<CaseDetail> {
  const form = new FormData();
  form.append("file", file);
  form.append("comment", comment);
  return api<CaseDetail>(`/cases/${id}/attachments`, { method: "POST", body: form });
}

export function attachmentUrl(caseId: number, attachmentId: number): string {
  return `/api/v1/cases/${caseId}/attachments/${attachmentId}`;
}

export interface Closure {
  outcome: Outcome;
  confirmed_mode_id: number | null;
  value_estimate: number | null;
  lessons: string | null;
}

export function closeCase(id: number, closure: Closure): Promise<CaseDetail> {
  return api<CaseDetail>(`/cases/${id}/close`, { method: "POST", body: closure });
}
