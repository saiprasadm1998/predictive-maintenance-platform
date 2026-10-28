import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { ADMIN, ALERTS, fakeApi, sessionRoutes } from "../../test/fakeApi";
import { FakeEventSource } from "../../test/fakeEventSource";
import { renderApp } from "../../test/renderApp";

// jsdom does no layout; the virtualised table needs a viewport to render rows into.
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "clientHeight", {
    configurable: true,
    get: () => 800,
  });
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get: () => 1200,
  });
});
afterAll(() => {
  // back to jsdom's own (inherited from Element)
  Reflect.deleteProperty(HTMLElement.prototype, "clientHeight");
  Reflect.deleteProperty(HTMLElement.prototype, "clientWidth");
});

type Row = Omit<(typeof ALERTS)[number], "shelved_until"> & { shelved_until: string | null };

function routes() {
  const r = sessionRoutes(true);
  let items: Row[] = ALERTS.map((a) => ({ ...a }));
  r["GET /alerts"] = () => ({ status: 200, body: { items, next_cursor: null } });
  r["POST /alerts/ack"] = (call) => {
    const ids = (call.body as { ids: number[] }).ids;
    items = items.map((a) => (ids.includes(a.id) ? { ...a, state: "Active-Acknowledged" } : a));
    return { status: 200, body: items.filter((a) => ids.includes(a.id)) };
  };
  r["POST /alerts/shelve"] = (call) => {
    const { ids } = call.body as { ids: number[] };
    items = items.map((a) =>
      ids.includes(a.id) ? { ...a, state: "Shelved", shelved_until: "2026-10-22T08:00:00Z" } : a,
    );
    return { status: 200, body: items.filter((a) => ids.includes(a.id)) };
  };
  r["GET /priority-matrix"] = () => ({
    status: 200,
    body: [{ criticality: "A", severity: "Alert", priority: "P1" }],
  });
  r["GET /alerts/1"] = () => ({
    status: 200,
    body: {
      ...ALERTS[0],
      trace: {
        cycle: "2026-10-20T00:01:00Z",
        value: 34.6,
        di: 34.6,
        health: 31,
        rule: { kind: "di", warning: 15, alert: 25 },
        inputs: {},
      },
      history: [
        {
          ts: "2026-10-20T00:01:00Z",
          action: "raise",
          from_state: "Normal",
          to_state: "Active-Unacknowledged",
          severity: "Alert",
          priority: "P1",
          user_id: null,
          user: null,
          comment: null,
        },
        {
          ts: "2026-10-20T02:00:00Z",
          action: "acknowledge",
          from_state: "Active-Unacknowledged",
          to_state: "Active-Acknowledged",
          severity: "Alert",
          priority: "P1",
          user_id: 2,
          user: "ann",
          comment: "on it",
        },
      ],
    },
  });
  return { r, setItems: (next: Row[]) => (items = next) };
}

async function page(path = "/alerts") {
  const { r, setItems } = routes();
  const api = fakeApi(r);
  const view = renderApp(path);
  const table = await screen.findByRole("table", { name: "Alerts" });
  await within(table).findAllByRole("checkbox", { name: /Select alert/ });
  return { ...api, ...view, table, setItems, r };
}

