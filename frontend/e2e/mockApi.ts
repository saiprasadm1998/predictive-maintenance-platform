import type { Page, Route } from "@playwright/test";

/** A fleet of `sites` x `units` x `perUnit` monitored assets, shaped like GET /assets?tree=true. */
export function fleet(sites = 5, units = 10, perUnit = 10) {
  let id = 1;
  const bands = ["Healthy", "Healthy", "Healthy", "Watch", "Alert", "Unknown"] as const;
  const leaves: { id: number; code: string; band: string; health: number | null }[] = [];
  const node = (code: string, name: string, level: string, children: object[], extra = {}) => ({
    id: id++,
    code,
    name,
    level,
    criticality: null,
    asset_type: null,
    asset_type_name: null,
    open_alerts: 0,
    band: "Healthy",
    health: 90,
    counts: {},
    worst: null,
    models: [],
    children,
    ...extra,
  });
  const siteNodes = Array.from({ length: sites }, (_, s) =>
    node(
      `S${s}`,
      `Site ${s}`,
      "site",
      Array.from({ length: units }, (_, u) =>
        node(
          `S${s}U${u}`,
          `Unit ${s}.${u}`,
          "unit",
          Array.from({ length: perUnit }, (_, e) => {
            const band = bands[(s + u + e) % bands.length]!;
            const health = band === "Unknown" ? null : 30 + ((s * 7 + u * 3 + e) % 70);
            const leaf = node(`S${s}U${u}E${e}`, `Pump S${s}U${u}E${e}`, "equipment", [], {
              band,
              health,
              asset_type_name: "Centrifugal pump",
              open_alerts: band === "Alert" ? 2 : band === "Watch" ? 1 : 0,
              counts: { [band]: 1 },
              models: [
                {
                  model_id: id,
                  name: "main",
                  band,
                  health,
                  status: band === "Unknown" ? "Insufficient data" : "Running",
                  reason: band === "Unknown" ? "Insufficient data: no samples" : null,
                  last_cycle: new Date().toISOString(),
                },
              ],
            });
            leaves.push({ id: leaf.id, code: leaf.code, band, health });
            return leaf;
          }),
          { band: "Alert", health: 30, counts: { Alert: 2, Watch: 2, Healthy: 5, Unknown: 1 } },
        ),
      ),
      { band: "Alert", health: 30, counts: { Alert: 20 } },
    ),
  );
  return {
    roots: [
      node("ENT", "Fleet", "enterprise", siteNodes, {
        band: "Alert",
        health: 30,
        counts: { Alert: 100 },
      }),
    ],
    leaves,
  };
}

