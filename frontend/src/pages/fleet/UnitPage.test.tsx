import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TREE, fakeApi, sessionRoutes } from "../../test/fakeApi";
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
      isDisposed: () => false,
      getZr: () => ({ on: vi.fn(), off: vi.fn() }),
    })),
    connect: vi.fn(),
  },
  chartColors: () => ({}),
}));

const UNIT = (TREE[0]!.children as (typeof TREE)[number][])[0]!;

function scores(values: (number | null)[]) {
  return {
    start: "2026-10-14T00:00:00Z",
    end: "2026-10-21T00:00:00Z",
    raw: false,
    bucket_s: 7200,
    source: "raw",
    ts: values.map((_, i) => new Date(Date.UTC(2026, 9, 14) + i * 7_200_000).toISOString()),
    min: { di: values, health: values },
    max: { di: values, health: values },
  };
}

describe("SCR-08 area / unit view", () => {
  it("shows a card per monitored asset with band, Health, DI sparkline and alerts", async () => {
    const routes = sessionRoutes(true);
    routes["GET /assets/5"] = () => ({
      status: 200,
      body: {
        id: 5,
        code: "SA-AMM",
        name: "Ammonia unit",
        level: "unit",
        parent_id: 1,
        criticality: null,
        asset_type: null,
        description: "",
        ancestors: [{ id: 1, code: "DEMO", name: "Demo enterprise" }],
        health: UNIT,
      },
    });
    routes["GET /models/1/scores"] = () => ({ status: 200, body: scores([10, 20, 30, 36.2]) });
    routes["GET /models/2/scores"] = () => ({ status: 200, body: scores([12, 15, 19.1]) });
    routes["GET /models/3/scores"] = () => ({ status: 200, body: scores([null, null]) });
    const { calls } = fakeApi(routes);
    renderApp("/units/5?range=24h");

    const cards = await screen.findByRole("list", { name: "Assets" });
    const k101 = within(cards)
      .getByRole("link", { name: "Syngas compressor K-101" })
      .closest("li")!;
    expect(k101).toHaveAttribute("class", expect.stringContaining("card"));
    expect(within(k101).getByText("ALERT")).toBeInTheDocument();
    expect(
      await within(k101).findByRole("img", { name: /K-101 Deviation Index, last 7 days/ }),
    ).toHaveAccessibleName(
      "K-101 Deviation Index, last 7 days (%): from 10.0 to 36.2, highest 36.2",
    );
    expect(k101).toHaveTextContent("3 open alerts");
    const p202 = within(cards).getByRole("link", { name: "Carbamate pump P-202" }).closest("li")!;
    expect(await within(p202).findByText("no data")).toBeInTheDocument();
    expect(p202).toHaveTextContent("Unknown — Insufficient data");

    // breadcrumb from the hierarchy, and the unit's alert history for the period
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Demo enterprise" })).toHaveAttribute(
      "href",
      "/units/1?range=24h",
    );
    expect(within(crumbs).getByRole("heading", { name: "Ammonia unit" })).toBeInTheDocument();
    const alertRead = calls.find((c) => c.path === "/alerts" && c.query.get("asset") === "SA-AMM");
    expect(alertRead?.query.get("include_closed")).toBe("true");
    expect(screen.getByRole("figure", { name: "Open alerts in Ammonia unit" })).toBeInTheDocument();
  });
});
