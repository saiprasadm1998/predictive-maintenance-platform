import type { EChartsCoreOption } from "echarts/core";

import { formatDateTime, formatTime } from "../app/format";
import type { ChartColors } from "./charting";

/**
 * Chart conventions of PDS §3.4, as a pure function from data to ECharts options so they can
 * be tested without a canvas:
 * - actual: solid, --text, 2 px; predicted: dashed, --text-muted, 1.5 px
 * - expected band: filled --band between lower and upper
 * - warning / alert limits: horizontal dashed lines in --watch / --alert (the warning line
 *   in --watch-text, the readable shade: --watch is 2.4:1 on white, decision 6.1)
 * - excluded periods: grey columns with the reason on hover
 * - bad data: a gap in the line (null values) and magenta ticks on the time axis
 * - alert periods: a bar under the time axis, coloured by severity, with its shape at the start
 */

export type Point = [number, number | null]; // epoch ms, value (null: no usable value)

export interface Period {
  from: number;
  to: number;
}

export interface TrendData {
  actual: Point[];
  predicted?: Point[];
  band?: [number, number, number][]; // epoch ms, lower, upper
  limits?: { warning?: number[]; alert?: number[] };
  excluded?: (Period & { reason: string })[];
  bad?: number[];
  alerts?: (Period & { severity: "Alert" | "Warning" })[];
}

export interface TrendSettings {
  unit: string;
  from: number;
  to: number;
  actualName?: string;
}

const ALERT_BAR_HEIGHT = 10;

/** Axis ends with a little room around the data and limits. */
function niceFloor(value: number): number {
  const step = 10 ** Math.floor(Math.log10(Math.abs(value) || 1));
  return Math.floor(value / step - 0.5) * step;
}

function niceCeil(value: number): number {
  const step = 10 ** Math.floor(Math.log10(Math.abs(value) || 1));
  return Math.ceil(value / step + 0.5) * step;
}

/** ECharts tooltips are HTML; names and units come from the registry, so escape them. */
export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

interface TooltipParam {
  seriesId: string;
  seriesName: string;
  marker: string;
  value: [number, number | null];
}

