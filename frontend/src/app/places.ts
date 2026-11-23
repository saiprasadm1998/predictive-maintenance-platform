import type { AssetNode } from "../api/types";

/** "Site A / Ammonia unit" for each asset id, from the hierarchy. */
export function locations(tree: readonly AssetNode[]): Map<number, string> {
  const out = new Map<number, string>();
  const walk = (nodes: readonly AssetNode[], trail: string[]) => {
    for (const n of nodes) {
      out.set(n.id, trail.join(" / "));
      const next = n.level === "enterprise" || n.level === "equipment" ? trail : [...trail, n.name];
      walk(n.children, next);
    }
  };
  walk(tree, []);
  return out;
}
