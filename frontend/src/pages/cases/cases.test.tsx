import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { CaseDetail, CaseSummary } from "../../api/cases";
import { ADMIN, type Call, fakeApi, sessionRoutes } from "../../test/fakeApi";
import { renderApp } from "../../test/renderApp";
import {
  activityText,
  canWorkOn,
  caseBlocker,
  dueText,
  readCaseFilter,
  transitionLabel,
  writeCaseFilter,
} from "./caseModel";

vi.mock("../../components/charting", () => ({
  echarts: {
    init: vi.fn(() => ({
      setOption: vi.fn(),
      dispatchAction: vi.fn(),
      resize: vi.fn(),
      dispose: vi.fn(),
      on: vi.fn(),
      off: vi.fn(),
      isDisposed: () => false,
      getZr: () => ({ on: vi.fn(), off: vi.fn() }),
    })),
    connect: vi.fn(),
  },
  chartColors: () => ({}),
}));

function user(role: string, id = 1) {
  return { ...ADMIN, id, roles: [{ role, scope_asset_id: null }] };
}

const SUMMARY: CaseSummary = {
  id: 14,
  number: "C-0014",
  title: "K-101 thrust bearing degradation suspected",
  status: "Investigating",
  priority: "P1",
  asset_id: 6,
  asset_code: "K-101",
  asset_path: "Site A / Ammonia unit / K-101",
  assignee_id: 3,
  assignee: "Max",
  due: "2026-10-12",
  overdue: true,
  outcome: null,
  review_requested: false,
  alert_ids: [1],
  created_at: "2026-10-08T19:31:00Z",
  updated_at: "2026-10-09T10:30:00Z",
  closed_at: null,
};

const DETAIL: CaseDetail = {
  ...SUMMARY,
  priority_set: false,
  confirmed_mode_id: null,
  value_estimate: null,
  lessons: null,
  cancel_reason: null,
  created_by: 2,
  snapshot: {
    taken_at: "2026-10-08T19:31:00Z",
    alerts: [
      {
        id: 1,
        model_id: 1,
        kind: "di",
        tag: null,
        state: "Active-Unacknowledged",
        severity: "Alert",
        priority: "P1",
        raised_at: "2026-10-08T19:00:00Z",
      },
    ],
    models: [
      {
        model_id: 1,
        model: "main",
        asset_code: "K-101",
        version: 3,
        at: "2026-10-08T19:30:00Z",
        limits: { warning: 15, alert: 25 },
        trend: {
          ts: ["2026-10-08T18:00:00Z", "2026-10-08T19:00:00Z"],
          di: [20, 29.5],
          health: [60, 41],
        },
        sensors: [
          {
            tag_id: 4,
            source_name: "K101.TI1012.PV",
            actual: 88,
            predicted: 80,
            z: 3.1,
            contribution: 46,
            dq_status: "Good",
            dq_rule: null,
            used: true,
          },
          {
            tag_id: 5,
            source_name: "K101.TI1016.PV",
            actual: null,
            predicted: null,
            z: null,
            contribution: null,
            dq_status: "Failure",
            dq_rule: "flatline",
            used: false,
          },
        ],
        diagnosis: [
          {
            code: "thrust_bearing_degradation",
            name: "Thrust bearing degradation",
            version: 1,
            score: 78,
            insufficient_evidence: false,
          },
        ],
        forecast: {
          id: 9,
          target: "di",
          tag: null,
          threshold: 25,
          urgency: "High",
          median_h: 156,
          lower_h: 96,
          upper_h: 216,
          valid: true,
          at: "2026-10-08T19:30:00Z",
        },
      },
    ],
  },
  activities: [
    {
      id: 1,
      ts: "2026-10-08T19:31:00Z",
      type: "created",
      author_id: 2,
      author: "Ana",
      body: "Case created from alert 1 (P1). Snapshot attached.",
      data: {},
      attachment_id: null,
    },
    {
      id: 2,
      ts: "2026-10-08T20:05:00Z",
      type: "state_change",
      author_id: 2,
      author: "Ana",
      body: "",
      data: { from: "Open", to: "Investigating", automatic: true },
      attachment_id: null,
    },
  ],
  actions: [],
  attachments: [],
};

