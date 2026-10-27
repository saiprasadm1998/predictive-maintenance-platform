import type {
  AlertRulesIn,
  ModelDefinitionIn,
  ModelDetail,
  Tag,
  TrainingData,
  VersionDetail,
} from "../../api/types";

/**
 * The model builder's state (SCR-06) and the rules each step checks before Next. The draft
 * is kept in the browser while it is edited (PDS §6: input survives navigation) and saved
 * to the server as the model's Draft version when training starts.
 */

export const STEPS = [
  "Asset and sensors",
  "Training period",
  "Cleanse data",
  "Train and validate",
  "Alert limits",
  "Deploy",
] as const;

export const DEFAULT_DI = { warning: 15, alert: 25 }; // before a version is validated
export const DEFAULT_SENSOR = { warning: 3, alert: 5 }; // |z|, UCS §6.4
export const DEFAULT_PERSISTENCE = { n: 3, m: 5 };
export const MIN_CYCLE_S = 10; // FR-RUN-01
const DAY = 86_400_000;

export interface SensorPick {
  tag: string;
  required: boolean;
}

export interface SensorRule {
  tag: string;
  warning: number;
  alert: number;
}

export interface DraftPeriod {
  start: string; // datetime-local text, in the browser's time zone
  end: string;
}

export interface BuilderDraft {
  asset: string;
  name: string;
  description: string;
  sensors: SensorPick[];
  training: DraftPeriod[];
  validation: DraftPeriod;
  cycleS: number;
  modeFilters: string[];
  /** Periods left out of training, picked on the trend (UC-05 step 5). */
  exclusions: DraftPeriod[];
  di: { warning: number; alert: number; n: number; m: number };
  sensorRules: SensorRule[];
  /** The training job started from this page, so its progress can be followed. */
  jobId: number | null;
  /** The version whose proposed limits were last put in `di` (plan 7.3). */
  proposedFor?: number | null;
}

/** "2026-10-21T14:05" for a datetime-local input, in the browser's time zone. */
export function toLocalInput(date: Date): string {
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return shifted.toISOString().slice(0, 16);
}

/** A datetime-local text as a moment (NaN date when it is not a time). */
export function fromLocalInput(text: string): Date {
  return new Date(text);
}

function midnight(now: Date): Date {
  const day = new Date(now);
  day.setHours(0, 0, 0, 0);
  return day;
}

/** A new model: the last 120 to 30 days to train on, the last 30 days to validate on. */
export function newDraft(asset = "", now = new Date()): BuilderDraft {
  const today = midnight(now).getTime();
  return {
    asset,
    name: "main",
    description: "",
    sensors: [],
    training: [
      {
        start: toLocalInput(new Date(today - 120 * DAY)),
        end: toLocalInput(new Date(today - 30 * DAY)),
      },
    ],
    validation: {
      start: toLocalInput(new Date(today - 30 * DAY)),
      end: toLocalInput(new Date(today)),
    },
    cycleS: 60,
    modeFilters: [],
    exclusions: [],
    di: { ...DEFAULT_DI, ...DEFAULT_PERSISTENCE },
    sensorRules: [],
    jobId: null,
  };
}

function periodInput(p: { start: string; end: string }): DraftPeriod {
  return { start: toLocalInput(new Date(p.start)), end: toLocalInput(new Date(p.end)) };
}

/** A new version of an existing model starts from its latest version and its rules. */
export function draftFromModel(model: ModelDetail, now = new Date()): BuilderDraft {
  const latest: VersionDetail | undefined = model.versions[model.versions.length - 1];
  const base = newDraft(model.asset_code, now);
  const names = new Map(latest?.sensors.map((s) => [s.tag_id, s.source_name]) ?? []);
  const di = model.alert_rules.find((r) => r.kind === "di");
  return {
    ...base,
    name: model.name,
    description: model.description,
    sensors: latest?.sensors.map((s) => ({ tag: s.source_name, required: s.required })) ?? [],
    training: latest?.training_periods?.length
      ? latest.training_periods.map(periodInput)
      : base.training,
    validation: latest?.validation_period ? periodInput(latest.validation_period) : base.validation,
    cycleS: Number(latest?.params.cycle_s ?? 60),
    modeFilters: latest?.mode_filters ?? [],
    exclusions: (latest?.exclusion_periods ?? []).map(periodInput),
    di: di
      ? {
          warning: di.warning,
          alert: di.alert,
          n: di.persistence_n ?? DEFAULT_PERSISTENCE.n,
          m: di.persistence_m ?? DEFAULT_PERSISTENCE.m,
        }
      : base.di,
    sensorRules: model.alert_rules
      .filter((r) => r.kind === "sensor" && r.tag_id !== null && names.has(r.tag_id))
      .map((r) => ({ tag: names.get(r.tag_id!)!, warning: r.warning, alert: r.alert })),
  };
}

