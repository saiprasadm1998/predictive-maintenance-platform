import type { Asset, Page } from "./assets";
import { api } from "./client";
import type { Job, Tag } from "./types";

/** Registry changes and imports (SCR-13; UC-02, UC-03, FR-REG-01 to -04, FR-ING-06). */

export const LEVELS = ["enterprise", "site", "area", "unit", "equipment"] as const;
export type Level = (typeof LEVELS)[number];
export const CRITICALITIES = ["A", "B", "C"] as const;

export interface AssetIn {
  code: string;
  name: string;
  level: Level;
  parent: string | null;
  criticality: string | null;
  asset_type: string | null;
  description: string;
}

export type AssetPatch = Partial<Omit<AssetIn, "code" | "level">>;

export function createAsset(asset: AssetIn): Promise<Asset> {
  return api<Asset>("/assets", { method: "POST", body: asset });
}

export function changeAsset(id: number, patch: AssetPatch): Promise<Asset> {
  return api<Asset>(`/assets/${id}`, { method: "PATCH", body: patch });
}

/** Every registered tag the user may see, following the pages. */
export async function fetchAllTags(signal?: AbortSignal): Promise<Tag[]> {
  const tags: Tag[] = [];
  let cursor: string | null = null;
  do {
    const page: Page<Tag> = await api<Page<Tag>>("/tags", {
      query: { limit: 500, cursor },
      signal,
    });
    tags.push(...page.items);
    cursor = page.next_cursor;
  } while (cursor);
  return tags;
}

export interface TagIn {
  source: string;
  source_name: string;
  asset: string;
  unit: string;
  range_lo: number;
  range_hi: number;
  interval_s: number;
  description: string;
  role: string | null;
}

export type TagPatch = Partial<Omit<TagIn, "source" | "source_name">>;

export function createTag(tag: TagIn): Promise<Tag> {
  return api<Tag>("/tags", { method: "POST", body: tag });
}

export function changeTag(id: number, patch: TagPatch): Promise<Tag> {
  return api<Tag>(`/tags/${id}`, { method: "PATCH", body: patch });
}

export interface Role {
  code: string;
  name: string;
  unit: string;
}

export interface AssetType {
  id: number;
  code: string;
  name: string;
  description: string;
  roles: Role[];
}

export function fetchAssetTypes(signal?: AbortSignal): Promise<AssetType[]> {
  return api<AssetType[]>("/asset-types", { signal });
}

export function createAssetType(type: {
  code: string;
  name: string;
  description: string;
}): Promise<AssetType> {
  return api<AssetType>("/asset-types", { method: "POST", body: type });
}

export function saveRole(typeId: number, role: Role): Promise<AssetType> {
  return api<AssetType>(`/asset-types/${typeId}/roles`, { method: "POST", body: role });
}

export interface ImportReport {
  committed: boolean;
  dry_run: boolean;
  counts: Record<string, Record<string, number>>;
  problems: { sheet: string; line: number; column: string; message: string }[];
}

/** Validate (dryRun) or import registry files: CSVs named by sheet, or one workbook. */
export function importRegistry(files: readonly File[], dryRun: boolean): Promise<ImportReport> {
  const form = new FormData();
  files.forEach((f) => form.append("files", f, f.name));
  return api<ImportReport>("/tags/import", {
    method: "POST",
    body: form,
    query: { dry_run: dryRun },
  });
}

export interface Unmapped {
  source: string;
  source_name: string;
  first_seen: string;
  last_seen: string;
  count: number;
}

export function fetchUnmapped(signal?: AbortSignal): Promise<Unmapped[]> {
  return api<Unmapped[]>("/unmapped-tags", { signal });
}

export function promoteUnmapped(tag: TagIn): Promise<Tag> {
  return api<Tag>("/unmapped-tags/promote", { method: "POST", body: tag });
}

// ------------------------------------------------------------------ history import

export interface HistoryOptions {
  source: string;
  layout: "long" | "wide" | null; // null: detected from the columns
  mode: "skip" | "overwrite";
  naive_as_utc: boolean;
  ts_column: string;
  tag_column: string;
  value_column: string;
  quality_column: string;
}

export interface QueuedJob {
  job_id: number;
  upload_id: string;
  preview: boolean;
}

/** What a history preview or import found (the job's result). */
export interface HistoryReport {
  error?: string;
  layout: string | null;
  preview: boolean;
  rows_read: number;
  loaded: number;
  duplicates: number;
  rejected: number;
  overlap: number;
  reconciles: boolean;
  rejected_by_reason: Record<string, number>;
  unmapped_tags: Record<string, number>;
  tags_found: number;
  first_ts: string | null;
  last_ts: string | null;
  problems: { row: number; reason: string; detail: string }[];
}

export function uploadHistory(
  file: File,
  options: HistoryOptions,
  preview: boolean,
): Promise<QueuedJob> {
  const form = new FormData();
  form.append("file", file, file.name);
  form.append("preview", String(preview));
  for (const [key, value] of Object.entries(options))
    if (value !== null && value !== "") form.append(key, String(value));
  return api<QueuedJob>("/ingest/backfill", { method: "POST", body: form });
}

/** Import a file that was uploaded for a preview, without sending it again. */
export function loadHistory(uploadId: string, options: HistoryOptions): Promise<QueuedJob> {
  return api<QueuedJob>(`/ingest/backfill/${uploadId}/load`, { method: "POST", body: options });
}

export type { Job };
