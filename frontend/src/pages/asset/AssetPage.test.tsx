import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ALERTS, MODELS, TREE, fakeApi, sessionRoutes } from "../../test/fakeApi";
import { renderApp } from "../../test/renderApp";

vi.mock("../../components/charting", () => ({
  echarts: {
    init: vi.fn(() => ({
      setOption: vi.fn(),
      dispatchAction: vi.fn(),
      resize: vi.fn(),
      dispose: vi.fn(),
      on: vi.fn(),
      off: vi.fn(),
      getZr: () => ({ on: vi.fn(), off: vi.fn() }),
    })),
    connect: vi.fn(),
  },
  chartColors: () => ({}),
}));

const K101 = (TREE[0]!.children as { children: object[] }[])[0]!.children[0]!;

function sensor(
  id: number,
  name: string,
  description: string,
  z: number,
  contribution: number,
  extra = {},
) {
  return {
    tag_id: id,
    source_name: name,
    description,
    unit: "°C",
    required: false,
    actual: 78.4,
    predicted: 71.2,
    residual: 7.2,
    z,
    contribution,
    dq_status: "Good",
    dq_rule: "none",
    used: true,
    sigma: 2.3,
    warning: 3,
    alert: 5,
    ...extra,
  };
}

function trend(name: string) {
  return {
    tag_id: 1,
    source_name: name,
    start: "2026-10-14T00:00:00Z",
    end: "2026-10-21T00:00:00Z",
    raw: false,
    bucket_s: 3600,
    source: "raw",
    ts: ["2026-10-20T00:00:00Z"],
    min: { actual: [70], predicted: [70], di: [30], health: [40] },
    max: { actual: [72], predicted: [70], di: [36], health: [41] },
  };
}

function routes() {
  const r = sessionRoutes(true);
  r["GET /assets/6"] = () => ({
    status: 200,
    body: {
      id: 6,
      code: "K-101",
      name: "Syngas compressor K-101",
      level: "equipment",
      parent_id: 5,
      criticality: "A",
      asset_type: null,
      description: "",
      ancestors: [
        { id: 1, code: "DEMO", name: "Demo enterprise" },
        { id: 5, code: "SA-AMM", name: "Ammonia unit" },
      ],
      health: K101,
    },
  });
  r["GET /models/1"] = () => ({
    status: 200,
    body: {
      ...MODELS[0],
      versions: [
        {
          id: 1,
          version: 1,
          status: "Superseded",
          algorithm: "median",
          created_at: "2026-09-01T00:00:00Z",
          sensors: [],
          params: { cycle_s: 60 },
          error: null,
        },
        {
          id: 2,
          version: 2,
          status: "Deployed",
          algorithm: "median",
          created_at: "2026-10-01T00:00:00Z",
          sensors: [],
          params: { cycle_s: 60 },
          error: null,
        },
      ],
      alert_rules: [
        { id: 1, kind: "di", tag_id: null, warning: 15, alert: 25, state: "Active-Unacknowledged" },
      ],
    },
  });
  r["GET /models/1/latest"] = () => ({
    status: 200,
    body: {
      version_id: 2,
      version: 2,
      ts: "2026-10-21T08:15:00Z",
      sensors: [
        sensor(11, "K101.TI1012.PV", "TI-1012 DE bearing temperature", 3.1, 0.46),
        sensor(12, "K101.ZI1015.PV", "ZI-1015 Axial displacement", 2.0, 0.21),
        sensor(13, "K101.TI1018.PV", "TI-1018 NDE bearing temperature", -0.1, 0, {
          dq_status: "Failure",
          dq_rule: "flatline",
          used: false,
        }),
      ],
    },
  });
  r["GET /models/1/scores"] = () => ({ status: 200, body: trend("di") });
  r["GET /models/1/status-periods"] = () => ({ status: 200, body: [] });
  r["GET /models/1/outputs"] = (call) => ({
    status: 200,
    body: (call.query.get("tags") ?? "").split(",").filter(Boolean).map(trend),
  });
  r["POST /alerts/ack"] = (call) => ({
    status: 200,
    body: (call.body as { ids: number[] }).ids.map((id) => ({ ...ALERTS[0], id })),
  });
  return r;
}

