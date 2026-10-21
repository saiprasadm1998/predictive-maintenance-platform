import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { KPIS, TREE, fakeApi, sessionRoutes } from "../../test/fakeApi";
import { FakeEventSource } from "../../test/fakeEventSource";
import { renderApp } from "../../test/renderApp";

async function fleet(path = "/fleet", routes = sessionRoutes(true)) {
  const api = fakeApi(routes);
  const view = renderApp(path);
  await screen.findByRole("table");
  return { ...api, ...view, routes };
}

describe("SCR-01 fleet overview", () => {
  it("shows the fleet figures with shapes, from the API", async () => {
    await fleet();
    const figures = screen.getByRole("list", { name: "Fleet figures" });
    expect(within(figures).getByRole("link", { name: /7\s*Models running/ })).toHaveAttribute(
      "href",
      "/models",
    );
    expect(
      within(figures).getByRole("button", { name: /2\s*Assets in Alert/ }),
    ).toBeInTheDocument();
    expect(within(figures).getByRole("link", { name: /5\s*Sensor faults/ })).toHaveAttribute(
      "href",
      "/sensors?status=Failure",
    );
    expect(within(figures).getByText("Cases arrive in Release 2")).toBeInTheDocument();
  });

  it("shows the hierarchy with type, band, Health and alerts, abnormal branches open", async () => {
    await fleet();
    const table = screen.getByRole("table");
    const k101 = within(table)
      .getByRole("link", { name: "Syngas compressor K-101" })
      .closest("tr")!;
    expect(within(k101).getByText("Centrifugal compressor")).toBeInTheDocument();
    expect(within(k101).getByText("ALERT")).toBeInTheDocument();
    expect(within(k101).getByRole("meter", { name: /Health of/ })).toHaveAttribute(
      "aria-valuenow",
      "28",
    );
    expect(within(k101).getByText("3")).toBeInTheDocument();
    expect(within(table).queryByText("Waste-heat boiler E-110")).not.toBeInTheDocument(); // healthy: closed
    const p202 = within(table).getByRole("link", { name: "Carbamate pump P-202" }).closest("tr")!;
    expect(p202).toHaveTextContent("— Insufficient data: Required sensor not usable");
  });

  it("opens and closes branches from the keyboard", async () => {
    await fleet();
    const user = userEvent.setup();
    const toggle = screen.getByRole("button", { name: "Expand Utilities" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(
      within(screen.getByRole("table")).getByRole("link", { name: "Waste-heat boiler E-110" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Collapse Utilities" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("filters to a band from its figure, in the URL", async () => {
    const { router } = await fleet();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Assets in Watch/ }));
    expect(router.state.location.search).toBe("?band=Watch");
    const table = screen.getByRole("table");
    expect(within(table).getByRole("link", { name: "BFW pump P-104A" })).toBeInTheDocument();
    expect(
      within(table).queryByRole("link", { name: "Syngas compressor K-101" }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show all" }));
    expect(router.state.location.search).toBe("");
  });

  it("lists the highest deviations and the latest alerts", async () => {
    await fleet();
    const deviations = screen.getByRole("region", { name: "Highest deviation now" });
    const items = within(deviations)
      .getAllByRole("listitem")
      .map((li) => li.textContent);
    expect(items[0]).toContain("Syngas compressor K-101");
    expect(items[0]).toContain("DI 36.2 %");
    const recent = screen.getByRole("region", { name: "Recent alerts" });
    const first = within(recent).getAllByRole("listitem")[0]!;
    expect(first).toHaveTextContent("P3");
    expect(within(first).getByRole("link", { name: "P-104A TI1044 residual" })).toHaveAttribute(
      "href",
      "/alerts?alert=7",
    );
  });

  it("warns when models have stopped scoring", async () => {
    const routes = sessionRoutes(true);
    routes["GET /fleet/kpis"] = () => ({ status: 200, body: { ...KPIS, stale_models: [1, 2] } });
    await fleet("/fleet", routes);
    expect(await screen.findByText(/No new scores/)).toBeInTheDocument();
    expect(screen.getByText(/K-101 \/ main, P-104A \/ main/)).toBeInTheDocument();
  });

  it("opens equipment on asset analysis and a unit on the unit view, keeping the time range", async () => {
    const { router } = await fleet("/fleet?range=24h");
    const user = userEvent.setup();
    expect(screen.getByRole("link", { name: "Ammonia unit" })).toHaveAttribute(
      "href",
      "/units/5?range=24h",
    );
    await user.click(
      within(screen.getByRole("table")).getByRole("link", { name: "BFW pump P-104A" }),
    );
    expect(router.state.location.pathname).toBe("/assets/7");
  });

  it("highlights a row whose figures change live", async () => {
    const { routes } = await fleet();
    const stream = FakeEventSource.latest();
    act(() => stream.open());
    const changed = structuredClone(TREE) as unknown as {
      children: { children: { health: number }[] }[];
    }[];
    changed[0]!.children[0]!.children[1]!.health = 55;
    routes["GET /assets"] = () => ({ status: 200, body: changed });
    act(() =>
      stream.emit("score.updated", {
        type: "score.updated",
        model_id: 2,
        ts: "2026-10-21T08:16:00Z",
      }),
    );
    await waitFor(
      () =>
        expect(
          within(screen.getByRole("table"))
            .getByRole("link", { name: "BFW pump P-104A" })
            .closest("tr"),
        ).toHaveClass("row-flash"),
      { timeout: 3000 },
    );
  });

  it("explains an empty hierarchy", async () => {
    const routes = sessionRoutes(true);
    routes["GET /assets"] = () => ({ status: 200, body: [] });
    fakeApi(routes);
    renderApp("/fleet");
    expect(await screen.findByText(/The plant hierarchy is empty/)).toBeInTheDocument();
  });
});
