import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { SensorHealth } from "../../api/admin";
import { ADMIN, type Call, fakeApi, sessionRoutes } from "../../test/fakeApi";
import { renderApp } from "../../test/renderApp";
import { figures, listed, ruleOrReason, scoringUse } from "./sensorsModel";

const NOW = new Date("2026-10-22T08:00:00Z");

function sensor(
  id: number,
  name: string,
  status: string,
  rule: string,
  extra: Partial<SensorHealth> = {},
): SensorHealth {
  return {
    tag_id: id,
    source: "gw",
    source_name: name,
    asset_code: "K-101",
    status,
    rule,
    effect: status === "Good" ? "used" : "excluded",
    since: "2026-10-22T02:00:00Z",
    evaluated_at: "2026-10-22T08:00:00Z",
    models: ["K-101 / main v2"],
    exclusion: null,
    ...extra,
  };
}

const SENSORS = [
  sensor(1, "K101.TI1018.PV", "Failure", "flatline"),
  sensor(2, "K101.PI1001.PV", "Good", "none"),
  sensor(3, "K101.TI1030.PV", "Out of specification", "out_of_range"),
  sensor(4, "K201.FI2203.PV", "Failure", "stale", { models: ["K-201 / main v1"] }),
  sensor(5, "K201.VI2010.PV", "Function check", "manual_exclusion", {
    exclusion: {
      id: 7,
      tag_id: 5,
      source_name: "K201.VI2010.PV",
      asset_code: "K-201",
      kind: "exclude",
      reason: "calibration",
      starts_at: "2026-10-21T00:00:00Z",
      expires_at: "2026-10-30T00:00:00Z",
      ended_at: null,
      created_by: 1,
    },
  }),
  sensor(6, "K101.SI1001.PV", "Good", "override", {
    effect: "used",
    exclusion: {
      id: 8,
      tag_id: 6,
      source_name: "K101.SI1001.PV",
      asset_code: "K-101",
      kind: "override",
      reason: "fixed speed",
      starts_at: "2026-10-21T00:00:00Z",
      expires_at: "2026-10-28T00:00:00Z",
      ended_at: null,
      created_by: 1,
    },
  }),
  sensor(9, "E110.TI3005.PV", "Maintenance required", "spike", { models: [] }),
];

describe("sensor health rules (wireframe 07)", () => {
  it("says the rule and how long it held, or the engineer's reason", () => {
    expect(ruleOrReason(SENSORS[0]!, NOW)).toBe("Flatline 6 h");
    expect(ruleOrReason(SENSORS[4]!, NOW)).toBe("Manual: calibration until 30-Oct");
    expect(ruleOrReason(SENSORS[5]!, NOW)).toBe("Overridden: fixed speed until 28-Oct");
    expect(scoringUse(SENSORS[0]!)).toBe("Auto-excluded");
    expect(scoringUse(SENSORS[4]!)).toBe("Manually excluded");
    expect(scoringUse(SENSORS[5]!)).toBe("In use (overridden)");
  });

  it("lists non-Good and overridden sensors worst first, and counts what models use", () => {
    expect(listed(SENSORS, null).map((s) => s.tag_id)).toEqual([1, 4, 3, 9, 5, 6]);
    expect(listed(SENSORS, "Failure").map((s) => s.tag_id)).toEqual([1, 4]);
    const f = figures(SENSORS);
    expect(f.inModels).toBe(6); // the E-110 sensor is in no model
    expect(f.byStatus).toMatchObject({ Failure: 2, "Out of specification": 1 });
    expect(f.impacted).toBe(2); // K-101 and K-201
  });
});

describe("SCR-07 sensor health", () => {
  function routes() {
    const r = sessionRoutes(true);
    r["GET /auth/me"] = () => ({
      status: 200,
      body: {
        user: { ...ADMIN, id: 3, roles: [{ role: "analyst", scope_asset_id: null }] },
        csrf_token: "c",
      },
    });
    r["GET /sensors/health"] = () => ({
      status: 200,
      body: { items: SENSORS, next_cursor: null },
    });
    r["GET /tags"] = () => ({ status: 200, body: { items: [], next_cursor: null } });
    return r;
  }

  it("filters by category, and excludes a sensor with a reason and an expiry", async () => {
    const r = routes();
    r["POST /sensors/1/exclusions"] = (call) => ({
      status: 201,
      body: { id: 9, ...(call.body as object) },
    });
    const { calls } = fakeApi(r);
    const user = userEvent.setup();
    renderApp("/sensors");

    const table = await screen.findByRole("table", { name: "NAMUR NE 107 status per sensor" });
    expect(within(table).getAllByRole("row")).toHaveLength(1 + 6);
    expect(screen.getByText("Models impacted").previousSibling).toHaveTextContent("2");
    await user.click(screen.getByRole("button", { name: /Out of specification/ }));
    await waitFor(() =>
      expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(2),
    );
    await user.click(screen.getByRole("button", { name: /show all non-Good/ }));

    // Stale data cannot be overridden; a flatline can.
    expect(screen.queryByRole("button", { name: "Override K201.FI2203.PV" })).toBeNull();
    expect(screen.getByRole("button", { name: "Override K101.TI1018.PV" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Exclude K101.TI1018.PV" }));
    const dialog = screen.getByRole("dialog", { name: "Exclude K101.TI1018.PV" });
    await user.selectOptions(within(dialog).getByLabelText("Until"), "168");
    await user.type(within(dialog).getByLabelText(/Reason/), "sensor replaced");
    await user.click(within(dialog).getByRole("button", { name: "Exclude" }));
    await waitFor(() => {
      const sent = calls.find((c: Call) => c.path === "/sensors/1/exclusions")?.body as {
        kind: string;
        reason: string;
        until: string;
      };
      expect(sent).toMatchObject({ kind: "exclude", reason: "sensor replaced" });
      const days = (Date.parse(sent.until) - Date.now()) / 86_400_000;
      expect(days).toBeGreaterThan(6.9);
      expect(days).toBeLessThan(7.1);
    });
  });

  it("ends an exclusion early", async () => {
    const r = routes();
    r["POST /sensor-exclusions/7/end"] = () => ({ status: 200, body: {} });
    const { calls } = fakeApi(r);
    const user = userEvent.setup();
    renderApp("/sensors");
    await user.click(await screen.findByRole("button", { name: "End exclusion" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "End" }));
    await waitFor(() =>
      expect(calls.some((c: Call) => c.path === "/sensor-exclusions/7/end")).toBe(true),
    );
  });

  it("shows no actions to a viewer", async () => {
    const r = routes();
    r["GET /auth/me"] = () => ({
      status: 200,
      body: {
        user: { ...ADMIN, id: 4, roles: [{ role: "viewer", scope_asset_id: null }] },
        csrf_token: "c",
      },
    });
    fakeApi(r);
    renderApp("/sensors");
    await screen.findByRole("table", { name: "NAMUR NE 107 status per sensor" });
    expect(screen.queryByRole("button", { name: /^Exclude/ })).toBeNull();
  });
});
