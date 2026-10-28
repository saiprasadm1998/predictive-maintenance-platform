import { describe, expect, it } from "vitest";

import type { ChartColors } from "./charting";
import { type TrendData, escapeHtml, trendOptions } from "./trendOptions";

const COLORS: ChartColors = {
  text: "#text",
  textMuted: "#muted",
  line: "#line",
  lineSoft: "#soft",
  band: "#band",
  panel: "#panel",
  alert: "#alert",
  watch: "#watch",
  watchText: "#watchtext",
  fault: "#fault",
  unknown: "#unknown",
};

const T0 = Date.UTC(2026, 9, 20);
const MIN = 60_000;
const DATA: TrendData = {
  actual: [
    [T0, 80],
    [T0 + MIN, null],
    [T0 + 2 * MIN, 82],
  ],
  predicted: [
    [T0, 79],
    [T0 + MIN, 79.5],
    [T0 + 2 * MIN, 80],
  ],
  band: [
    [T0, 75, 83],
    [T0 + 2 * MIN, 76, 84],
  ],
  limits: { warning: [86], alert: [90] },
  excluded: [{ from: T0, to: T0 + MIN, reason: "outside operating mode" }],
  bad: [T0 + MIN],
  alerts: [{ from: T0 + MIN, to: T0 + 2 * MIN, severity: "Warning" }],
};

type Series = Record<string, unknown> & { id: string };

function seriesById(data: TrendData = DATA): Record<string, Series> {
  const option = trendOptions(data, { unit: "°C", from: T0, to: T0 + 3 * MIN }, COLORS) as {
    series: Series[];
  };
  return Object.fromEntries(option.series.map((s) => [s.id, s]));
}

describe("chart conventions (PDS §3.4)", () => {
  it("draws actual solid 2 px in --text and predicted dashed 1.5 px in --text-muted", () => {
    const s = seriesById();
    expect(s.actual?.lineStyle).toEqual({ color: "#text", width: 2, type: "solid" });
    expect(s.predicted?.lineStyle).toEqual({ color: "#muted", width: 1.5, type: "dashed" });
  });

  it("breaks the line at bad data instead of joining across it", () => {
    const s = seriesById();
    expect(s.actual?.connectNulls).toBe(false);
    expect(s["bad-data"]?.itemStyle).toEqual({ color: "#fault" });
  });

  it("fills the expected band between lower and upper in --band", () => {
    const s = seriesById();
    expect(s["band-lower"]?.data).toEqual([
      [T0, 75],
      [T0 + 2 * MIN, 76],
    ]);
    expect(s["band-width"]?.data).toEqual([
      [T0, 8],
      [T0 + 2 * MIN, 8],
    ]);
    expect(s["band-width"]?.areaStyle).toEqual({ color: "#band", opacity: 1 });
  });

  it("draws the limits as dashed lines in --watch and --alert", () => {
    const lines = (
      seriesById().actual?.markLine as { data: { yAxis: number; lineStyle: unknown }[] }
    ).data;
    expect(lines).toEqual([
      {
        yAxis: 86,
        name: "Warning limit",
        lineStyle: { color: "#watchtext", type: "dashed", width: 1.5 },
      },
      {
        yAxis: 90,
        name: "Alert limit",
        lineStyle: { color: "#alert", type: "dashed", width: 1.5 },
      },
    ]);
  });

  it("draws markers as thin vertical lines (the forecast's median crossing)", () => {
    const lines = (
      seriesById({ actual: DATA.actual, markers: [{ t: T0 + MIN, name: "Median crossing" }] })
        .actual?.markLine as { data: unknown[] }
    ).data;
    expect(lines).toEqual([
      {
        xAxis: T0 + MIN,
        name: "Median crossing",
        lineStyle: { color: "#muted", type: "solid", width: 1 },
      },
    ]);
    expect(seriesById({ actual: DATA.actual }).actual?.markLine).toBeUndefined();
  });

  it("shades excluded periods with their reason, and marks alert periods under the axis", () => {
    const s = seriesById();
    const excluded = (s.actual?.markArea as { data: [{ name: string }, unknown][] }).data;
    expect(excluded[0]?.[0].name).toBe("Excluded: outside operating mode");
    const bar = s["alert-bar"] as unknown as {
      xAxisIndex: number;
      markPoint: { data: { symbol: string }[] };
    };
    expect(bar.xAxisIndex).toBe(1);
    expect(bar.markPoint.data[0]?.symbol).toBe("diamond");
  });

  it("leaves out what is not there", () => {
    const s = seriesById({ actual: DATA.actual });
    expect(Object.keys(s)).toEqual(["actual"]);
    expect(s.actual?.markLine).toBeUndefined();
  });
});

describe("tooltip", () => {
  it("shows DD-Mon HH:MM, leaves out the band and bad-data marks, and escapes text", () => {
    const option = trendOptions(
      { actual: DATA.actual, band: DATA.band, bad: DATA.bad },
      { unit: "<b>°C", from: T0, to: T0 + 3 * MIN, actualName: "TI<1>" },
      COLORS,
    ) as { tooltip: { formatter: (p: unknown[]) => string } };
    const html = option.tooltip.formatter([
      { seriesId: "band-lower", seriesName: "Expected band", marker: "", value: [T0, 75] },
      { seriesId: "actual", seriesName: "TI<1>", marker: "", value: [T0, 80.123] },
    ]);
    expect(html).not.toContain("Expected band");
    expect(html).toContain("TI&#60;1&#62;: <b>80.12 &#60;b&#62;°C</b>");
    expect(html).toContain(new Date(T0).toISOString().slice(0, 16)); // PDS §7: full ISO time
    expect(escapeHtml(`"'&`)).toBe("&#34;&#39;&#38;");
  });
});

describe("y axis", () => {
  it("takes a fixed axis when given one (Health: 0 to 100)", () => {
    const option = trendOptions(
      { actual: [[T0, 40]] },
      { unit: "", from: T0, to: T0 + MIN, axis: { min: 0, max: 100, interval: 25 } },
      COLORS,
    ) as { yAxis: { min: unknown; max: unknown; interval: unknown }[] };
    expect(option.yAxis[0]).toMatchObject({ min: 0, max: 100, interval: 25 });
  });

  it("keeps the limits in view even when the data is far from them", () => {
    const option = trendOptions(
      {
        actual: [
          [T0, 40],
          [T0 + MIN, 60],
        ],
        limits: { warning: [15], alert: [25] },
      },
      { unit: "%", from: T0, to: T0 + 2 * MIN },
      COLORS,
    ) as {
      yAxis: { min?: (v: { min: number }) => number; max?: (v: { max: number }) => number }[];
    };
    const axis = option.yAxis[0]!;
    expect(axis.min!({ min: 40 })).toBeLessThanOrEqual(15);
    expect(axis.max!({ max: 60 })).toBeGreaterThanOrEqual(60);
  });
});