describe("SCR-03 asset analysis", () => {
  it("summarises the asset, its model and its worst alert", async () => {
    fakeApi(routes());
    renderApp("/assets/6?range=7d");
    const summary = await screen.findByRole("region", { name: "Syngas compressor K-101" });
    expect(await within(summary).findByText("K-101 / main v2 · median")).toBeInTheDocument();
    expect(within(summary).getByText("2 / 3 sensors")).toBeInTheDocument();
    expect(within(summary).getByText("P1 · active · unack")).toBeInTheDocument();
    expect(within(summary).getByText("ALERT · DI 36.2 %")).toBeInTheDocument();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Ammonia unit" })).toHaveAttribute(
      "href",
      "/units/5?range=7d",
    );
  });

  it("lists the top contributors and charts the first two", async () => {
    const { calls } = fakeApi(routes());
    renderApp("/assets/6");
    const contributors = await screen.findByRole("region", { name: "Top contributors now" });
    const first = await within(contributors).findByRole("button", {
      name: /TI-1012 DE bearing temperature/,
    });
    expect(first).toHaveAttribute("aria-pressed", "true");
    expect(first).toHaveTextContent("46 %");
    expect(first).toHaveTextContent("+3.1σ");
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/models/1/outputs")?.query.get("tags")).toBe(
        "K101.TI1012.PV,K101.ZI1015.PV",
      ),
    );
    expect(
      await screen.findByRole("figure", { name: /TI-1012 DE bearing temperature: actual/ }),
    ).toBeInTheDocument();
  });

  it("shows the sensor table with NE 107 status and charts a sensor from it", async () => {
    const { router } = (() => {
      fakeApi(routes());
      return renderApp("/assets/6");
    })();
    const user = userEvent.setup();
    const table = await screen.findByRole("table", { name: /Sensors at the latest cycle/ });
    const flat = (await within(table).findByText("TI-1018 NDE bearing temperature")).closest("tr")!;
    expect(flat).toHaveTextContent("Failure: flatline");
    await user.click(
      within(flat).getByRole("button", { name: "Chart TI-1018 NDE bearing temperature" }),
    );
    expect(new URLSearchParams(router.state.location.search).get("sensors")).toBe(
      "K101.TI1012.PV,K101.ZI1015.PV,K101.TI1018.PV",
    );
  });

  it("acknowledges the open alerts after confirmation, with an optional comment", async () => {
    const { calls } = fakeApi(routes());
    renderApp("/assets/6");
    const user = userEvent.setup();
    const button = await screen.findByRole("button", { name: /^Acknowledge \(2\)/ });
    await user.click(button);
    const dialog = screen.getByRole("dialog", { name: "Acknowledge 2 alerts on K-101" });
    await user.type(within(dialog).getByLabelText(/Comment/), "seen, monitoring");
    await user.click(within(dialog).getByRole("button", { name: "Acknowledge" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/alerts/ack")?.body).toEqual({
        ids: [1, 7],
        comment: "seen, monitoring",
      }),
    );
    expect(calls.find((c) => c.path === "/alerts/ack")?.headers["X-CSRF-Token"]).toBe("csrf-1");
  });

  it("compares one version from the summary", async () => {
    const { calls } = fakeApi(routes());
    const { router } = renderApp("/assets/6");
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Compare version"), "1");
    expect(new URLSearchParams(router.state.location.search).get("version")).toBe("1");
    await waitFor(() =>
      expect(
        calls.some((c) => c.path === "/models/1/scores" && c.query.get("version") === "1"),
      ).toBe(true),
    );
  });

  it("opens an alert link on the alert's window", async () => {
    fakeApi(routes());
    const { router } = renderApp("/assets/6?alert=1");
    await waitFor(() =>
      expect(new URLSearchParams(router.state.location.search).get("from")).toBe(
        "2026-10-19T12:01:00.000Z",
      ),
    );
  });
});
