import { describe, expect, it } from "vitest";

import { ASSETS } from "../test/fakeApi";
import { assetPath, matchAssets } from "./assetSearch";
import { safeNext } from "./navigation";
import { findScreen } from "./useScreen";
import { resolveTimeRange, timeRangeParams } from "./timeRange";

const NOW = new Date("2026-10-21T12:00:00Z");

describe("time range in the URL", () => {
  it("defaults to the last 7 days", () => {
    const range = resolveTimeRange(new URLSearchParams(), NOW);
    expect(range.preset).toBe("7d");
    expect(range.from.toISOString()).toBe("2026-10-14T12:00:00.000Z");
  });

  it("reads a preset, a custom range, and ignores nonsense", () => {
    expect(resolveTimeRange(new URLSearchParams("range=24h"), NOW).from.toISOString()).toBe(
      "2026-10-20T12:00:00.000Z",
    );
    const custom = resolveTimeRange(
      new URLSearchParams("from=2026-10-01T00:00:00Z&to=2026-10-02T00:00:00Z"),
      NOW,
    );
    expect(custom.preset).toBeNull();
    expect(custom.to.toISOString()).toBe("2026-10-02T00:00:00.000Z");
    expect(resolveTimeRange(new URLSearchParams("range=5y&from=x&to=y"), NOW).preset).toBe("7d");
    expect(
      resolveTimeRange(
        new URLSearchParams("from=2026-10-02T00:00:00Z&to=2026-10-01T00:00:00Z"),
        NOW,
      ).preset,
    ).toBe("7d");
  });

  it("carries only the time range onto other screens' links", () => {
    expect(timeRangeParams(new URLSearchParams("range=30d&alert=4&sort=x")).toString()).toBe(
      "range=30d",
    );
  });
});

describe("routes", () => {
  it("maps URLs to screen IDs, most specific first", () => {
    expect(findScreen("/fleet")?.id).toBe("SCR-01");
    expect(findScreen("/assets/6")?.id).toBe("SCR-03");
    expect(findScreen("/assets/6/diagnostics")?.id).toBe("SCR-04");
    expect(findScreen("/models/3/build/2")?.id).toBe("SCR-06");
    expect(findScreen("/admin/registry")?.id).toBe("SCR-13");
    expect(findScreen("/nowhere")).toBeNull();
  });

  it("only follows sign-in to a path inside the app", () => {
    expect(safeNext("/assets/6?range=24h")).toBe("/assets/6?range=24h");
    expect(safeNext("https://evil.example")).toBe("/fleet");
    expect(safeNext("//evil.example")).toBe("/fleet");
    expect(safeNext("/\\evil.example")).toBe("/fleet");
    expect(safeNext(null)).toBe("/fleet");
  });
});

describe("asset search", () => {
  it("ranks code prefix, then code, then name matches", () => {
    expect(matchAssets(ASSETS, "k-1").map((a) => a.code)).toEqual(["K-101"]);
    expect(matchAssets(ASSETS, "pump").map((a) => a.code)).toEqual(["P-104A"]);
    expect(matchAssets(ASSETS, "a").map((a) => a.code)).toEqual(["P-104A", "SA-AMM", "K-101"]);
    expect(matchAssets(ASSETS, "  ")).toEqual([]);
  });

  it("opens equipment on asset analysis and anything above on the unit view", () => {
    expect(assetPath(ASSETS[2]!)).toBe("/assets/6");
    expect(assetPath(ASSETS[1]!)).toBe("/units/5");
  });
});
