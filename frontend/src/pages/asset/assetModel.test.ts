import { describe, expect, it } from "vitest";

import type { Alert, SensorNow, SensorTrend } from "../../api/types";
import {
  alertPeriods,
  alertWindow,
  excludedPeriods,
  linePoints,
  sensorChartData,
  sensorLabel,
  sensorOrder,
  topContributors,
  worstAlert,
} from "./assetModel";

function sensor(
  name: string,
  z: number | null,
  contribution: number | null,
  extra: Partial<SensorNow> = {},
): SensorNow {
  return {
    tag_id: name.length,
    source_name: `K101.${name}.PV`,
    description: "",
    unit: "°C",
    required: false,
    actual: 1,
    predicted: 1,
    residual: 0,
    z,
    contribution,
    dq_status: "Good",
    dq_rule: "none",
    used: true,
    sigma: 2,
    warning: 3,
    alert: 5,
    ...extra,
  };
}

function alert(extra: Partial<Alert>): Alert {
  return {
    id: 1,
    model_id: 1,
    model: "main",
    asset_id: 6,
    asset_code: "K-101",
    kind: "di",
    tag_id: null,
    tag: null,
    state: "Active-Unacknowledged",
    severity: "Alert",
    priority: "P1",
    raised_at: "2026-10-20T00:00:00Z",
    condition_active: true,
    ack_at: null,
    shelved_until: null,
    shelve_reason: null,
    closed_at: null,
    cleared_at: null,
    asset_path: "Site A / Ammonia unit / K-101",
    version: 1,
    di: 36.2,
    health: 28,
    persistence_n: 5,
    persistence_m: 5,
    ...extra,
  };
}

describe("contributors and the sensor table", () => {
  it("ranks used sensors by their share of the DI, with direction", () => {
    const top = topContributors([
      sensor("TI1012", 3.1, 0.46),
      sensor("ZI1015", 2.0, 0.21),
      sensor("PI1002", -1.0, 0.08),
      sensor("TI1018", -0.1, 0.5, { used: false }), // flatlined: not used
      sensor("II1001", 0, 0),
    ]);
    expect(top.map((c) => [c.sensor.source_name, c.direction])).toEqual([
      ["K101.TI1012.PV", "up"],
      ["K101.ZI1015.PV", "up"],
      ["K101.PI1002.PV", "down"],
    ]);
  });

  it("orders the table by |z|, unknown last", () => {
    const order = sensorOrder([
      sensor("A1", 0.5, 0),
      sensor("B1", null, null),
      sensor("C1", -3, 0),
    ]);
    expect(order.map((s) => s.source_name)).toEqual(["K101.C1.PV", "K101.A1.PV", "K101.B1.PV"]);
  });

  it("labels sensors with the tag-style ID", () => {
    expect(
      sensorLabel({ source_name: "K101.TI1012.PV", description: "TI-1012 DE bearing temperature" }),
    ).toBe("TI-1012 DE bearing temperature");
    expect(sensorLabel({ source_name: "K101.ZI1015.PV", description: "" })).toBe("ZI-1015");
  });
});

describe("chart data", () => {
  const T0 = Date.parse("2026-10-20T00:00:00Z");
  const bucketed: SensorTrend = {
    tag_id: 1,
    source_name: "K101.TI1012.PV",
    start: "2026-10-20T00:00:00Z",
    end: "2026-10-27T00:00:00Z",
    raw: false,
    bucket_s: 600,
    source: "raw",
    ts: ["2026-10-20T00:00:00Z", "2026-10-20T00:10:00Z"],
    min: { actual: [70, 71], predicted: [70, 70] },
    max: { actual: [74, 72], predicted: [70, 70] },
  };

  it("draws buckets as their minimum then maximum, so spikes stay", () => {
    expect(linePoints(bucketed, "actual")).toEqual([
      [T0, 70],
      [T0 + 300_000, 74],
      [T0 + 600_000, 71],
      [T0 + 900_000, 72],
    ]);
  });

  it("puts the expected band at predicted ± warning × σ", () => {
    const data = sensorChartData(bucketed, sensor("TI1012", 3.1, 0.4, { sigma: 2, warning: 3 }));
    expect(data.band?.[0]).toEqual([T0, 64, 76]);
    expect(sensorChartData(bucketed, sensor("TI1012", 1, 1, { sigma: null })).band).toBeUndefined();
  });

  it("shades the cycles a sensor was left out of scoring", () => {
    const trend = {
      ...bucketed,
      unused: [
        {
          start: new Date(T0).toISOString(),
          end: new Date(T0 + 120_000).toISOString(),
          status: "Failure",
          rule: "flatline",
        },
      ],
    };
    expect(sensorChartData(trend, undefined).excluded).toEqual([
      { from: T0, to: T0 + 180_000, reason: "not used in scoring (Failure, flatline)" },
    ]);
  });

  it("ends an alert bar when its condition cleared", () => {
    const [cleared, active] = alertPeriods(
      [
        alert({ cleared_at: "2026-10-20T03:00:00Z", state: "RTN-Unacknowledged" }),
        alert({ raised_at: "2026-10-20T05:00:00Z" }),
      ],
      Date.parse("2026-10-21T00:00:00Z"),
    )!;
    expect(cleared!.to).toBe(Date.parse("2026-10-20T03:00:00Z"));
    expect(active!.to).toBe(Date.parse("2026-10-21T00:00:00Z"));
  });

  it("shades periods not scored normally, and everything after a pause", () => {
    const shaded = excludedPeriods(
      [
        {
          start: "2026-10-20T01:00:00Z",
          end: "2026-10-20T02:00:00Z",
          status: "Outside operating mode",
          reason: null,
        },
      ],
      {
        status: "Paused",
        reason: null,
        since: "2026-10-20T06:00:00Z",
        last_cycle: null,
        version_id: 1,
        band: "Unknown",
        di: null,
        health: null,
      },
      Date.parse("2026-10-21T00:00:00Z"),
    );
    expect(shaded.map((p) => p.reason)).toEqual(["Outside operating mode", "Paused"]);
    expect(shaded[1]!.to).toBe(Date.parse("2026-10-21T00:00:00Z"));
  });
});

describe("alerts", () => {
  it("picks the most urgent open alert", () => {
    const worst = worstAlert([
      alert({ id: 1, priority: "P3" }),
      alert({ id: 2, priority: "P1", state: "Active-Acknowledged" }),
      alert({ id: 3, priority: "P1" }),
      alert({ id: 4, priority: "P1", closed_at: "2026-10-20T01:00:00Z", state: "Normal" }),
    ]);
    expect(worst?.id).toBe(3);
  });

  it("opens an alert link on the alert's window", () => {
    const now = Date.parse("2026-10-21T12:00:00Z");
    const open = alertWindow(alert({ raised_at: "2026-10-21T06:00:00Z" }), now);
    expect([open.from.toISOString(), open.to.toISOString()]).toEqual([
      "2026-10-20T18:00:00.000Z",
      "2026-10-21T12:00:00.000Z",
    ]);
    const closed = alertWindow(
      alert({ raised_at: "2026-10-20T06:00:00Z", closed_at: "2026-10-20T08:00:00Z" }),
      now,
    );
    expect(closed.to.toISOString()).toBe("2026-10-20T10:00:00.000Z");
  });
});
