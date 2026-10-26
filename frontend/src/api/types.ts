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
  status_changed_at: string | null;
}

export interface ModelSummary {
  id: number;
  asset_code: string;
  name: string;
  description: string;
  latest: VersionSummary;
  in_service: VersionSummary | null;
  runtime: Runtime | null;
  alerts_30d: number;
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
  asset_path: string; // "Site A / Ammonia unit / K-101"
  version: number | null;
  di: number | null; // the model's latest
  health: number | null;
  persistence_n: number | null; // of the rule's last m cycles, how many met the severity
  persistence_m: number | null;
}

export interface AlertEvent {
  ts: string;
  action: string;
  from_state: string | null;
  to_state: string;
  severity: string;
  priority: string;
  user_id: number | null;
  user: string | null;
  comment: string | null;
}

export interface AlertDetail extends Alert {
  trace: Record<string, unknown>;
  history: AlertEvent[];
}

export interface PriorityCell {
  criticality: string;
  severity: string;
  priority: string;
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

export interface Period {
  start: string;
  end: string;
}

export interface VersionDetail extends VersionSummary {
  sensors: { tag_id: number; source_name: string; description: string; required: boolean }[];
  params: Record<string, unknown>;
  error: string | null;
  training_periods?: Period[];
  validation_period?: Period | null;
  mode_filters?: string[];
  metrics?: Record<string, unknown> | null;
  artefact_sha256?: string | null;
}

export interface AuditEntry {
  id: number;
  ts: string;
  user_id: number | null;
  actor_type: string;
  entity: string;
  entity_id: string;
  action: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  ip: string | null;
}

export interface AlertRule {
  id: number;
  kind: "di" | "sensor";
  tag_id: number | null;
  warning: number;
  alert: number;
  state: string;
  persistence_n?: number;
  persistence_m?: number;
  on_delay_s?: number;
  deadband?: number;
  clear_cycles?: number;
  enabled?: boolean;
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
  /** Cycles the sensor was left out of scoring, with its NE 107 status then. */
  unused?: { start: string; end: string; status: string; rule: string | null }[];
}

/** A model definition as saved (POST /models) or previewed; times are ISO 8601. */
export interface ModelDefinitionIn {
  asset: string;
  name: string;
  description?: string;
  sensors: { tag: string; required: boolean }[];
  training_periods: Period[];
  validation_period: Period;
  mode_filters: string[];
  params?: Record<string, unknown>;
  alert_rules?: AlertRulesIn;
}

export interface AlertRulesIn {
  di: { warning: number; alert: number; persistence_n?: number; persistence_m?: number };
  sensors: { tag: string; warning: number; alert: number }[];
}

/** What the cleansing rules leave of the training periods (SCR-06 step 3). */
export interface TrainingData {
  cycle_s: number;
  cycles: number;
  retained: number;
  mode_removed: number;
  quality_removed: number;
  blocked: string | null;
  sensors: {
    source_name: string;
    description: string;
    required: boolean;
    usable_share: number;
    flagged: boolean;
  }[];
  bucket_s: number;
  buckets: string[];
  excluded: number[];
  values: Record<string, (number | null)[]>;
}

export interface Job {
  id: number;
  type: string;
  status: "queued" | "running" | "succeeded" | "failed";
  progress: number | null;
  attempts: number;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface Tag {
  id: number;
  source: string;
  source_name: string;
  asset_id: number;
  asset_code: string;
  description: string;
  unit: string;
  range_lo: number;
  range_hi: number;
  interval_s: number;
  role: string | null;
}
