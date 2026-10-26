/**
 * The ECharts set-up shared by every chart (PDS §9: canvas renderer, one wrapper). Only the
 * parts we use are registered, which keeps the bundle small.
 */
import { LineChart, ScatterChart } from "echarts/charts";
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  LineChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  AxisPointerComponent,
  DataZoomComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  CanvasRenderer,
]);

export { echarts };

/** The design tokens the charts draw with, read from CSS so both themes apply. */
export interface ChartColors {
  text: string;
  textMuted: string;
  line: string;
  lineSoft: string;
  band: string;
  panel: string;
  alert: string;
  watch: string;
  watchText: string;
  fault: string;
  unknown: string;
}

export function chartColors(element: Element = document.documentElement): ChartColors {
  const style = getComputedStyle(element);
  const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    text: read("--text", "#1e2329"),
    textMuted: read("--text-muted", "#5b6470"),
    line: read("--line", "#c8cdd3"),
    lineSoft: read("--line-soft", "#e3e6e9"),
    band: read("--band", "#dce3ec"),
    panel: read("--panel", "#ffffff"),
    alert: read("--alert", "#b71c1c"),
    watch: read("--watch", "#d99a00"),
    watchText: read("--watch-text", "#805a00"),
    fault: read("--fault", "#a3007d"),
    unknown: read("--unknown", "#7a7f87"),
  };
}
