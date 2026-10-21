import { vi } from "vitest";

/** A stand-in for the web role: routes `METHOD /path` to handlers and records requests. */
export interface Call {
  method: string;
  path: string;
  query: URLSearchParams;
  headers: Record<string, string>;
  body: unknown;
}

type Handler = (call: Call) => { status: number; body?: unknown };

export const ADMIN = {
  id: 1,
  username: "admin",
  display_name: "Administrator",
  email: null,
  roles: [{ role: "administrator", scope_asset_id: null }],
};

export const ASSETS = [
  { id: 1, code: "DEMO", name: "Demo enterprise", level: "enterprise", parent_id: null },
  { id: 5, code: "SA-AMM", name: "Ammonia unit", level: "unit", parent_id: 3 },
  { id: 6, code: "K-101", name: "Syngas compressor K-101", level: "equipment", parent_id: 5 },
  { id: 7, code: "P-104A", name: "BFW pump P-104A", level: "equipment", parent_id: 5 },
].map((a) => ({ criticality: null, asset_type: null, description: "", ...a }));

function node(
  id: number,
  code: string,
  name: string,
  level: string,
  band: string | null,
  health: number | null,
  children: unknown[] = [],
  extra: Record<string, unknown> = {},
) {
  return {
    id,
    code,
    name,
    level,
    criticality: null,
    asset_type: null,
    asset_type_name: null,
    open_alerts: 0,
    band,
    health,
    counts: {},
    worst: null,
    models: [],
    children,
    ...extra,
  };
}

/** Demo-like hierarchy: Site A with K-101 (Alert), P-104A (Watch), P-202 (Unknown); Utilities healthy. */
export const TREE = [
  node(
    1,
    "DEMO",
    "Demo enterprise",
    "enterprise",
    "Alert",
    28,
    [
      node(
        5,
        "SA-AMM",
        "Ammonia unit",
        "unit",
        "Alert",
        28,
        [
          node(6, "K-101", "Syngas compressor K-101", "equipment", "Alert", 28, [], {
            asset_type_name: "Centrifugal compressor",
            open_alerts: 3,
            counts: { Alert: 1 },
            models: [
              {
                model_id: 1,
                name: "main",
                band: "Alert",
                health: 28,
                status: "Running",
                reason: null,
                last_cycle: null,
              },
            ],
          }),
          node(7, "P-104A", "BFW pump P-104A", "equipment", "Watch", 67, [], {
            asset_type_name: "Centrifugal pump",
            open_alerts: 2,
            counts: { Watch: 1 },
            models: [
              {
                model_id: 2,
                name: "main",
                band: "Watch",
                health: 67,
                status: "Running",
                reason: null,
                last_cycle: null,
              },
            ],
          }),
          node(8, "P-202", "Carbamate pump P-202", "equipment", "Unknown", null, [], {
            counts: { Unknown: 1 },
            models: [
              {
                model_id: 3,
                name: "main",
                band: "Unknown",
                health: null,
                status: "Insufficient data",
                reason: "Insufficient data: Required sensor not usable",
                last_cycle: null,
              },
            ],
          }),
        ],
        { open_alerts: 5, counts: { Alert: 1, Watch: 1, Unknown: 1 } },
      ),
      node(
        9,
        "SA-UTIL",
        "Utilities",
        "unit",
        "Healthy",
        91,
        [
          node(10, "E-110", "Waste-heat boiler E-110", "equipment", "Healthy", 91, [], {
            counts: { Healthy: 1 },
            models: [
              {
                model_id: 4,
                name: "main",
                band: "Healthy",
                health: 91,
                status: "Running",
                reason: null,
                last_cycle: null,
              },
            ],
          }),
        ],
        { counts: { Healthy: 1 } },
      ),
    ],
    { open_alerts: 5, counts: { Alert: 1, Watch: 1, Unknown: 1, Healthy: 1 } },
  ),
];

