import { createContext, useContext } from "react";

import type { AssetNode } from "../api/types";

/**
 * The plant scope chosen in the header (site, area, unit). It applies to every page and is
 * remembered per browser.
 */
export interface ScopeChoice {
  site: number | null;
  area: number | null;
  unit: number | null;
}

export interface ScopeState {
  choice: ScopeChoice;
  setChoice: (choice: ScopeChoice) => void;
  tree: AssetNode[];
  /** The deepest chosen node, or null for the whole plant. */
  node: AssetNode | null;
  /** Ids of every asset inside the scope; null when nothing is chosen. */
  ids: Set<number> | null;
  /** Equipment (level "equipment") inside the scope, in hierarchy order. */
  equipment: AssetNode[];
  label: string;
}

export const KEY = "pmp.scope";
const NONE: ScopeChoice = { site: null, area: null, unit: null };

export function stored(): ScopeChoice {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...NONE, ...(JSON.parse(raw) as ScopeChoice) } : NONE;
  } catch {
    return NONE;
  }
}

export function flatten(nodes: readonly AssetNode[]): AssetNode[] {
  const out: AssetNode[] = [];
  const walk = (n: AssetNode) => {
    out.push(n);
    n.children.forEach(walk);
  };
  nodes.forEach(walk);
  return out;
}

/** Nodes of a level below `root` (or in the whole tree), skipping levels in between. */
export function nodesOfLevel(roots: readonly AssetNode[], level: string): AssetNode[] {
  return flatten(roots).filter((n) => n.level === level);
}

export function find(roots: readonly AssetNode[], id: number | null): AssetNode | null {
  if (id === null) return null;
  return flatten(roots).find((n) => n.id === id) ?? null;
}

export const ScopeContext = createContext<ScopeState | null>(null);

export function useScope(): ScopeState {
  const scope = useContext(ScopeContext);
  if (!scope) throw new Error("useScope outside ScopeProvider");
  return scope;
}

/** Whether an asset id lies inside the chosen scope. */
export function useInScope(): (assetId: number) => boolean {
  const { ids } = useScope();
  return (assetId) => ids === null || ids.has(assetId);
}
