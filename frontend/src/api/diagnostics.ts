import { api } from "./client";

export type Direction = "up" | "down" | "any";

export interface SymptomDef {
  role: string;
  direction: Direction;
  weight: number;
}

/** One version of a failure mode (UC-16, SCR-12). */
export interface FailureMode {
  id: number;
  asset_type: string;
  code: string;
  version: number;
  name: string;
  iso_code: string | null;
  description: string;
  symptoms: SymptomDef[];
  tasks: string[];
  comment: string;
  updated_at: string;
  updated_by: number | null;
  retired_at: string | null;
}

export interface FailureModeIn {
  asset_type: string;
  code: string;
  name: string;
  iso_code: string | null;
  description: string;
  symptoms: SymptomDef[];
  tasks: string[];
  comment: string;
}

export interface SymptomMatch {
  role: string;
  direction: Direction;
  weight: number;
  tag_id: number | null;
  source_name: string | null;
  z: number | null;
  z_ref: number | null;
  g: number | null;
  result: "match" | "partial" | "no match" | "not evaluated";
}

export interface ModeMatch {
  mode: FailureMode;
  score: number | null; // 0 to 100: a relative match, not a probability
  insufficient_evidence: boolean;
  evaluated_weight: number;
  total_weight: number;
  symptoms: SymptomMatch[];
  trend: { ts: string; score: number | null }[];
}

export interface Diagnosis {
  model_id: number;
  asset_code: string;
  asset_type: string | null;
  version_id: number | null;
  at: string | null;
  note: string;
  modes: ModeMatch[];
}

export function fetchDiagnosis(
  modelId: number,
  at: string | null,
  signal?: AbortSignal,
): Promise<Diagnosis> {
  return api<Diagnosis>(`/models/${modelId}/diagnostics`, { query: { at }, signal });
}

export function fetchLibrary(
  assetType: string | null,
  includeRetired: boolean,
  signal?: AbortSignal,
): Promise<FailureMode[]> {
  return api<FailureMode[]>("/library", {
    query: { asset_type: assetType, include_retired: includeRetired || null },
    signal,
  });
}

export function fetchModeVersions(id: number, signal?: AbortSignal): Promise<FailureMode[]> {
  return api<FailureMode[]>(`/library/${id}/versions`, { signal });
}

export function saveMode(body: FailureModeIn): Promise<FailureMode> {
  return api<FailureMode>("/library", { method: "PUT", body });
}

export function retireMode(id: number): Promise<FailureMode> {
  return api<FailureMode>(`/library/${id}/retire`, { method: "POST" });
}