export function trendOptions(
  data: TrendData,
  settings: TrendSettings,
  colors: ChartColors,
): EChartsCoreOption {
  const actualName = settings.actualName ?? "Actual";
  const hasBar = (data.alerts?.length ?? 0) > 0 || (data.bad?.length ?? 0) > 0;
  const limitLines = [
    ...(data.limits?.warning ?? []).map((y) => ({
      yAxis: y,
      name: "Warning limit",
      color: colors.watchText,
    })),
    ...(data.limits?.alert ?? []).map((y) => ({
      yAxis: y,
      name: "Alert limit",
      color: colors.alert,
    })),
  ];

  const limitValues = limitLines.map((l) => l.yAxis);
  const series: Record<string, unknown>[] = [];
  if (data.band?.length) {
    // A stacked pair: the invisible lower edge, then the width filled with --band.
    series.push({
      id: "band-lower",
      name: "Expected band",
      type: "line",
      data: data.band.map(([t, lo]) => [t, lo]),
      stack: "band",
      symbol: "none",
      lineStyle: { opacity: 0 },
      tooltip: { show: false },
      silent: true,
    });
    series.push({
      id: "band-width",
      name: "Expected band",
      type: "line",
      data: data.band.map(([t, lo, hi]) => [t, hi - lo]),
      stack: "band",
      symbol: "none",
      lineStyle: { opacity: 0 },
      areaStyle: { color: colors.band, opacity: 1 },
      tooltip: { show: false },
      silent: true,
    });
  }
  if (data.predicted?.length) {
    series.push({
      id: "predicted",
      name: "Predicted",
      type: "line",
      data: data.predicted,
      symbol: "none",
      connectNulls: false,
      lineStyle: { color: colors.textMuted, width: 1.5, type: "dashed" },
      itemStyle: { color: colors.textMuted },
    });
  }
  series.push({
    id: "actual",
    name: actualName,
    type: "line",
    data: data.actual,
    symbol: "none",
    connectNulls: false, // bad or excluded data shows as a break
    lineStyle: { color: colors.text, width: 2, type: "solid" },
    itemStyle: { color: colors.text },
    markLine: limitLines.length
      ? {
          symbol: "none",
          silent: true,
          label: { show: false },
          data: limitLines.map((l) => ({
            yAxis: l.yAxis,
            name: l.name,
            lineStyle: { color: l.color, type: "dashed", width: 1.5 },
          })),
        }
      : undefined,
    markArea: data.excluded?.length
      ? {
          silent: false,
          itemStyle: { color: colors.unknown, opacity: 0.18 },
          label: { show: false },
          tooltip: { show: true, formatter: (p: { name: string }) => escapeHtml(p.name) },
          data: data.excluded.map((e) => [
            { xAxis: e.from, name: `Excluded: ${e.reason}` },
            { xAxis: e.to },
          ]),
        }
      : undefined,
  });

  if (hasBar) {
    series.push({
      id: "alert-bar",
      name: "Alert periods",
      type: "line",
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: [],
      silent: true,
      markArea: {
        silent: true,
        label: { show: false },
        data: (data.alerts ?? []).map((a) => [
          {
            xAxis: a.from,
            name: `${a.severity} from ${formatDateTime(new Date(a.from))}`,
            itemStyle: { color: a.severity === "Alert" ? colors.alert : colors.watch },
          },
          { xAxis: a.to },
        ]),
      },
      markPoint: {
        silent: true,
        symbolSize: 9,
        label: { show: false },
        data: (data.alerts ?? []).map((a) => ({
          coord: [a.from, 0.5],
          symbol: a.severity === "Alert" ? "triangle" : "diamond",
          itemStyle: {
            color: a.severity === "Alert" ? colors.alert : colors.watch,
            borderColor: a.severity === "Alert" ? colors.panel : colors.watchText,
            borderWidth: 1,
          },
        })),
      },
    });
    if (data.bad?.length) {
      series.push({
        id: "bad-data",
        name: "Bad data",
        type: "scatter",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: data.bad.map((t) => [t, 0.5]),
        symbol: "rect",
        symbolSize: [2, ALERT_BAR_HEIGHT],
        itemStyle: { color: colors.fault },
        tooltip: { show: false },
        silent: true,
      });
    }
  }

  // Times as PDS §7: "21-Oct" at midnight, "14:05" otherwise; the tooltip "21-Oct 14:05".
  const axisLabel = {
    color: colors.textMuted,
    hideOverlap: true,
    formatter: (value: number) => {
      const date = new Date(value);
      const time = formatTime(date);
      return time === "00:00" ? formatDateTime(date).slice(0, 6) : time;
    },
  };
  const unitText = (v: number | null | undefined) =>
    v === null || v === undefined
      ? "—"
      : `${v.toLocaleString("en-GB", { maximumFractionDigits: 2 })} ${settings.unit}`;
  const xAxisBase = {
    type: "time",
    min: settings.from,
    max: settings.to,
    axisLine: { lineStyle: { color: colors.line } },
    splitLine: { show: false },
  };
  return {
    animation: false,
    textStyle: { color: colors.textMuted, fontFamily: "inherit" },
    grid: hasBar
      ? [
          { left: 56, right: 16, top: 12, bottom: 30 + ALERT_BAR_HEIGHT + 6 },
          { left: 56, right: 16, height: ALERT_BAR_HEIGHT, bottom: 26 },
        ]
      : [{ left: 56, right: 16, top: 12, bottom: 30 }],
    xAxis: hasBar
      ? [
          { ...xAxisBase, axisLabel: { show: false }, axisTick: { show: false } },
          { ...xAxisBase, gridIndex: 1, axisLabel },
        ]
      : [{ ...xAxisBase, axisLabel }],
    yAxis: [
      {
        type: "value",
        scale: true,
        // Limits always in view, so a value's distance to them can be read.
        ...(limitValues.length
          ? {
              min: (v: { min: number }) => {
                const low = Math.min(v.min, ...limitValues);
                return low >= 0 ? 0 : niceFloor(low); // a positive measure starts at zero
              },
              max: (v: { max: number }) => niceCeil(Math.max(v.max, ...limitValues)),
            }
          : {}),
        name: settings.unit,
        nameTextStyle: { color: colors.textMuted, align: "right" },
        axisLabel: { color: colors.textMuted },
        splitLine: { lineStyle: { color: colors.lineSoft } },
      },
      ...(hasBar ? [{ type: "value", gridIndex: 1, min: 0, max: 1, show: false }] : []),
    ],
    axisPointer: { link: [{ xAxisIndex: "all" }], lineStyle: { color: colors.textMuted } },
    tooltip: {
      trigger: "axis",
      backgroundColor: colors.panel,
      borderColor: colors.line,
      textStyle: { color: colors.text },
      formatter: (params: TooltipParam[]) => {
        const rows = params.filter(
          (p) => !p.seriesId.startsWith("band") && p.seriesId !== "bad-data",
        );
        const first = rows[0];
        if (!first) return "";
        const head = formatDateTime(new Date(first.value[0]));
        const lines = rows.map(
          (p) =>
            `${p.marker}${escapeHtml(p.seriesName)}: <b>${escapeHtml(unitText(p.value[1]))}</b>`,
        );
        return [head, ...lines].join("<br/>");
      },
    },
    dataZoom: [{ type: "inside", xAxisIndex: hasBar ? [0, 1] : [0], filterMode: "none" }],
    series,
  };
}
