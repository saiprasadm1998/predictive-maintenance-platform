/** Pure helpers behind the fleet overview and unit view (SCR-01, SCR-08). */

import type { Alert, AssetNode, ModelSummary } from "../../api/types";
import type { Band } from "../../components/status";

export interface Row {
  node: AssetNode;
  depth: number;
  hasChildren: boolean;
  expanded: boolean;
}

/** Every node, depth first, in hierarchy order. */
export function walk(nodes: readonly AssetNode[]): AssetNode[] {
  const out: AssetNode[] = [];
  const visit = (n: AssetNode) => {
    out.push(n);
    n.children.forEach(visit);
  };
  nodes.forEach(visit);
  return out;
}

/**
 * Opened at first: the top level, and every branch with something abnormal in it, so what
 * needs attention is visible without clicking (PDS §2.1 L1: "where does the plant need
 * attention now?"). Healthy branches start closed.
 */
export function defaultExpanded(roots: readonly AssetNode[]): Set<number> {
  const open = new Set<number>();
  const visit = (n: AssetNode, depth: number) => {
    if (!n.children.length) return;
    const abnormal = (n.counts.Alert ?? 0) + (n.counts.Watch ?? 0) + (n.counts.Unknown ?? 0) > 0;
    if (depth === 0 || abnormal) open.add(n.id);
    n.children.forEach((c) => visit(c, depth + 1));
  };
  roots.forEach((r) => visit(r, 0));
  return open;
}

/** The visible rows: a branch's children show only while it is expanded. */
export function visibleRows(roots: readonly AssetNode[], expanded: ReadonlySet<number>): Row[] {
  const rows: Row[] = [];
  const visit = (n: AssetNode, depth: number) => {
    const open = expanded.has(n.id);
    rows.push({ node: n, depth, hasChildren: n.children.length > 0, expanded: open });
    if (open) n.children.forEach((c) => visit(c, depth + 1));
  };
  roots.forEach((r) => visit(r, 0));
  return rows;
}

/** Only the branches that hold assets in `band` (the KPI click-through). */
export function filterByBand(roots: readonly AssetNode[], band: Band): AssetNode[] {
  const keep = (n: AssetNode): AssetNode | null => {
    if (!(n.counts[band] ?? 0)) return null;
    return { ...n, children: n.children.map(keep).filter((c): c is AssetNode => c !== null) };
  };
  return roots.map(keep).filter((n): n is AssetNode => n !== null);
}

export type TreeSort = "name" | "band" | "health";
const BAND_RANK: Record<string, number> = { Alert: 0, Watch: 1, Unknown: 2, Healthy: 3 };

/** Siblings worst first (band, then Health) or by name; the hierarchy itself stays. */
export function sortTree(roots: readonly AssetNode[], sort: TreeSort): AssetNode[] {
  if (sort === "name") return [...roots];
  const rank = (n: AssetNode) => (n.band ? (BAND_RANK[n.band] ?? 4) : 5);
  const health = (n: AssetNode) => n.health ?? Number.POSITIVE_INFINITY;
  const compare = (a: AssetNode, b: AssetNode) =>
    sort === "band"
      ? rank(a) - rank(b) || health(a) - health(b) || a.name.localeCompare(b.name)
      : health(a) - health(b) || rank(a) - rank(b) || a.name.localeCompare(b.name);
  const order = (nodes: readonly AssetNode[]): AssetNode[] =>
    [...nodes].sort(compare).map((n) => ({ ...n, children: order(n.children) }));
  return order(roots);
}

/** Every branch with children, for "expand all" under a filter. */
export function allBranches(roots: readonly AssetNode[]): Set<number> {
  return new Set(
    walk(roots)
      .filter((n) => n.children.length)
      .map((n) => n.id),
  );
}

export interface Deviation {
  modelId: number;
  assetId: number | null;
  label: string;
  band: Band;
  di: number;
}