function routes(role: string, detail: CaseDetail = DETAIL, me = 2) {
  const r = sessionRoutes(true);
  r["GET /auth/me"] = () => ({ status: 200, body: { user: user(role, me), csrf_token: "c" } });
  let current = detail;
  r["GET /cases"] = () => ({
    status: 200,
    body: [
      SUMMARY,
      {
        ...SUMMARY,
        id: 15,
        number: "C-0015",
        overdue: false,
        status: "Closed",
        outcome: "false_alert",
        review_requested: true,
      },
    ],
  });
  r["GET /cases/14"] = () => ({ status: 200, body: current });
  r["GET /cases/14/people"] = () => ({
    status: 200,
    body: [
      { id: 2, username: "ana", display_name: "Ana", roles: ["analyst"] },
      { id: 3, username: "max", display_name: "Max", roles: ["maintenance"] },
    ],
  });
  r["GET /assets/6"] = () => ({
    status: 200,
    body: { id: 6, asset_type: "centrifugal_compressor" },
  });
  r["GET /library"] = () => ({
    status: 200,
    body: [{ id: 26, name: "Thrust bearing degradation" }],
  });
  r["POST /cases/14/activities"] = (call) => {
    const body = call.body as { type: string; body: string };
    current = {
      ...current,
      status: body.type === "action" ? "Action required" : current.status,
      actions:
        body.type === "action"
          ? [
              {
                id: 7,
                description: body.body,
                owner_id: 3,
                owner: "Max",
                due: null,
                status: "open",
                created_at: "2026-10-09T10:30:00Z",
                done_at: null,
              },
            ]
          : current.actions,
    };
    return { status: 201, body: current };
  };
  r["POST /cases/14/actions/7/done"] = () => {
    current = {
      ...current,
      status: "Monitoring",
      actions: current.actions.map((a) => ({ ...a, status: "done" as const })),
    };
    return { status: 200, body: current };
  };
  r["POST /cases/14/close"] = (call) => {
    current = {
      ...current,
      status: "Closed",
      outcome: (call.body as { outcome: "true_finding" }).outcome,
      confirmed_mode_id: 26,
    };
    return { status: 200, body: current };
  };
  return r;
}

describe("case rules", () => {
  it("words states, dates and activities as the wireframe does", () => {
    expect(dueText({ due: "2026-10-12", overdue: false })).toBe("12-Oct");
    expect(dueText({ due: "2026-10-12", overdue: true })).toBe("12-Oct (overdue)");
    expect(transitionLabel("Action required", "Monitoring")).toBe(
      "Condition worsened: action required",
    );
    expect(transitionLabel("Cancelled", "Open")).toBe("Cancel case…");
    expect(activityText(DETAIL.activities[1]!)).toBe("Status: Open → Investigating (automatic)");
  });

  it("lets only the right people create and work on cases", () => {
    expect(canWorkOn(user("analyst"), SUMMARY)).toBe(true);
    expect(canWorkOn(user("maintenance", 3), SUMMARY)).toBe(true); // assigned to them
    expect(canWorkOn(user("maintenance", 4), SUMMARY)).toBe(false);
    expect(canWorkOn(user("viewer"), SUMMARY)).toBe(false);
    expect(caseBlocker([])).toBe("Select the alerts first.");
    expect(caseBlocker([{ asset_id: 1 }, { asset_id: 2 }])).toMatch(/one asset/);
    expect(caseBlocker([{ asset_id: 1, case_number: "C-0003" }])).toMatch(/C-0003/);
    expect(caseBlocker([{ asset_id: 1 }, { asset_id: 1 }])).toBeNull();
  });

  it("keeps the list filter in the URL", () => {
    const params = writeCaseFilter(new URLSearchParams("range=24h"), {
      open_only: true,
      mine: true,
      outcome: "false_alert",
    });
    expect(params.toString()).toBe("range=24h&open_only=true&mine=true&outcome=false_alert");
    expect(readCaseFilter(params)).toMatchObject({
      open_only: true,
      mine: true,
      outcome: "false_alert",
    });
  });
});

describe("SCR-09 case list", () => {
  it("lists cases with overdue highlighted and filters through the URL", async () => {
    const { calls } = fakeApi(routes("viewer"));
    const u = userEvent.setup();
    const { router } = renderApp("/cases?open_only=true");
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("C-0014");
    expect(rows[0]).toHaveClass("row-overdue");
    expect(rows[0]).toHaveTextContent("12-Oct (overdue)");
    expect(rows[1]).toHaveTextContent("False alert · model review");
    expect(screen.getByRole("heading", { name: /Cases · 2 · 1 overdue/ })).toBeInTheDocument();
    expect(calls.at(-1)?.query.get("open_only")).toBe("true");
    await u.click(screen.getByLabelText("Assigned to me"));
    await waitFor(() => expect(router.state.location.search).toContain("mine=true"));
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/cases" && c.query.get("mine") === "true")).toBe(true),
    );
  });
});

