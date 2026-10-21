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
    if (path === "/alerts") return json(route, { items: [], next_cursor: null });
    return json(route, { title: "Not found", status: 404 }, 404);
  });
  return { roots, leaves };
}