/** Every role-mapped tag of the asset (the asset-type template), required kept as set. */
export function applyTemplate(draft: BuilderDraft, tags: readonly Tag[]): BuilderDraft {
  const kept = new Map(draft.sensors.map((s) => [s.tag, s.required]));
  return {
    ...draft,
    sensors: tags
      .filter((t) => t.role !== null)
      .map((t) => ({ tag: t.source_name, required: kept.get(t.source_name) ?? false })),
  };
}

const NAME = /^[A-Za-z0-9][A-Za-z0-9 _.-]{0,99}$/;

function periodProblems(p: DraftPeriod, label: string): string[] {
  const start = fromLocalInput(p.start).getTime();
  const end = fromLocalInput(p.end).getTime();
  if (Number.isNaN(start) || Number.isNaN(end)) return [`${label} needs a start and an end`];
  return start < end ? [] : [`${label} must end after it starts`];
}

function overlaps(a: DraftPeriod, b: DraftPeriod): boolean {
  return (
    fromLocalInput(a.start) < fromLocalInput(b.end) &&
    fromLocalInput(b.start) < fromLocalInput(a.end)
  );
}

/** What stops Next on a step (UC-05 rules; the server checks them all again). */
export function stepProblems(step: number, draft: BuilderDraft): string[] {
  const problems: string[] = [];
  if (step === 1) {
    if (!draft.asset) problems.push("Choose the asset");
    if (!NAME.test(draft.name.trim()))
      problems.push("Model name: 1 to 100 letters, digits, spaces, '.', '_' or '-'");
    if (!draft.sensors.length) problems.push("Select at least one sensor");
  }
  if (step === 2) {
    if (!draft.training.length) problems.push("Add at least one training period");
    const own = draft.training.flatMap((p, i) => periodProblems(p, `Training period ${i + 1}`));
    const validation = periodProblems(draft.validation, "Validation period");
    problems.push(...own, ...validation);
    if (!own.length && !validation.length) {
      draft.training.forEach((a, i) =>
        draft.training.slice(i + 1).forEach((b, j) => {
          if (overlaps(a, b)) problems.push(`Training periods ${i + 1} and ${i + j + 2} overlap`);
        }),
      );
      draft.training.forEach((p, i) => {
        if (overlaps(p, draft.validation))
          problems.push(`Training period ${i + 1} overlaps the validation period`);
      });
    }
    if (!Number.isInteger(draft.cycleS) || draft.cycleS < MIN_CYCLE_S)
      problems.push(`The scoring cycle must be a whole number of seconds, at least ${MIN_CYCLE_S}`);
  }
  if (step === 3) {
    draft.modeFilters.forEach((f, i) => {
      if (!f.trim()) problems.push(`Operating-mode filter ${i + 1} is empty`);
    });
    (draft.exclusions ?? []).forEach((p, i) => {
      const start = fromLocalInput(p.start).getTime();
      const end = fromLocalInput(p.end).getTime();
      if (!(start < end))
        problems.push(`Excluded period ${i + 1}: the start must be before the end`);
    });
  }
  if (step === 5) {
    const { warning, alert, n, m } = draft.di;
    if (!(warning > 0 && warning < alert)) problems.push("DI limits need 0 < warning < alert");
    if (!(Number.isInteger(n) && Number.isInteger(m) && n >= 1 && n <= m))
      problems.push("Persistence needs whole numbers with 1 ≤ n ≤ m");
    for (const r of draft.sensorRules)
      if (!(r.warning > 0 && r.warning < r.alert))
        problems.push(`${r.tag}: limits need 0 < warning < alert`);
  }
  return problems;
}

export function alertRules(draft: BuilderDraft): AlertRulesIn {
  const chosen = new Set(draft.sensors.map((s) => s.tag));
  return {
    di: {
      warning: draft.di.warning,
      alert: draft.di.alert,
      persistence_n: draft.di.n,
      persistence_m: draft.di.m,
    },
    sensors: draft.sensorRules
      .filter((r) => chosen.has(r.tag))
      .map((r) => ({ tag: r.tag, warning: r.warning, alert: r.alert })),
  };
}

/** The definition the server takes; alert rules only when they may be saved now. */
export function toDefinition(draft: BuilderDraft, withRules: boolean): ModelDefinitionIn {
  const iso = (text: string) => fromLocalInput(text).toISOString();
  return {
    asset: draft.asset,
    name: draft.name.trim(),
    description: draft.description.trim(),
    sensors: draft.sensors,
    training_periods: draft.training.map((p) => ({ start: iso(p.start), end: iso(p.end) })),
    validation_period: { start: iso(draft.validation.start), end: iso(draft.validation.end) },
    mode_filters: draft.modeFilters.map((f) => f.trim()).filter(Boolean),
    exclusion_periods: (draft.exclusions ?? []).map((p) => ({
      start: iso(p.start),
      end: iso(p.end),
    })),
    params: { cycle_s: draft.cycleS },
    ...(withRules ? { alert_rules: alertRules(draft) } : {}),
  };
}

/** The model's version in service (Deployed or Paused), whose limits are live. */
export function inService(model: ModelDetail | undefined): VersionDetail | undefined {
  return model?.versions.find((v) => v.status === "Deployed" || v.status === "Paused");
}