/** "Highest deviation now": running models by their latest DI, highest first. */
export function highestDeviation(
  models: readonly ModelSummary[],
  roots: readonly AssetNode[],
  limit = 8,
): Deviation[] {
  const byCode = new Map(walk(roots).map((n) => [n.code, n]));
  return models
    .filter((m) => m.runtime?.status === "Running" && m.runtime.di !== null)
    .map((m) => {
      const asset = byCode.get(m.asset_code);
      return {
        modelId: m.id,
        assetId: asset?.id ?? null,
        label: asset ? assetLabel(asset) : m.asset_code,
        band: m.runtime!.band,
        di: m.runtime!.di!,
      };
    })
    .sort((a, b) => b.di - a.di)
    .slice(0, limit);
}

/** Equipment opens on asset analysis (L3), anything above it on the unit view (L2). */
export function assetLink(node: { id: number; level: string }): string {
  return node.level === "equipment" ? `/assets/${node.id}` : `/units/${node.id}`;
}

/** PDS §7: the display name followed by the tag-style ID, unless the name already has it. */
export function assetLabel(asset: { code: string; name: string }): string {
  return asset.name.includes(asset.code) ? asset.name : `${asset.code} ${asset.name}`;
}

/** Newest first. */
export function recentAlerts(alerts: readonly Alert[], limit = 8): Alert[] {
  return [...alerts].sort((a, b) => b.raised_at.localeCompare(a.raised_at)).slice(0, limit);
}

/** "K-101 Deviation Index high", "P-104A TI1044 residual" (wireframe 01). */
export function describeAlert(alert: Alert): string {
  if (alert.kind === "di") return `${alert.asset_code} Deviation Index high`;
  const tag = (alert.tag ?? "sensor").replace(/^[^.]+\./, "").replace(/\.PV$/, "");
  return `${alert.asset_code} ${tag} residual`;
}

/** "42 min", "3 h", "2 d": how long ago. */
export function age(from: Date, now: Date = new Date()): string {
  const minutes = Math.max(0, Math.floor((now.getTime() - from.getTime()) / 60_000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.floor(hours / 24)} d`;
}

/** Rows whose band, Health or alert count changed since the last read (live highlight). */
export function changedIds(
  previous: ReadonlyMap<number, string>,
  roots: readonly AssetNode[],
): { changed: Set<number>; next: Map<number, string> } {
  const next = new Map(walk(roots).map((n) => [n.id, `${n.band}|${n.health}|${n.open_alerts}`]));
  const changed = new Set<number>();
  if (previous.size) {
    for (const [id, value] of next) {
      if (previous.has(id) && previous.get(id) !== value) changed.add(id);
    }
  }
  return { changed, next };
}

/** The equipment beneath a node (or the node itself), for the unit view's cards. */
export function equipmentUnder(node: AssetNode): AssetNode[] {
  const all = walk([node]).filter((n) => n.models.length > 0 || n.level === "equipment");
  return all.filter((n) => n.id !== node.id || node.level === "equipment");
}

/** Why an asset is Unknown, from its models (UC-08 2a: shown on hover). */
export function unknownReason(node: AssetNode): string | null {
  if (node.band !== "Unknown") return null;
  const own = node.models.find((m) => m.band === "Unknown" && m.reason);
  if (own?.reason) return own.reason;
  return node.children.length ? null : "insufficient data";
}

/** Open alerts over time, from raise and close times: one value per step (SCR-08). */
export function openAlertSeries(
  alerts: readonly Alert[],
  from: number,
  to: number,
  steps = 168,
): [number, number][] {
  const step = Math.max(1, (to - from) / steps);
  const out: [number, number][] = [];
  for (let t = from; t <= to; t += step) {
    const open = alerts.filter((a) => {
      const raised = Date.parse(a.raised_at);
      const closed = a.closed_at ? Date.parse(a.closed_at) : Infinity;
      return raised <= t && t < closed;
    }).length;
    out.push([Math.round(t), open]);
  }
  return out;
}
