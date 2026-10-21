import { api } from "./client";

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
