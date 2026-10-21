import { describe, expect, it } from "vitest";

import type { Alert } from "../../api/types";
import { ALERTS } from "../../test/fakeApi";
import {
  allowed,
  liveView,
  loadSaved,
  menuLabel,
  modelText,
  persistenceText,
  readFilter,
  storeSaved,
  toApiFilter,
  writeFilter,
} from "./alertsModel";

const base = ALERTS[0] as unknown as Alert;
const alert = (extra: Partial<Alert>): Alert => ({ ...base, ...extra });

describe("filters in the URL", () => {
  it("reads, ignores unknown values and writes back without touching other parameters", () => {
    const params = new URLSearchParams(
      "state=Shelved&state=Bogus&priority=P1&severity=Alert&kind=sensor&scope=SA-AMM&closed=true&range=24h",
    );
    const filter = readFilter(params);
    expect(filter).toEqual({
      scope: "SA-AMM",
      states: ["Shelved"],
      priorities: ["P1"],
      severities: ["Alert"],
      kind: "sensor",
      closed: true,
    });
    const written = writeFilter(params, { ...filter, priorities: [], closed: false });
    expect(written.get("range")).toBe("24h");
    expect(written.getAll("priority")).toEqual([]);
    expect(written.has("closed")).toBe(false);
    expect(toApiFilter(filter)).toMatchObject({
      asset: "SA-AMM",
      includeClosed: true,
      kind: "sensor",
    });
  });

  it("labels a filter button as the wireframe does", () => {
    expect(menuLabel("Priority", [])).toBe("Priority: All");
    expect(
      menuLabel(
        "State",
        ["Active-Unacknowledged", "Shelved"],
        new Map([["Active-Unacknowledged", "Active · unack"]]),
      ),
    ).toBe("State: Active · unack, Shelved");
  });

  it("keeps saved filters per user", () => {
    storeSaved("ann", [{ name: "My P1s", query: "priority=P1" }]);
    expect(loadSaved("ann")).toEqual([{ name: "My P1s", query: "priority=P1" }]);
    expect(loadSaved("bob")).toEqual([]);
    localStorage.setItem("pmp.alertFilters.eve", "not json");
    expect(loadSaved("eve")).toEqual([]);
  });
});

describe("live updates (PDS §6)", () => {
  it("keeps the shown order, refreshes values and counts new alerts", () => {
    const a = alert({ id: 1 });
    const b = alert({ id: 2 });
    const c = alert({ id: 3 });
    const fresh = [c, alert({ id: 2, state: "Active-Acknowledged" }), a];
    const view = liveView(fresh, [1, 2]);
    expect(view.rows.map((r) => r.id)).toEqual([1, 2]);
    expect(view.rows[1]!.state).toBe("Active-Acknowledged");
    expect(view.incoming).toBe(1);
    expect(liveView([b, a], null).rows.map((r) => r.id)).toEqual([2, 1]);
  });
});

describe("rows and actions", () => {
  it("shows persistence, but not while shelved or out of service", () => {
    expect(persistenceText(alert({ persistence_n: 4, persistence_m: 5 }))).toBe("4 of 5");
    expect(persistenceText(alert({ state: "Shelved" }))).toBe("—");
    expect(persistenceText(alert({ persistence_n: null }))).toBe("—");
  });

  it("names the model, version and rule", () => {
    expect(modelText(alert({ kind: "sensor", tag: "P104A.TI1044.PV", version: 3 }))).toBe(
      "K-101 v3 · TI1044",
    );
    expect(modelText(alert({ kind: "di", version: 1 }))).toBe("K-101 v1 · DI");
  });

  it("allows an action only if it suits every selected alert", () => {
    const unack = alert({ state: "Active-Unacknowledged" });
    const acked = alert({ state: "Active-Acknowledged" });
    const shelved = alert({ state: "Shelved" });
    expect(allowed([unack])).toEqual({ ack: true, shelve: true, unshelve: false });
    expect(allowed([unack, acked])).toEqual({ ack: false, shelve: true, unshelve: false });
    expect(allowed([shelved])).toEqual({ ack: false, shelve: false, unshelve: true });
    expect(allowed([])).toEqual({ ack: false, shelve: false, unshelve: false });
  });
});
