/** What the Set up screens need to know about each piece of equipment. */
import { useQuery } from "@tanstack/react-query";

import {
  type AssetType,
  type Coverage,
  fetchAllTags,
  fetchAssetTypes,
  fetchCoverage,
  fetchUnmapped,
} from "../../api/registry";
import { type ModelTemplate, fetchTemplates } from "../../api/templates";
import type { AssetNode, ModelSummary, Tag } from "../../api/types";
import { useModels } from "../../app/data";
import { useScope } from "../../app/scope";
import type { ToneName } from "../../components/ui";

export function useTags() {
  return useQuery({ queryKey: ["tags", "all"], queryFn: ({ signal }) => fetchAllTags(signal) });
}
export function useTypes() {
  return useQuery({ queryKey: ["asset-types"], queryFn: ({ signal }) => fetchAssetTypes(signal) });
}
export function useTemplates() {
  return useQuery({
    queryKey: ["templates"],
    queryFn: ({ signal }) => fetchTemplates(null, signal),
  });
}
export function useCoverage() {
  return useQuery({
    queryKey: ["tags", "coverage"],
    queryFn: ({ signal }) => fetchCoverage(signal),
  });
}
export function useUnmapped() {
  return useQuery({
    queryKey: ["tags", "unmapped"],
    queryFn: ({ signal }) => fetchUnmapped(signal),
  });
}

/** Roles that describe the operating condition rather than the machine's health. */
const DRIVER = /current|flow|suction|speed|load|power|ambient|inlet/i;
export function roleKind(code: string): "Driver" | "Monitored" {
  return DRIVER.test(code) ? "Driver" : "Monitored";
}

export type Readiness = "ready" | "roles" | "review" | "cannot" | "no-model";

export const READINESS: Record<Readiness, { label: string; tone: ToneName }> = {
  ready: { label: "Ready and scoring", tone: "success" },
  roles: { label: "Missing required roles", tone: "warning" },
  review: { label: "Model waiting for review", tone: "warning" },
  cannot: { label: "Cannot score", tone: "unknown" },
  "no-model": { label: "No model yet", tone: "neutral" },
};

export interface EquipmentSetup {
  node: AssetNode;
  type: AssetType | null;
  template: ModelTemplate | null;
  tags: Tag[];
  rolesTotal: number;
  rolesMapped: number;
  missingRequired: string[];
  historyDays: number | null;
  model: ModelSummary | null;
  readiness: Readiness;
  /** Setup steps done, 1 to 5: details, tags, history, model, monitoring. */
  step: number;
}

const DAY = 86_400_000;

function spanDays(tags: Tag[], coverage: Map<number, Coverage>): number | null {
  let first = Infinity;
  let last = -Infinity;
  for (const t of tags) {
    const c = coverage.get(t.id);
    if (!c) continue;
    first = Math.min(first, Date.parse(c.first_ts));
    last = Math.max(last, Date.parse(c.last_ts));
  }
  return Number.isFinite(first) ? Math.round((last - first) / DAY) : null;
}

export function describe(
  node: AssetNode,
  types: AssetType[],
  templates: ModelTemplate[],
  tags: Tag[],
  models: ModelSummary[],
  coverage: Map<number, Coverage>,
): EquipmentSetup {
  const type = types.find((t) => t.code === node.asset_type) ?? null;
  const template = templates.find((t) => t.asset_type === node.asset_type) ?? null;
  const mine = tags.filter((t) => t.asset_id === node.id);
  const filled = new Set(mine.map((t) => t.role).filter(Boolean));
  const roleCodes = type?.roles.map((r) => r.code) ?? [];
  const required = template?.required_roles ?? [];
  const missingRequired = required.filter((r) => !filled.has(r));
  const model = models.find((m) => m.asset_code === node.code) ?? null;
  const historyDays = spanDays(mine, coverage);
  let readiness: Readiness;
  if (missingRequired.length) readiness = "roles";
  else if (!model) readiness = "no-model";
  else if (model.latest.status === "Validated" && !model.in_service) readiness = "review";
  else if (model.in_service && model.runtime?.status === "Running") readiness = "ready";
  else if (model.in_service) readiness = "cannot";
  else readiness = "review";
  const step = model?.in_service ? 5 : model ? 4 : historyDays ? 3 : mine.length ? 2 : 1;
  return {
    node,
    type,
    template,
    tags: mine,
    rolesTotal: roleCodes.length,
    rolesMapped: roleCodes.filter((r) => filled.has(r)).length,
    missingRequired,
    historyDays,
    model,
    readiness,
    step,
  };
}

/** Every piece of equipment in scope with its setup state. */
export function useEquipmentSetup() {
  const scope = useScope();
  const tags = useTags();
  const types = useTypes();
  const templates = useTemplates();
  const models = useModels();
  const coverage = useCoverage();
  const loading = tags.isPending || types.isPending || models.isPending;
  const cov = new Map((coverage.data ?? []).map((c) => [c.tag_id, c]));
  const rows = loading
    ? []
    : scope.equipment.map((n) =>
        describe(
          n,
          types.data ?? [],
          templates.data ?? [],
          tags.data ?? [],
          models.data ?? [],
          cov,
        ),
      );
  return { rows, loading, tags, types, templates, models, coverage, scope };
}

/** A sensible instrument range for a unit, used until the real range is entered. */
export function defaultRange(unit: string): [number, number] {
  const u = unit.toLowerCase();
  if (u.includes("°c") || u === "c") return [0, 200];
  if (u.includes("bar")) return [0, 100];
  if (u === "a") return [0, 500];
  if (u.includes("m³/h") || u.includes("m3/h")) return [0, 1000];
  if (u.includes("mm/s")) return [0, 50];
  if (u.includes("µm") || u.includes("um")) return [0, 500];
  if (u.includes("rpm")) return [0, 20000];
  if (u === "%") return [0, 100];
  return [0, 1000];
}
