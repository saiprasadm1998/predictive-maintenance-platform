import type { Asset } from "../api/assets";

const MAX_RESULTS = 8;

/** Where an asset opens: equipment on its analysis screen (L3), anything above it on the
 * area/unit view (L2). */
export function assetPath(asset: Asset): string {
  return asset.level === "equipment" ? `/assets/${asset.id}` : `/units/${asset.id}`;
}

export function matchAssets(assets: readonly Asset[], text: string): Asset[] {
  const needle = text.trim().toLowerCase();
  if (!needle) return [];
  const scored = assets
    .map((asset) => {
      const code = asset.code.toLowerCase();
      const name = asset.name.toLowerCase();
      const rank = code.startsWith(needle)
        ? 0
        : code.includes(needle)
          ? 1
          : name.includes(needle)
            ? 2
            : 3;
      return { asset, rank };
    })
    .filter((x) => x.rank < 3);
  scored.sort((a, b) => a.rank - b.rank || a.asset.code.localeCompare(b.asset.code));
  return scored.slice(0, MAX_RESULTS).map((x) => x.asset);
}
