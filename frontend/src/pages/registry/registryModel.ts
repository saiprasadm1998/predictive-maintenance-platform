import type { Asset } from "../../api/assets";
import type { User } from "../../api/auth";
import { LEVELS, type Level, type TagIn } from "../../api/registry";

/** ARC §9.2: the registry and its imports are changed by Model Engineers and Administrators. */
export function canEditRegistry(user: User | null | undefined): boolean {
  return !!user?.roles.some((r) => r.role === "model_engineer" || r.role === "administrator");
}

export interface HierarchyRow {
  asset: Asset;
  depth: number;
  hasChildren: boolean;
}

/** The assets as an indented list: each under its parent, siblings by code. */
export function hierarchyRows(assets: readonly Asset[]): HierarchyRow[] {
  const ids = new Set(assets.map((a) => a.id));
  const children = new Map<number | null, Asset[]>();
  for (const a of assets) {
    const parent = a.parent_id !== null && ids.has(a.parent_id) ? a.parent_id : null;
    children.set(parent, [...(children.get(parent) ?? []), a]);
  }
  const rows: HierarchyRow[] = [];
  const visit = (parent: number | null, depth: number) => {
    for (const a of [...(children.get(parent) ?? [])].sort((x, y) =>
      x.code.localeCompare(y.code),
    )) {
      rows.push({ asset: a, depth, hasChildren: children.has(a.id) });
      visit(a.id, depth + 1);
    }
  };
  visit(null, 0);
  return rows;
}

/** The level a child of `level` usually has (equipment has none). */
export function childLevel(level: string): Level | null {
  const i = LEVELS.indexOf(level as Level);
  return i >= 0 && i < LEVELS.length - 1 ? LEVELS[i + 1]! : null;
}

/** The levels a new asset may have under `parent` (at the top: an enterprise or a site). */
export function levelsBelow(parent: string | null): Level[] {
  if (parent === null) return ["enterprise", "site"];
  return LEVELS.slice(LEVELS.indexOf(parent as Level) + 1);
}

/** The asset and everything under it: an asset cannot move below itself. */
export function subtreeIds(assets: readonly Asset[], id: number): Set<number> {
  const found = new Set([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const a of assets)
      if (a.parent_id !== null && found.has(a.parent_id) && !found.has(a.id)) {
        found.add(a.id);
        grew = true;
      }
  }
  return found;
}

/** Where an asset may move: any asset at a higher level, outside its own subtree. */
export function parentChoices(assets: readonly Asset[], asset: Asset): Asset[] {
  const own = subtreeIds(assets, asset.id);
  const level = LEVELS.indexOf(asset.level as Level);
  return assets.filter((a) => !own.has(a.id) && LEVELS.indexOf(a.level as Level) < level);
}

/** What stops a tag form from being sent (the server checks again). */
export function tagProblems(tag: TagIn): string[] {
  const problems: string[] = [];
  if (!tag.source.trim()) problems.push("Source is required");
  if (!tag.source_name.trim()) problems.push("Source name is required");
  if (!tag.asset) problems.push("Choose the asset");
  if (!tag.unit.trim()) problems.push("Unit is required");
  if (!(Number.isFinite(tag.range_lo) && Number.isFinite(tag.range_hi)))
    problems.push("The instrument range needs two numbers");
  else if (!(tag.range_lo < tag.range_hi)) problems.push("Range low must be below range high");
  if (!(Number.isInteger(tag.interval_s) && tag.interval_s > 0))
    problems.push("The interval is a whole number of seconds above 0");
  return problems;
}

export function emptyTag(source = "", sourceName = "", asset = ""): TagIn {
  return {
    source,
    source_name: sourceName,
    asset,
    unit: "",
    range_lo: 0,
    range_hi: 100,
    interval_s: 60,
    description: "",
    role: null,
  };
}

/** "assets: 3 created, 1 changed" for an import report's counts. */
export function countText(counts: Record<string, number>): string {
  const parts = Object.entries(counts)
    .filter(([, n]) => n > 0)
    .map(([what, n]) => `${n.toLocaleString("en-GB")} ${what}`);
  return parts.join(", ") || "no change";
}

/** Reasons a history row was rejected, in words. */
export const REJECT_REASONS: Record<string, string> = {
  invalid_timestamp: "Timestamp not readable",
  timestamp_without_offset: "Timestamp without a time zone",
  unregistered_tag: "Tag not registered",
  invalid_value: "Value not a number",
  invalid_quality: "Quality not readable",
  in_future: "Timestamp in the future",
};
