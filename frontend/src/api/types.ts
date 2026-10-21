/** Shapes of the REST API's answers (OpenAPI document at /api/v1/openapi.json). */

import type { Band } from "../components/status";

export interface ModelHealth {
  model_id: number;
  name: string;
  band: Band;
  health: number | null;
  status: string | null;
  reason: string | null;
  last_cycle: string | null;
}

export interface AssetNode {
  id: number;
  code: string;
  name: string;
  level: string;
  criticality: string | null;
  asset_type: string | null;
  asset_type_name: string | null;
  open_alerts: number;
  band: Band | null; // null: not monitored (no model beneath)
  health: number | null;
  counts: Partial<Record<Band, number>>;
  worst: string | null;
  models: ModelHealth[];
  children: AssetNode[];
}

export interface Crumb {
  id: number;
  code: string;
  name: string;
}

export interface AssetDetail {
  id: number;
  code: string;
  name: string;
  level: string;
  parent_id: number | null;
  criticality: string | null;
  asset_type: string | null;
  description: string;
  ancestors: Crumb[];
  health: AssetNode;
}

export interface Runtime {
  status: string;
  reason: string | null;
  since: string;
  last_cycle: string | null;
  version_id: number | null;
  band: Band;
  di: number | null;
  health: number | null;
}

export interface VersionSummary {
  id: number;
  version: number;
  status: string;
  algorithm: string;
  created_at: string;
}

export interface ModelSummary {
  id: number;
  asset_code: string;
  name: string;
  description: string;
  latest: VersionSummary;
  in_service: VersionSummary | null;
  runtime: Runtime | null;
}

export interface Alert {
  id: number;
  model_id: number;
  model: string;
  asset_id: number;
  asset_code: string;
  kind: "di" | "sensor";
  tag_id: number | null;
  tag: string | null;
  state: string;
  severity: "Alert" | "Warning";
  priority: string | null;
  raised_at: string;
  condition_active: boolean;
  ack_at: string | null;
  shelved_until: string | null;
  shelve_reason: string | null;
  closed_at: string | null;
  cleared_at: string | null; // when the condition returned to normal
}

export interface Trend {
  start: string;
  end: string;
  raw: boolean;
  bucket_s: number | null;
  source: string;
  ts: string[];
  min: Record<string, (number | null)[]>;
  max: Record<string, (number | null)[]>;
}

export interface VersionDetail extends VersionSummary {
  sensors: { tag_id: number; source_name: string; description: string; required: boolean }[];
  params: Record<string, unknown>;
  error: string | null;
}

export interface AlertRule {
  id: number;
  kind: "di" | "sensor";
  tag_id: number | null;
  warning: number;
  alert: number;
  state: string;
}

export interface ModelDetail extends ModelSummary {
  versions: VersionDetail[];
  alert_rules: AlertRule[];
}

export interface SensorNow {
  tag_id: number;
  source_name: string;
  description: string;
  unit: string;
  required: boolean;
  actual: number | null;
  predicted: number | null;
  residual: number | null;
  z: number | null;
  contribution: number | null;
  dq_status: string;
  dq_rule: string | null;
  used: boolean | null;
  sigma: number | null;
  warning: number;
  alert: number;
}

export interface LatestCycle {
  version_id: number;
  version: number;
  ts: string | null;
  sensors: SensorNow[];
}

export interface StatusPeriod {
  start: string;
  end: string;
  status: string;
  reason: string | null;
}

export interface SensorTrend extends Trend {
  tag_id: number;
  source_name: string;
}