describe("SCR-02 alert list", () => {
  it("creates a case from the selected alerts of one asset (analysts)", async () => {
    const { r, setItems } = routes();
    r["GET /auth/me"] = () => ({
      status: 200,
      body: {
        user: { ...ADMIN, roles: [{ role: "analyst", scope_asset_id: null }] },
        csrf_token: "c",
      },
    });
    r["POST /cases"] = () => ({ status: 201, body: { id: 5 } });
    setItems(ALERTS.map((a) => ({ ...a, asset_id: a.asset_code === "K-101" ? 6 : 9 })));
    const { calls } = fakeApi(r);
    const { router } = renderApp("/alerts");
    const user = userEvent.setup();
    const table = await screen.findByRole("table", { name: "Alerts" });
    const rows = await within(table).findAllByRole("checkbox", { name: /Select alert/ });
    const create = screen.getByRole("button", { name: "Create case…" });
    expect(create).toBeDisabled();
    await user.click(rows[0]!);
    await user.click(rows[1]!);
    expect(create).toBeDisabled(); // K-101 and P-104A: one asset per case
    await user.click(rows[1]!);
    await user.click(create);
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Title/), "Thrust bearing suspected");
    await user.click(within(dialog).getByRole("button", { name: "Create case" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/cases/5"));
    expect(calls.find((c) => c.method === "POST" && c.path === "/cases")?.body).toEqual({
      alert_ids: [1],
      title: "Thrust bearing suspected",
    });
  });

  it("shows the PDS columns in the server's order (unacknowledged first, then priority, then age)", async () => {
    const { table } = await page();
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.getAttribute("aria-rowindex"))).toEqual(["2", "3"]);
    expect(rows[0]).toHaveTextContent("P1");
    expect(rows[0]).toHaveTextContent("Active · unack");
    expect(rows[0]).toHaveTextContent("Site A / Ammonia unit / K-101");
    expect(rows[0]).toHaveTextContent("K-101 v1 · DI");
    expect(rows[0]).toHaveTextContent("5 of 5");
    expect(rows[0]).toHaveTextContent("High · 4–10 d"); // forecast urgency (FR-PRG-02)
    expect(rows[1]).toHaveTextContent("P-104A v1 · TI1044");
    expect(
      within(rows[0]!).getByRole("link", { name: "Site A / Ammonia unit / K-101" }),
    ).toHaveAttribute("href", "/assets/6?alert=1");
  });

  it("puts filters in the URL and asks the API for them", async () => {
    const { router, calls } = await page();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Priority: All/ }));
    await user.click(await screen.findByRole("checkbox", { name: "P1" }));
    expect(new URLSearchParams(router.state.location.search).getAll("priority")).toEqual(["P1"]);
    await waitFor(() =>
      expect(
        calls.some((c) => c.path === "/alerts" && c.query.getAll("priority").includes("P1")),
      ).toBe(true),
    );
  });

  it("acknowledges the selection after confirmation", async () => {
    const { calls, table } = await page();
    const user = userEvent.setup();
    await user.click(within(table).getByRole("checkbox", { name: "Select alert 1 on K-101" }));
    await user.click(screen.getByRole("button", { name: "Acknowledge" }));
    const dialog = screen.getByRole("dialog", { name: "Acknowledge 1 alert" });
    await user.click(within(dialog).getByRole("button", { name: "Acknowledge" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/alerts/ack")?.body).toEqual({
        ids: [1],
        comment: null,
      }),
    );
    await waitFor(() =>
      expect(within(table).getAllByRole("row")[1]).toHaveTextContent("Active · ack"),
    );
  });

  it("shelves only with a reason, for the chosen time", async () => {
    const { calls, table } = await page();
    const user = userEvent.setup();
    await user.click(within(table).getByRole("checkbox", { name: "Select all alerts shown" }));
    await user.click(screen.getByRole("button", { name: "Shelve…" }));
    const dialog = screen.getByRole("dialog", { name: "Shelve 2 alerts" });
    const confirm = within(dialog).getByRole("button", { name: "Shelve" });
    expect(confirm).toBeDisabled();
    await user.selectOptions(within(dialog).getByLabelText("For"), "1440");
    await user.type(within(dialog).getByLabelText(/Reason/), "valve work on P-104A");
    await user.click(confirm);
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/alerts/shelve")?.body).toEqual({
        ids: [1, 7],
        reason: "valve work on P-104A",
        minutes: 1440,
      }),
    );
  });

  it("shows new alerts behind a button instead of re-sorting under the user", async () => {
    const { setItems, table } = await page();
    const stream = FakeEventSource.latest();
    act(() => stream.open());
    setItems([
      { ...ALERTS[1]!, id: 99, asset_code: "K-201", asset_path: "Site A / Urea unit / K-201" },
      ...ALERTS,
    ]);
    act(() =>
      stream.emit("alert.changed", {
        type: "alert.changed",
        alert_id: 99,
        model_id: 5,
        state: "Active-Unacknowledged",
      }),
    );
    const show = await screen.findByRole(
      "button",
      { name: "1 new alert · show" },
      { timeout: 3000 },
    );
    expect(within(table).getAllByRole("row")).toHaveLength(3); // still the two it showed
    await userEvent.setup().click(show);
    await waitFor(() =>
      expect(
        within(screen.getByRole("table", { name: "Alerts" })).getAllByRole("row"),
      ).toHaveLength(4),
    );
  });

  it("opens an alert's details with what it was based on and its history", async () => {
    const { router } = await page("/alerts?alert=1");
    const panel = await screen.findByRole("complementary", { name: "Alert 1" });
    expect(await within(panel).findByText(/Deviation Index/)).toHaveTextContent(
      "34.6 against warning 15 and alert 25",
    );
    const history = within(panel).getAllByRole("listitem");
    expect(history[1]).toHaveTextContent("Acknowledged");
    expect(history[1]).toHaveTextContent("ann");
    expect(history[1]).toHaveTextContent("“on it”");
    await userEvent
      .setup()
      .click(within(panel).getByRole("button", { name: "Close the alert details" }));
    expect(new URLSearchParams(router.state.location.search).has("alert")).toBe(false);
  });

  it("saves the current filter for this user", async () => {
    await page("/alerts?priority=P1");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Save filter" }));
    await user.type(screen.getByRole("textbox", { name: "Name for this filter" }), "My P1s");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(JSON.parse(localStorage.getItem("pmp.alertFilters.admin")!)).toEqual([
      { name: "My P1s", query: "priority=P1" },
    ]);
    expect(
      within(screen.getByRole("combobox", { name: "Saved filters" })).getByRole("option", {
        name: "My P1s",
      }),
    ).toBeInTheDocument();
  });
});
