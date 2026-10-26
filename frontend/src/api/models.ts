import { api } from "./client";
import type {
  AlertRulesIn,
  AuditEntry,
  Job,
  LatestCycle,
  ModelDefinitionIn,
  ModelDetail,
  ModelSummary,
  SensorTrend,
  StatusPeriod,
  TrainingData,
  Trend,
  VersionSummary,
} from "./types";

export function fetchModels(signal?: AbortSignal): Promise<ModelSummary[]> {
  return api<ModelSummary[]>("/models", { signal });
}

/** DI and Health over a period, downsampled to about `px` points (min and max per bucket). */
export function fetchScores(
  modelId: number,
  from: Date,
  to: Date,
  px: number,
  signal?: AbortSignal,
  version?: number | null,
): Promise<Trend> {
  return api<Trend>(`/models/${modelId}/scores`, {
    query: { from: from.toISOString(), to: to.toISOString(), px, version },
    signal,
  });
}

export function fetchModel(id: number, signal?: AbortSignal): Promise<ModelDetail> {
  return api<ModelDetail>(`/models/${id}`, { signal });
}

/** Every sensor at the latest cycle of the version in service (or of `version`). */
export function fetchLatest(
  id: number,
  version: number | null,
  signal?: AbortSignal,
  at: string | null = null,
): Promise<LatestCycle> {
  return api<LatestCycle>(`/models/${id}/latest`, { query: { version, at }, signal });
}

export function fetchStatusPeriods(
  id: number,
  from: Date,
  to: Date,
  version: number | null,
  signal?: AbortSignal,
): Promise<StatusPeriod[]> {
  return api<StatusPeriod[]>(`/models/${id}/status-periods`, {
    query: { from: from.toISOString(), to: to.toISOString(), version },
    signal,
  });
}

/** Actual, predicted, residual, q and z of some sensors (by source name). */
export function fetchOutputs(
  id: number,
  tags: readonly string[],
  from: Date,
  to: Date,
  px: number,
  version: number | null,
  signal?: AbortSignal,
): Promise<SensorTrend[]> {
  return api<SensorTrend[]>(`/models/${id}/outputs`, {
    query: { tags: tags.join(","), from: from.toISOString(), to: to.toISOString(), px, version },
    signal,
  });
}

export type LifecycleAction = "deploy" | "pause" | "resume" | "retire" | "reject";

/** Change a version's status (ARC Figure 7); the server checks what is allowed. */
export function changeVersion(versionId: number, action: LifecycleAction): Promise<ModelDetail> {
  return api<ModelDetail>(`/versions/${versionId}/${action}`, { method: "POST" });
}

/** The audit trail of one entity (administrators only: others get 403). */
export function fetchAudit(
  entity: string,
  entityId: string | number,
  signal?: AbortSignal,
): Promise<{ items: AuditEntry[] }> {
  return api<{ items: AuditEntry[] }>("/audit", {
    query: { entity, entity_id: String(entityId), limit: 100 },
    signal,
  });
}

/** Save the definition: creates the model, updates its Draft or starts a new Draft version. */
export function saveModel(definition: ModelDefinitionIn): Promise<ModelDetail> {
  return api<ModelDetail>("/models", { method: "POST", body: definition });
}

export function saveAlertRules(modelId: number, rules: AlertRulesIn): Promise<ModelDetail> {
  return api<ModelDetail>(`/models/${modelId}/alert-rules`, { method: "PUT", body: rules });
}

/** Train the model's Draft version; the worker runs the job. */
export function startTraining(
  modelId: number,
): Promise<{ version: VersionSummary; job_id: number | null }> {
  return api(`/models/${modelId}/versions`, { method: "POST" });
}

/** The cleansing rules applied to the training periods, without saving anything. */
export function previewTrainingData(
  definition: ModelDefinitionIn,
  px: number,
  signal?: AbortSignal,
): Promise<TrainingData> {
  return api<TrainingData>("/models/training-data", {
    method: "POST",
    body: definition,
    query: { px },
    signal,
  });
}

export function fetchJob(id: number, signal?: AbortSignal): Promise<Job> {
  return api<Job>(`/jobs/${id}`, { signal });
}