function model(id: number, asset: string, band: string, di: number | null, status = "Running") {
  return {
    id,
    asset_code: asset,
    name: "main",
    description: "",
    latest: {
      id,
      version: 1,
      status: "Deployed",
      algorithm: "median",
      created_at: "2026-10-01T00:00:00Z",
    },
    in_service: {
      id,
      version: 1,
      status: "Deployed",
      algorithm: "median",
      created_at: "2026-10-01T00:00:00Z",
    },
    runtime: {
      status,
      reason: null,
      since: "2026-10-01T00:00:00Z",
      last_cycle: "2026-10-21T08:15:00Z",
      version_id: id,
      band,
      di,
      health: null,
    },
  };
}

export const MODELS = [
  model(1, "K-101", "Alert", 36.2),
  model(2, "P-104A", "Watch", 19.1),
  model(3, "P-202", "Unknown", null, "Insufficient data"),
  model(4, "E-110", "Healthy", 7.7),
];

function alert(
  id: number,
  asset: string,
  kind: "di" | "sensor",
  priority: string,
  raised: string,
  tag: string | null = null,
) {
  return {
    id,
    model_id: 1,
    model: "main",
    asset_id: 6,
    asset_code: asset,
    kind,
    tag_id: tag ? 99 : null,
    tag,
    state: "Active-Unacknowledged",
    severity: priority === "P1" ? "Alert" : "Warning",
    priority,
    raised_at: raised,
    condition_active: true,
    ack_at: null,
    shelved_until: null,
    shelve_reason: null,
    closed_at: null,
    cleared_at: null,
    asset_path: `Site A / Ammonia unit / ${asset}`,
    version: 1,
    di: 36.2,
    health: 28,
    persistence_n: 5,
    persistence_m: 5,
  };
}

export const ALERTS = [
  alert(1, "K-101", "di", "P1", "2026-10-20T00:01:00Z"),
  alert(7, "P-104A", "sensor", "P3", "2026-10-20T08:30:00Z", "P104A.TI1044.PV"),
];

export const KPIS = {
  assets_by_band: { Alert: 2, Watch: 2, Unknown: 1, Healthy: 3 },
  open_alerts: { P1: 2 },
  unacknowledged_alerts: { P1: 2 },
  sensors_by_status: { Good: 55, Failure: 5 },
  models_by_status: { Running: 7 },
  stale_models: [] as number[],
  last_cycle: "2026-10-21T08:15:00Z",
};

export function fakeApi(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(
      input instanceof Request ? input.url : input.toString(),
      "http://localhost",
    );
    const method = init?.method ?? "GET";
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const headers = Object.fromEntries(Object.entries(init?.headers ?? {})) as Record<
      string,
      string
    >;
    const call: Call = {
      method,
      path,
      query: url.searchParams,
      headers,
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
    };
    calls.push(call);
    const handler = routes[`${method} ${path}`];
    const { status, body } = handler
      ? handler(call)
      : { status: 404, body: { title: "Not found", status: 404 } };
    return Promise.resolve(
      new Response(status === 204 ? null : JSON.stringify(body ?? {}), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

/** A session that starts signed out and signs in with admin / correct-horse-battery. */
export function sessionRoutes(signedIn = false): Record<string, Handler> {
  let session = signedIn;
  return {
    "GET /auth/me": () =>
      session
        ? { status: 200, body: { user: ADMIN, csrf_token: "csrf-1" } }
        : { status: 401, body: { title: "Not signed in", status: 401 } },
    "POST /auth/login": (call) => {
      const { username, password } = call.body as { username: string; password: string };
      if (username === "admin" && password === "correct-horse-battery") {
        session = true;
        return { status: 200, body: { user: ADMIN, csrf_token: "csrf-2" } };
      }
      return {
        status: 401,
        body: { title: "Sign-in failed", status: 401, detail: "Wrong username or password." },
      };
    },
    "POST /auth/logout": () => {
      session = false;
      return { status: 204 };
    },
    "GET /assets": (call) =>
      call.query.get("tree") === "true"
        ? { status: 200, body: TREE }
        : { status: 200, body: { items: ASSETS, next_cursor: null } },
    "GET /fleet/kpis": () => ({ status: 200, body: KPIS }),
    "GET /models": () => ({ status: 200, body: MODELS }),
    "GET /alerts": () => ({ status: 200, body: { items: ALERTS, next_cursor: null } }),
  };
}
