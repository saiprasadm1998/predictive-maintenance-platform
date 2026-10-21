import { api } from "./client";
import type { ModelSummary, Trend } from "./types";

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
): Promise<Trend> {
  return api<Trend>(`/models/${modelId}/scores`, {
    query: { from: from.toISOString(), to: to.toISOString(), px },
    signal,
  });
}
