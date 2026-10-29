import { api } from "./client";

/** An asset-type model template (UC-07): a model definition written with roles. */
export interface ModelTemplate {
  id: number;
  asset_type: string;
  name: string;
  model_name: string;
  description: string;
  definition: Record<string, unknown>;
  required_roles: string[];
  optional_roles: string[];
  updated_at: string;
  updated_by: number | null;
}

/** What applying (or previewing) did for one asset. */
export interface TemplateResult {
  asset: string;
  outcome: "ready" | "created" | "skipped";
  reason: string | null;
  tags: Record<string, string>; // role -> tag
  missing_required: string[];
  missing_optional: string[]; // gaps: left out of the model
  model_id: number | null;
  version_id: number | null;
  job_id: number | null;
}

export function fetchTemplates(
  assetType: string | null,
  signal?: AbortSignal,
): Promise<ModelTemplate[]> {
  return api<ModelTemplate[]>("/model-templates", { query: { asset_type: assetType }, signal });
}

export function applyTemplate(
  id: number,
  assets: string[],
  preview: boolean,
): Promise<TemplateResult[]> {
  return api<TemplateResult[]>(`/model-templates/${id}/apply`, {
    method: "POST",
    body: { assets, preview },
  });
}
