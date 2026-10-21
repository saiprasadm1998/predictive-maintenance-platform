import { vi } from "vitest";

/** A stand-in for the web role: routes `METHOD /path` to handlers and records requests. */
export interface Call {
  method: string;
  path: string;
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

export const KPIS = {
  assets_by_band: { Alert: 2, Watch: 2, Unknown: 1, Healthy: 3 },
  open_alerts: { P1: 2 },
  unacknowledged_alerts: { P1: 2 },
  sensors_by_status: { Good: 55, Failure: 5 },
  models_by_status: { Running: 7 },
  stale_models: [],
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
    "GET /assets": () => ({ status: 200, body: { items: ASSETS, next_cursor: null } }),
    "GET /fleet/kpis": () => ({ status: 200, body: KPIS }),
  };
}
