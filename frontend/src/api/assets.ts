import { api } from "./client";
import type { AssetDetail, AssetNode, Tag } from "./types";

export interface Asset {
  id: number;
  code: string;
  name: string;
  level: string;
  parent_id: number | null;
  criticality: string | null;
  asset_type: string | null;
  description: string;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

/** Every asset the user may see (flat, hierarchy order), following the pages. */
/** Every item of a cursor-paged list, following the pages. */
export async function fetchAllPages<T>(
  path: string,
  signal?: AbortSignal,
  query: Record<string, string | number | null> = {},
): Promise<T[]> {
  const items: T[] = [];
  let cursor: string | null = null;
  do {
    const page: Page<T> = await api<Page<T>>(path, {
      query: { ...query, limit: 500, cursor },
      signal,
    });
    items.push(...page.items);
    cursor = page.next_cursor;
  } while (cursor);
  return items;
}

export async function fetchAllAssets(signal?: AbortSignal): Promise<Asset[]> {
  const assets: Asset[] = [];
  let cursor: string | null = null;
  do {
    const page: Page<Asset> = await api<Page<Asset>>("/assets", {
      query: { limit: 500, cursor },
      signal,
    });
    assets.push(...page.items);
    cursor = page.next_cursor;
  } while (cursor);
  return assets;
}

/** The hierarchy with the health roll-up and open-alert counts (SCR-01). */
export function fetchAssetTree(signal?: AbortSignal): Promise<AssetNode[]> {
  return api<AssetNode[]>("/assets", { query: { tree: true }, signal });
}

/** One asset with its breadcrumb and its subtree's health. */
export function fetchAsset(id: number, signal?: AbortSignal): Promise<AssetDetail> {
  return api<AssetDetail>(`/assets/${id}`, { signal });
}

/** The asset's registered tags (one page of up to 500 is plenty for one asset). */
export async function fetchAssetTags(asset: string, signal?: AbortSignal): Promise<Tag[]> {
  const page = await api<Page<Tag>>("/tags", { query: { asset, limit: 500 }, signal });
  return page.items;
}