const USER = {
  id: 1,
  username: "admin",
  display_name: "Administrator",
  email: null,
  roles: [{ role: "administrator", scope_asset_id: null }],
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

/** Answers every /api/v1 call the screens make, signed in as an administrator. */
export async function mockApi(
  page: Page,
  size: { sites?: number; units?: number; perUnit?: number } = {},
) {
  const { roots, leaves } = fleet(size.sites, size.units, size.perUnit);
  const flat = leaves.map((l) => ({
    id: l.id,
    code: l.code,
    name: `Pump ${l.code}`,
    level: "equipment",
    parent_id: null,
    criticality: null,
    asset_type: null,
    description: "",
  }));
  const models = leaves.map((l, i) => ({
    id: i + 1,
    asset_code: l.code,
    name: "main",
    description: "",
    latest: {
      id: i + 1,
      version: 1,
      status: "Deployed",
      algorithm: "median",
      created_at: "2026-10-01T00:00:00Z",
    },
    in_service: {
      id: i + 1,
      version: 1,
      status: "Deployed",
      algorithm: "median",
      created_at: "2026-10-01T00:00:00Z",
    },
    runtime: {
      status: l.band === "Unknown" ? "Insufficient data" : "Running",
      reason: null,
      since: "2026-10-01T00:00:00Z",
      last_cycle: new Date().toISOString(),
      version_id: i + 1,
      band: l.band,
      di: l.health === null ? null : 100 - l.health,
      health: l.health,
    },
  }));
  const alerts = leaves
    .filter((l) => l.band === "Alert")
    .slice(0, 20)
    .map((l, i) => ({
      id: i + 1,
      model_id: leaves.indexOf(l) + 1,
      model: "main",
      asset_id: l.id,
      asset_code: l.code,
      kind: "di",
      tag_id: null,
      tag: null,
      state: "Active-Unacknowledged",
      severity: "Alert",
      priority: "P1",
      raised_at: new Date(Date.now() - (i + 1) * 3_600_000).toISOString(),
      condition_active: true,
      ack_at: null,
      closed_at: null as string | null,
      cleared_at: null as string | null,
      shelved_until: null as string | null,
      shelve_reason: null as string | null,
      asset_path: `Site 0 / Unit / ${l.code}`,
      version: 1,
      di: l.health === null ? null : 100 - l.health,
      health: l.health,
      persistence_n: 5,
      persistence_m: 5,
    }));
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/v1", "");
    if (path === "/auth/me") return json(route, { user: USER, csrf_token: "csrf" });
    if (path === "/events") {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: ": connected\n\n",
      });
    }
    if (path === "/assets" && url.searchParams.get("tree") === "true") return json(route, roots);
    if (path === "/assets") return json(route, { items: flat, next_cursor: null });
    if (path === "/fleet/kpis") {
      return json(route, {
        assets_by_band: { Alert: 84, Watch: 83, Healthy: 250, Unknown: 83 },
        open_alerts: { P1: 10, P2: 40 },
        unacknowledged_alerts: { P1: 10 },
        sensors_by_status: { Good: 4900, Failure: 12 },
        models_by_status: { Running: 417, "Insufficient data": 83 },
        stale_models: [],
        last_cycle: new Date().toISOString(),
      });
    }
    if (path === "/models") return json(route, models);
    const method = route.request().method();
    if (path === "/alerts") return json(route, { items: alerts, next_cursor: null });
    if (path === "/alerts/settings") return json(route, { max_shelve_days: 7 });
    if (path === "/priority-matrix") {
      return json(route, [
        { criticality: "A", severity: "Alert", priority: "P1" },
        { criticality: "A", severity: "Warning", priority: "P2" },
      ]);
    }
    if (method === "POST" && (path === "/alerts/ack" || path === "/alerts/shelve")) {
      const body = route.request().postDataJSON() as {
        ids: number[];
        reason?: string;
        minutes?: number;
      };
      const changed = alerts.filter((a) => body.ids.includes(a.id));
      for (const a of changed) {
        if (path === "/alerts/ack") a.state = "Active-Acknowledged";
        else {
          a.state = "Shelved";
          a.shelve_reason = body.reason ?? null;
          a.shelved_until = new Date(Date.now() + (body.minutes ?? 60) * 60_000).toISOString();
        }
      }
      return json(route, changed);
    }
    const alertMatch = /^\/alerts\/(\d+)$/.exec(path);
    if (alertMatch) {
      const a = alerts.find((x) => x.id === Number(alertMatch[1]));
      if (!a) return json(route, { title: "Not found", status: 404 }, 404);
      return json(route, {
        ...a,
        trace: {
          cycle: a.raised_at,
          value: 30,
          di: 30,
          health: 40,
          rule: { kind: "di", warning: 15, alert: 25 },
          inputs: {},
        },
        history: [],
      });
    }
    const assetMatch = /^\/assets\/(\d+)$/.exec(path);
    if (assetMatch) {
      const leaf = leaves.find((l) => l.id === Number(assetMatch[1]));
      const node = findNode(roots, Number(assetMatch[1]));
      if (!leaf && !node) return json(route, { title: "Not found", status: 404 }, 404);
      return json(route, {
        id: node!.id,
        code: node!.code,
        name: node!.name,
        level: node!.level,
        parent_id: null,
        criticality: null,
        asset_type: null,
        description: "",
        ancestors: [],
        health: node,
      });
    }
    const modelMatch = /^\/models\/(\d+)(\/[a-z-]+)?$/.exec(path);
    if (modelMatch) {
      const model = models[Number(modelMatch[1]) - 1];
      if (!model) return json(route, { title: "Not found", status: 404 }, 404);
      const now = Date.now();
      const trend = (series: string[]) => ({
        start: new Date(now - 86_400_000).toISOString(),
        end: new Date(now).toISOString(),
        raw: false,
        bucket_s: 3600,
        source: "raw",
        ts: Array.from({ length: 24 }, (_, i) =>
          new Date(now - (24 - i) * 3_600_000).toISOString(),
        ),
        min: Object.fromEntries(
          series.map((n) => [n, Array.from({ length: 24 }, (_, i) => 20 + i)]),
        ),
        max: Object.fromEntries(
          series.map((n) => [n, Array.from({ length: 24 }, (_, i) => 22 + i)]),
        ),
      });
      switch (modelMatch[2]) {
        case undefined:
          return json(route, {
            ...model,
            versions: [{ ...model.latest, sensors: [], params: { cycle_s: 60 }, error: null }],
            alert_rules: [
              { id: 1, kind: "di", tag_id: null, warning: 15, alert: 25, state: "Normal" },
            ],
          });
        case "/latest":
          return json(route, {
            version_id: model.id,
            version: 1,
            ts: new Date(now).toISOString(),
            sensors: ["TI1", "PI2", "FI3"].map((t, i) => ({
              tag_id: i + 1,
              source_name: `${model.asset_code}.${t}.PV`,
              description: `${t} sensor ${i + 1}`,
              unit: "°C",
              required: i === 0,
              actual: 70 + i,
              predicted: 68,
              residual: 2 + i,
              z: 1 + i,
              contribution: [0.5, 0.3, 0.2][i],
              dq_status: "Good",
              dq_rule: "none",
              used: true,
              sigma: 2,
              warning: 3,
              alert: 5,
            })),
          });
        case "/scores":
          return json(route, trend(["di", "health"]));
        case "/status-periods":
          return json(route, []);
        case "/diagnostics": {
          const mode = {
            id: 1,
            asset_type: "pump",
            code: "seal_leak",
            version: 1,
            name: "Seal leak",
            iso_code: "ELP",
            description: "",
            symptoms: [{ role: "temp", direction: "up", weight: 1 }],
            tasks: ["Inspect the mechanical seal"],
            comment: "",
            updated_at: new Date(now).toISOString(),
            updated_by: null,
            retired_at: null,
          };
          return json(route, {
            model_id: model.id,
            asset_code: "x",
            asset_type: "pump",
            version_id: model.id,
            at: new Date(now).toISOString(),
            note: "",
            modes: [
              {
                mode,
                score: 82,
                insufficient_evidence: false,
                evaluated_weight: 1,
                total_weight: 1,
                symptoms: [
                  {
                    role: "temp",
                    direction: "up",
                    weight: 1,
                    tag_id: 1,
                    source_name: "TI1",
                    z: 2.5,
                    z_ref: 3,
                    g: 0.83,
                    result: "match",
                  },
                ],
                trend: [{ ts: new Date(now).toISOString(), score: 82 }],
              },
            ],
          });
        }
        case "/outputs": {
          const tags = (url.searchParams.get("tags") ?? "").split(",").filter(Boolean);
          return json(
            route,
            tags.map((t, i) => ({
              ...trend(["actual", "predicted", "residual", "q", "z"]),
              tag_id: i + 1,
              source_name: t,
            })),
          );
        }
      }
    }
    return json(route, { title: "Not found", status: 404 }, 404);
  });
  return { roots, leaves, alerts };
}

interface TreeNode {
  id: number;
  code: string;
  name: string;
  level: string;
  children: TreeNode[];
}

function findNode(nodes: readonly object[], id: number): TreeNode | null {
  for (const n of nodes as TreeNode[]) {
    if (n.id === id) return n;
    const found = findNode(n.children, id);
    if (found) return found;
  }
  return null;
}