describe("SCR-05 case detail", () => {
  it("shows the stepper, log, linked alerts and the snapshot as created", async () => {
    fakeApi(routes("viewer"));
    renderApp("/cases/14");
    expect(
      await screen.findByRole("heading", {
        name: "C-0014 · K-101 thrust bearing degradation suspected",
      }),
    ).toBeInTheDocument();
    const stepper = screen.getByRole("list", { name: "Case status" });
    expect(within(stepper).getByText("Investigating").closest("li")).toHaveAttribute(
      "aria-current",
      "step",
    );
    expect(screen.getByText("Status: Open → Investigating (automatic)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Alert 1" })).toHaveAttribute(
      "href",
      "/assets/6?alert=1",
    );
    const snapshot = screen.getByRole("region", { name: "Snapshot at creation" });
    expect(
      within(snapshot).getByRole("figure", { name: /DI trend \(snapshot\)/ }),
    ).toBeInTheDocument();
    expect(within(snapshot).getByText("K101.TI1012.PV")).toBeInTheDocument();
    expect(within(snapshot).getByText("78 %")).toBeInTheDocument();
    expect(within(snapshot).getByText("High · 4–9 d (median 6.5 d) to 25")).toBeInTheDocument();
    expect(within(snapshot).getByText("K101.TI1016.PV: Failure (flatline)")).toBeInTheDocument();
    // a viewer reads but cannot act
    expect(screen.getByLabelText("Priority")).toBeDisabled();
    expect(screen.queryByRole("form", { name: "Add activity" })).toBeNull();
    expect(screen.queryByRole("form", { name: "Close case" })).toBeNull();
  });

  it("assigns the case to someone who can work on it", async () => {
    const r = routes("analyst", { ...DETAIL, status: "Open", assignee_id: null, assignee: null });
    r["PATCH /cases/14"] = () => ({
      status: 200,
      body: { ...DETAIL, assignee_id: 3, assignee: "Max" },
    });
    const { calls } = fakeApi(r);
    const u = userEvent.setup();
    renderApp("/cases/14");
    const assignee = await screen.findByLabelText("Assignee");
    await within(assignee).findByRole("option", { name: "Max" });
    await u.selectOptions(assignee, "3");
    await waitFor(() =>
      expect(calls.find((c: Call) => c.method === "PATCH")?.body).toEqual({ assignee_id: 3 }),
    );
  });

  it("acts and closes with the confirmed mode of a true finding", async () => {
    const { calls } = fakeApi(routes("analyst"));
    const u = userEvent.setup();
    renderApp("/cases/14");
    const form = await screen.findByRole("form", { name: "Add activity" });
    await u.click(within(form).getByLabelText("Action"));
    await u.type(within(form).getByRole("textbox"), "Reduce load to 85 %");
    await u.selectOptions(within(form).getByLabelText("Owner"), "3");
    await u.click(within(form).getByRole("button", { name: "Add action" }));
    await waitFor(() =>
      expect(calls.find((c: Call) => c.path === "/cases/14/activities")?.body).toEqual({
        type: "action",
        body: "Reduce load to 85 %",
        owner_id: 3,
        due: null,
      }),
    );
    await u.click(await screen.findByRole("button", { name: "Mark done" }));
    const stepper = screen.getByRole("list", { name: "Case status" });
    await waitFor(() =>
      expect(within(stepper).getByText("Monitoring").closest("li")).toHaveAttribute(
        "aria-current",
        "step",
      ),
    );

    const closure = screen.getByRole("form", { name: "Close case" });
    const close = within(closure).getByRole("button", { name: "Close case" });
    await u.selectOptions(within(closure).getByLabelText("Outcome"), "true_finding");
    expect(close).toBeDisabled(); // a true finding needs its confirmed mode
    await within(closure).findByRole("option", { name: "Thrust bearing degradation" });
    await u.selectOptions(within(closure).getByLabelText(/Confirmed mode/), "26");
    await u.type(within(closure).getByLabelText(/Lessons learned/), "Check oil weekly");
    await u.click(close);
    await waitFor(() =>
      expect(calls.find((c: Call) => c.path === "/cases/14/close")?.body).toEqual({
        outcome: "true_finding",
        confirmed_mode_id: 26,
        value_estimate: null,
        lessons: "Check oil weekly",
      }),
    );
    expect(await screen.findByText("True finding")).toBeInTheDocument();
  });
});
