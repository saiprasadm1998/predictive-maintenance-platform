import type { Page, Route } from "@playwright/test";

import type { mockApi } from "./mockApi";

type Alerts = Awaited<ReturnType<typeof mockApi>>["alerts"];

const PEOPLE = [
  { id: 1, username: "ana", display_name: "Ana Analyst", roles: ["analyst"] },
  { id: 3, username: "max", display_name: "Max Maintenance", roles: ["maintenance"] },
];
const MODE = { id: 26, name: "Seal leak" };

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

/**
 * A stateful case back end for the browser journeys (plan 8.4c), on top of mockApi: the
 * signed-in user is an analyst, cases follow UCS Figure 7 (assigning starts the
 * investigation, an action makes it Action required, the last action done Monitoring),
 * and the alert list shows each alert's open case.
 */
export async function mockCases(page: Page, alerts: Alerts) {
  const cases: Record<string, unknown>[] = [];
  const caseOf = new Map<number, { id: number; number: string }>();
  const now = () => new Date().toISOString();

  function log(c: Record<string, unknown>, type: string, body: string, data = {}) {
    const activities = c.activities as Record<string, unknown>[];
    activities.push({
      id: activities.length + 1,
      ts: now(),
      type,
      author_id: 1,
      author: "Ana Analyst",
      body,
      data,
      attachment_id: null,
    });
    c.updated_at = now();
  }
  function move(c: Record<string, unknown>, to: string, automatic = true) {
    log(c, "state_change", "", { from: c.status, to, automatic });
    c.status = to;
  }

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/v1", "");
    const method = request.method();
    const body = (request.postDataJSON() ?? {}) as Record<string, unknown>;

    if (path === "/auth/me") {
      return json(route, {
        user: {
          id: 1,
          username: "ana",
          display_name: "Ana Analyst",
          email: null,
          roles: [{ role: "analyst", scope_asset_id: null }],
        },
        csrf_token: "csrf",
      });
    }
    if (path === "/alerts" && method === "GET") {
      const modelId = Number(url.searchParams.get("model_id")) || null;
      const items = alerts
        .filter((a) => modelId === null || a.model_id === modelId)
        .map((a) => ({
          ...a,
          case_id: caseOf.get(a.id)?.id ?? null,
          case_number: caseOf.get(a.id)?.number ?? null,
        }));
      return json(route, { items, next_cursor: null });
    }
    if (path === "/library") return json(route, [MODE]);
    if (path === "/cases" && method === "GET") return json(route, cases);
    if (path === "/cases" && method === "POST") {
      const ids = body.alert_ids as number[];
      const linked = alerts.filter((a) => ids.includes(a.id));
      const first = linked[0]!;
      const id = cases.length + 1;
      const number = `C-${String(id).padStart(4, "0")}`;
      const c: Record<string, unknown> = {
        id,
        number,
        title: body.title ?? `${first.asset_code} DI alert`,
        status: "Open",
        priority: "P1",
        asset_id: first.asset_id,
        asset_code: first.asset_code,
        asset_path: first.asset_path,
        assignee_id: null,
        assignee: null,
        due: null,
        overdue: false,
        outcome: null,
        review_requested: false,
        alert_ids: ids,
        created_at: now(),
        updated_at: now(),
        closed_at: null,
        priority_set: false,
        confirmed_mode_id: null,
        value_estimate: null,
        lessons: null,
        cancel_reason: null,
        created_by: 1,
        snapshot: {
          taken_at: now(),
          alerts: linked.map((a) => ({
            id: a.id,
            model_id: a.model_id,
            kind: "di",
            tag: null,
            state: a.state,
            severity: a.severity,
            priority: a.priority,
            raised_at: a.raised_at,
          })),
          models: [
            {
              model_id: first.model_id,
              model: "main",
              asset_code: first.asset_code,
              version: 1,
              at: now(),
              limits: { warning: 15, alert: 25 },
              trend: {
                ts: [new Date(Date.now() - 3_600_000).toISOString(), now()],
                di: [22, 30],
                health: [50, 40],
              },
              sensors: [
                {
                  tag_id: 1,
                  source_name: "TI1",
                  actual: 88,
                  predicted: 80,
                  z: 2.5,
                  contribution: 60,
                  dq_status: "Good",
                  dq_rule: null,
                  used: true,
                },
              ],
              diagnosis: [
                {
                  code: "seal_leak",
                  name: "Seal leak",
                  version: 1,
                  score: 82,
                  insufficient_evidence: false,
                },
              ],
              forecast: null,
            },
          ],
        },
        activities: [],
        actions: [],
        attachments: [],
      };
      log(c, "created", `Case created from alert ${ids.join(", ")}. Snapshot attached.`);
      for (const a of ids) caseOf.set(a, { id, number });
      cases.unshift(c);
      return json(route, c, 201);
    }
    const match = /^\/cases\/(\d+)(\/.*)?$/.exec(path);
    if (match) {
      const c = cases.find((x) => x.id === Number(match[1]));
      if (!c) return json(route, { title: "Not found", status: 404 }, 404);
      const rest = match[2] ?? "";
      if (rest === "/people") return json(route, PEOPLE);
      if (rest === "" && method === "PATCH") {
        if ("assignee_id" in body) {
          const person = PEOPLE.find((p) => p.id === body.assignee_id)!;
          c.assignee_id = person.id;
          c.assignee = person.display_name;
          log(c, "assignment", `Assigned to ${person.display_name}`);
          if (c.status === "Open") move(c, "Investigating");
        }
        if ("due" in body) c.due = body.due;
        if ("priority" in body) c.priority = body.priority;
      }
      if (rest === "/activities" && method === "POST") {
        if (body.type === "action") {
          const actions = c.actions as Record<string, unknown>[];
          const owner = PEOPLE.find((p) => p.id === body.owner_id);
          actions.push({
            id: 100 + actions.length,
            description: body.body,
            owner_id: owner?.id ?? null,
            owner: owner?.display_name ?? null,
            due: body.due ?? null,
            status: "open",
            created_at: now(),
            done_at: null,
          });
          log(c, "action", `Action: ${String(body.body)}`);
          if (c.status === "Investigating" || c.status === "Monitoring") {
            move(c, "Action required");
          }
        } else {
          log(c, "comment", String(body.body));
        }
        return json(route, c, 201);
      }
      const done = /^\/actions\/(\d+)\/done$/.exec(rest);
      if (done && method === "POST") {
        const actions = c.actions as Record<string, unknown>[];
        const action = actions.find((a) => a.id === Number(done[1]))!;
        action.status = "done";
        action.done_at = now();
        log(c, "update", `Action done: ${String(action.description)}`);
        if (actions.every((a) => a.status === "done")) move(c, "Monitoring");
      }
      if (rest === "/close" && method === "POST") {
        c.outcome = body.outcome;
        c.confirmed_mode_id = body.confirmed_mode_id;
        c.lessons = body.lessons;
        log(c, "closure", "Closed: True finding");
        move(c, "Closed", false);
        c.closed_at = now();
        for (const a of c.alert_ids as number[]) caseOf.delete(a);
      }
      return json(route, c);
    }
    return route.fallback();
  });
  return { cases };
}
