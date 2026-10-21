import { api } from "./client";
import type {
  LatestCycle,
  ModelDetail,
  ModelSummary,
  SensorTrend,
  StatusPeriod,
  Trend,
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
): Promise<LatestCycle> {
  return api<LatestCycle>(`/models/${id}/latest`, { query: { version }, signal });
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
