import { describe, expect, it } from "vitest";

import type { AssetNode } from "../../api/types";
import { ALERTS, MODELS, TREE } from "../../test/fakeApi";
import {
  age,
  changedIds,
  defaultExpanded,
  describeAlert,
  equipmentUnder,
  filterByBand,
  highestDeviation,
  openAlertSeries,
  unknownReason,
  visibleRows,
  walk,
} from "./fleetModel";

const roots = TREE as unknown as AssetNode[];

describe("fleet hierarchy", () => {
  it("opens the top level and abnormal branches, and leaves healthy ones closed", () => {
    const open = defaultExpanded(roots);
    expect([...open].sort()).toEqual([1, 5]);
    const rows = visibleRows(roots, open).map((r) => [r.node.code, r.depth]);
    expect(rows).toEqual([
      ["DEMO", 0],
      ["SA-AMM", 1],
      ["K-101", 2],
      ["P-104A", 2],
      ["P-202", 2],
      ["SA-UTIL", 1],
    ]);
  });

  it("keeps only the branches with assets in a band", () => {
    const watch = filterByBand(roots, "Watch");
    expect(walk(watch).map((n) => n.code)).toEqual(["DEMO", "SA-AMM", "P-104A"]);
    expect(
      filterByBand(roots, "Healthy")
        .flatMap((r) => walk([r]))
        .map((n) => n.code),
    ).toEqual(["DEMO", "SA-UTIL", "E-110"]);
  });

  it("gives the Unknown reason from the asset's model", () => {
    const p202 = walk(roots).find((n) => n.code === "P-202")!;
    expect(unknownReason(p202)).toBe("Insufficient data: Required sensor not usable");
    expect(unknownReason(walk(roots).find((n) => n.code === "K-101")!)).toBeNull();
  });

  it("notices rows whose figures changed, but not on the first read", () => {
    const first = changedIds(new Map(), roots);
    expect(first.changed.size).toBe(0);
    const updated = structuredClone(roots);
    updated[0]!.children[0]!.children[1]!.health = 60;
    expect([...changedIds(first.next, updated).changed]).toEqual([7]);
  });

  it("lists the monitored equipment beneath a unit", () => {
    expect(equipmentUnder(roots[0]!.children[0]!).map((n) => n.code)).toEqual([
      "K-101",
      "P-104A",
      "P-202",
    ]);
    const k101 = walk(roots).find((n) => n.code === "K-101")!;
    expect(equipmentUnder(k101).map((n) => n.code)).toEqual(["K-101"]);
  });
});

describe("side lists", () => {
  it("ranks running models by DI and names their assets", () => {
    const top = highestDeviation(MODELS as never, roots);
    expect(top.map((d) => [d.label, d.di])).toEqual([
      ["Syngas compressor K-101", 36.2],
      ["BFW pump P-104A", 19.1],
      ["Waste-heat boiler E-110", 7.7],
    ]);
  });

  it("describes alerts as the wireframe does", () => {
    expect(describeAlert(ALERTS[0] as never)).toBe("K-101 Deviation Index high");
    expect(describeAlert(ALERTS[1] as never)).toBe("P-104A TI1044 residual");
  });

  it("says how long ago", () => {
    const now = new Date("2026-10-21T12:00:00Z");
    expect(age(new Date("2026-10-21T11:18:00Z"), now)).toBe("42 min");
    expect(age(new Date("2026-10-21T09:00:00Z"), now)).toBe("3 h");
    expect(age(new Date("2026-10-18T12:00:00Z"), now)).toBe("3 d");
  });

  it("counts open alerts over time from raise and close times", () => {
    const t0 = Date.parse("2026-10-20T00:00:00Z");
    const series = openAlertSeries(
      [
        { raised_at: "2026-10-20T01:00:00Z", closed_at: null },
        { raised_at: "2026-10-20T02:00:00Z", closed_at: "2026-10-20T03:00:00Z" },
      ] as never,
      t0,
      t0 + 4 * 3_600_000,
      4,
    );
    expect(series.map(([, n]) => n)).toEqual([0, 1, 2, 1, 1]);
  });
});