/** Which step a saved model can be shown at: training needs a saved Draft and so on. */
export function furthestStep(model: ModelDetail | undefined, draft: BuilderDraft): number {
  for (const step of [1, 2, 3]) if (stepProblems(step, draft).length) return step;
  const latest = model?.versions[model.versions.length - 1];
  if (!latest || latest.status === "Draft") return 3;
  if (latest.status === "Training" || latest.status === "Failed") return 4;
  if (latest.status === "Validated") return 6;
  return 3; // the latest version is in service or ended: a new version starts at step 1-3
}

// ------------------------------------------------------------------ the browser copy

function storageKey(userId: number, key: string): string {
  return `pmp.builder.${userId}.${key}`;
}

/** The draft kept in this browser for a model ("new" before it is first saved). */
export function loadDraft(userId: number, key: string): BuilderDraft | null {
  try {
    const raw = window.localStorage.getItem(storageKey(userId, key));
    if (!raw) return null;
    const draft = JSON.parse(raw) as BuilderDraft;
    return { ...draft, exclusions: draft.exclusions ?? [] }; // copies saved before 7.2
  } catch {
    return null;
  }
}

export function storeDraft(userId: number, key: string, draft: BuilderDraft): void {
  try {
    window.localStorage.setItem(storageKey(userId, key), JSON.stringify(draft));
  } catch {
    // Storage full or blocked: the draft lives only as long as the page.
  }
}

export function forgetDraft(userId: number, key: string): void {
  try {
    window.localStorage.removeItem(storageKey(userId, key));
  } catch {
    // nothing to forget
  }
}

/** "78.0 %" of a count. */
export function share(part: number, whole: number): string {
  return whole ? `${((100 * part) / whole).toFixed(1)} %` : "—";
}

/** One sensor's training data as a line (broken where no cycles fall), with the buckets
 * where most cycles are excluded shaded as periods. */
/** The validation report kept with a version (plan 7.3, UCS §6.4). */
export interface ValidationReport {
  cycles: number;
  di_percentiles: Record<"P50" | "P95" | "P99" | "P99.9", number>;
  outside_envelope: number | null;
  proposed: { di_warning: number; di_alert: number; sensor_warning: number; sensor_alert: number };
  alerts: number;
  alerts_per_week: number;
  warning: string | null;
  sensors?: Record<string, { nrmse: number; bias: number }>;
}

/** The report from a version's metrics, or null for versions trained before 7.3. */
export function validationReport(
  metrics: Record<string, unknown> | null | undefined,
): ValidationReport | null {
  const raw = metrics?.validation;
  if (!raw || typeof raw !== "object") return null;
  const report = raw as Partial<ValidationReport>;
  return report.di_percentiles && report.proposed ? (report as ValidationReport) : null;
}

/** Put a newly validated version's proposed DI limits in the draft, once per version. */
export function withProposedLimits(
  draft: BuilderDraft,
  versionId: number,
  report: ValidationReport | null,
): BuilderDraft {
  if (!report || draft.proposedFor === versionId) return draft;
  return {
    ...draft,
    di: { ...draft.di, warning: report.proposed.di_warning, alert: report.proposed.di_alert },
    proposedFor: versionId,
  };
}

/** A cluster holding less than this share of the retained data may be under-learnt. */
export const SMALL_CLUSTER = 0.05;

/** "3 operating clusters: 52 %, 31 %, 17 %" and the clusters that are small. */
export function clusterSummary(clusters: readonly number[]): { text: string; small: number[] } {
  const total = clusters.reduce((a, b) => a + b, 0);
  if (!clusters.length || !total) return { text: "Not enough data to find them", small: [] };
  const shares = clusters.map((c) => c / total);
  const text = `${clusters.length} operating cluster${clusters.length === 1 ? "" : "s"}: ${shares
    .map((s) => `${Math.round(s * 100)} %`)
    .join(", ")}`;
  const small = shares.flatMap((s, i) => (s < SMALL_CLUSTER ? [i + 1] : []));
  return { text, small };
}

export function trainingTrend(data: TrainingData, sensor: string) {
  const step = data.bucket_s * 1000;
  const values = data.values[sensor] ?? [];
  const points: [number, number | null][] = [];
  const excluded: { from: number; to: number; reason: string }[] = [];
  data.buckets.forEach((ts, i) => {
    const t = Date.parse(ts);
    const previous = points[points.length - 1];
    if (previous && t - previous[0] > step) points.push([previous[0] + step, null]);
    points.push([t, values[i] ?? null]);
    if ((data.excluded[i] ?? 0) < 0.5) return;
    const last = excluded[excluded.length - 1];
    if (last && last.to === t) last.to = t + step;
    else excluded.push({ from: t, to: t + step, reason: "Excluded from training" });
  });
  const from = points[0]?.[0] ?? 0;
  const to = (points[points.length - 1]?.[0] ?? 0) + step;
  return { points, excluded, from, to };
}
