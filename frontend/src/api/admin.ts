import { fetchAllPages } from "./assets";
import { api, apiUrl } from "./client";
import type { AuditEntry } from "./types";

/** Administration (SCR-14; UC-17, UC-19, UC-04, FR-SEC, FR-AUD-01, NFR-DATA-01). */

export const ROLES = [
  { value: "viewer", label: "Viewer" },
  { value: "analyst", label: "Reliability analyst" },
  { value: "maintenance", label: "Maintenance" },
  { value: "model_engineer", label: "Model engineer" },
  { value: "administrator", label: "Administrator" },
] as const;

export interface RoleGrant {
  role: string;
  scope_asset_id: number | null;
}

export interface AdminUser {
  id: number;
  username: string;
  display_name: string;
  email: string | null;
  active: boolean;
  roles: RoleGrant[];
  locked_until: string | null;
  last_login_at: string | null;
}

export function fetchUsers(signal?: AbortSignal): Promise<AdminUser[]> {
  return api<AdminUser[]>("/users", { signal });
}

export function createUser(user: {
  username: string;
  display_name: string;
  email: string | null;
  password: string;
  roles: RoleGrant[];
}): Promise<AdminUser> {
  return api<AdminUser>("/users", { method: "POST", body: user });
}

export function changeUser(
  id: number,
  patch: { roles?: RoleGrant[]; active?: boolean; password?: string },
): Promise<AdminUser> {
  return api<AdminUser>(`/users/${id}`, { method: "PATCH", body: patch });
}

// ------------------------------------------------------------------ API keys

export type KeyScope = "ingest" | "results-read";

export interface ApiKey {
  id: number;
  prefix: string;
  name: string;
  scope: KeyScope;
  created_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
}

export interface IssuedKey {
  id: number;
  key: string;
  prefix: string;
}

export function fetchApiKeys(signal?: AbortSignal): Promise<ApiKey[]> {
  return api<ApiKey[]>("/api-keys", { signal });
}

export function issueApiKey(name: string, scope: KeyScope): Promise<IssuedKey> {
  return api<IssuedKey>("/api-keys", { method: "POST", body: { name, scope } });
}

export function revokeApiKey(id: number): Promise<void> {
  return api<void>(`/api-keys/${id}/revoke`, { method: "POST" });
}

export function rotateApiKey(id: number): Promise<IssuedKey> {
  return api<IssuedKey>(`/api-keys/${id}/rotate`, { method: "POST" });
}

// ------------------------------------------------------------------ data quality

export interface RuleSet {
  scope: string;
  version: number;
  overrides: Record<string, unknown>;
  comment: string;
  created_at: string | null;
  defaults: Record<string, number | boolean>;
}

export interface RulesIn {
  scope: string;
  overrides: Record<string, number | boolean>;
  comment: string;
  confirm: boolean;
  days: number;
}

export interface RulePreview {
  scope: string;
  start: string;
  end: string;
  excluded_share: number;
  warning: boolean;
  tags: {
    tag_id: number;
    source_name: string;
    asset_code: string;
    cycles: number;
    excluded: number;
    excluded_share: number;
    by_rule: Record<string, number>;
  }[];
}

export function fetchRules(scope: string, signal?: AbortSignal): Promise<RuleSet> {
  return api<RuleSet>("/dq/rules", { query: { scope }, signal });
}

export function previewRules(rules: RulesIn): Promise<RulePreview> {
  return api<RulePreview>("/dq/rules/preview", { method: "POST", body: rules });
}

export function saveRules(rules: RulesIn): Promise<{ rules: RuleSet; preview: RulePreview }> {
  return api("/dq/rules", { method: "PUT", body: rules });
}

// ------------------------------------------------------------------ retention

export interface Retention {
  raw_months: number;
  aggregate_months: number;
  last_run_at: string | null;
  last_result: string | null;
}

export function fetchRetention(signal?: AbortSignal): Promise<Retention> {
  return api<Retention>("/retention", { signal });
}

export function saveRetention(raw_months: number, aggregate_months: number): Promise<Retention> {
  return api<Retention>("/retention", { method: "PUT", body: { raw_months, aggregate_months } });
}

// ------------------------------------------------------------------ audit log

export interface AuditQuery {
  from?: string;
  to?: string;
  user_id?: number;
  entity?: string;
  entity_id?: string;
}

export function fetchAuditPage(
  query: AuditQuery,
  cursor: number | null,
  signal?: AbortSignal,
): Promise<{ items: AuditEntry[]; next_cursor: number | null }> {
  return api("/audit", { query: { ...query, cursor, limit: 100 }, signal });
}

/** The CSV export of the same filter (the browser sends the session cookie). */
export function auditCsvUrl(query: AuditQuery): string {
  return apiUrl("/audit.csv", { ...query });
}

// ------------------------------------------------------------------ sensor health

export interface SensorHealth {
  tag_id: number;
  source: string;
  source_name: string;
  asset_code: string;
  status: string;
  rule: string;
  effect: string;
  since: string;
  evaluated_at: string;
}

export function fetchSensorHealth(signal?: AbortSignal): Promise<SensorHealth[]> {
  return fetchAllPages<SensorHealth>("/sensors/health", signal);
}
