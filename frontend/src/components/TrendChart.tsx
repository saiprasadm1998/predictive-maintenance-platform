import { useEffect, useId, useMemo, useRef, useState } from "react";

import { formatDateTime, formatIso } from "../app/format";
import { chartColors, echarts } from "./charting";
import { type Point, type TrendData, type TrendSettings, trendOptions } from "./trendOptions";

const MAX_TABLE_ROWS = 2000;

/** Values to six significant digits, without trailing zeros ("12.3457", "0.00123"). */
function tableValue(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return Number(value.toPrecision(6)).toString();
}

/**
 * The one time-series chart (PDS §3.4, §5, §9). It enforces the chart conventions through
 * `trendOptions`, shares cursor and zoom with the other charts of its `group` (all charts on
 * a page by default), redraws in the dark theme's colours, can be read with the keyboard
 * (arrow keys move the cursor) and offers the data as a table ("View data", WCAG 1.3.1).
 */
export function TrendChart({
  title,
  data,
  settings,
  height = 220,
  group = "page",
  loading = false,
  onZoom,
  onPick,
  onSelect,
}: {
  title: string;
  data: TrendData;
  settings: TrendSettings;
  height?: number;
  group?: string;
  loading?: boolean;
  /** Called (debounced) with the visible window after a zoom or pan, to fetch finer data. */
  onZoom?: (from: number, to: number) => void;
  /** Called with the time under a click, to show what the page knows at that moment. */
  onPick?: (t: number) => void;
  /** Called with the period dragged across the plot (left to right or back). */
  onSelect?: (from: number, to: number) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const cursor = useRef(-1);
  const [position, setPosition] = useState(-1);
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme ?? "light");
  const [showTable, setShowTable] = useState(false);
  const [slow, setSlow] = useState(false);
  const tableId = useId();

  // Redraw when the theme changes (the colours come from CSS tokens).
  useEffect(() => {
    const observer = new MutationObserver(() =>
      setTheme(document.documentElement.dataset.theme ?? "light"),
    );
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const instance = echarts.init(element, undefined, { renderer: "canvas" });
    instance.group = group;
    echarts.connect(group);
    chart.current = instance;
    const resize = new ResizeObserver(() => instance.resize());
    resize.observe(element);
    return () => {
      resize.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, [group]);

  // A zoom or pan reports the window it settles on, so the page can fetch finer data.
  const zoomed = useRef(onZoom);
  const picked = useRef(onPick);
  const selected = useRef(onSelect);
  useEffect(() => {
    zoomed.current = onZoom;
    picked.current = onPick;
    selected.current = onSelect;
  }, [onZoom, onPick, onSelect]);
  useEffect(() => {
    const instance = chart.current;
    if (!instance) return;
    let timer: number | undefined;
    const handler = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const zoom = (
          instance.getOption() as { dataZoom?: { startValue?: number; endValue?: number }[] }
        ).dataZoom?.[0];
        if (zoom?.startValue !== undefined && zoom.endValue !== undefined)
          zoomed.current?.(Number(zoom.startValue), Number(zoom.endValue));
      }, 400);
    };
    instance.on("datazoom", handler);
    const pick = (event: { offsetX: number; offsetY: number }) => {
      if (!picked.current) return;
      const point = [event.offsetX, event.offsetY];
      if (!instance.containPixel({ gridIndex: 0 }, point)) return;
      const value = instance.convertFromPixel({ gridIndex: 0 }, point) as number | number[];
      const t = Array.isArray(value) ? value[0] : value;
      if (typeof t === "number" && Number.isFinite(t)) picked.current(t);
    };
    // Drag across the plot to select a period: press, move at least 5 px, release.
    let pressed: number[] | null = null;
    const timeAt = (point: number[]) => {
      const value = instance.convertFromPixel({ gridIndex: 0 }, point) as number | number[];
      return Array.isArray(value) ? value[0] : value;
    };
    const down = (event: { offsetX: number; offsetY: number }) => {
      const point = [event.offsetX, event.offsetY];
      pressed = selected.current && instance.containPixel({ gridIndex: 0 }, point) ? point : null;
    };
    const up = (event: { offsetX: number; offsetY: number }) => {
      const start = pressed;
      pressed = null;
      if (!start || !selected.current || Math.abs(event.offsetX - start[0]!) < 5) return;
      const a = timeAt(start);
      const b = timeAt([event.offsetX, start[1]!]);
      if (typeof a === "number" && typeof b === "number" && Number.isFinite(a + b))
        selected.current(Math.min(a, b), Math.max(a, b));
    };
    const zr = instance.getZr();
    zr.on("click", pick);
    zr.on("mousedown", down);
    zr.on("mouseup", up);
    return () => {
      window.clearTimeout(timer);
      // The chart may already be disposed (unmounting runs the init effect's cleanup first),
      // and disposing removes its handlers anyway.
      if (instance.isDisposed()) return;
      instance.off("datazoom", handler);
      zr.off("click", pick);
      zr.off("mousedown", down);
      zr.off("mouseup", up);
    };
  }, [group]);

  const option = useMemo(
    () => trendOptions(data, settings, chartColors()),
    // theme: the colours are read again when it changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data, settings, theme],
  );

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
  }, [option]);

  // PDS §6: a progress bar once loading takes more than a second; no page-blocking spinner.
  useEffect(() => {
    if (!loading) return;
    const timer = window.setTimeout(() => setSlow(true), 1000);
    return () => {
      window.clearTimeout(timer);
      setSlow(false);
    };
  }, [loading]);

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const count = data.actual.length;
    if (!count || !chart.current) return;
    const step = event.shiftKey ? 10 : 1;
    let next = cursor.current;
    if (event.key === "ArrowRight") next = Math.min(count - 1, (next < 0 ? -1 : next) + step);
    else if (event.key === "ArrowLeft") next = Math.max(0, (next < 0 ? count : next) - step);
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = count - 1;
    else if (event.key === "Escape") {
      cursor.current = -1;
      setPosition(-1);
      chart.current.dispatchAction({ type: "hideTip" });
      return;
    } else return;
    event.preventDefault();
    cursor.current = next;
    setPosition(next);
    const seriesIndex = (data.band?.length ? 2 : 0) + (data.predicted?.length ? 1 : 0);
    chart.current.dispatchAction({ type: "showTip", seriesIndex, dataIndex: next });
  }

  const point = position >= 0 ? data.actual[position] : undefined;
  const pointText = point
    ? `${formatDateTime(new Date(point[0]))}: ${point[1] === null ? "no value" : tableValue(point[1])} ${point[1] === null ? "" : settings.unit}`.trim()
    : "No point selected";
  const predicted = new Map(data.predicted?.map(([t, v]) => [t, v]));
  // A projection beyond the data (the forecast) adds rows of its own.
  const actualTimes = new Set(data.actual.map(([t]) => t));
  const ahead = (data.predicted ?? []).filter(([t]) => !actualTimes.has(t));
  const rows = (
    ahead.length
      ? [...data.actual, ...ahead.map(([t]): Point => [t, null])].sort((a, b) => a[0] - b[0])
      : data.actual
  ).slice(-MAX_TABLE_ROWS);
  return (
    <figure className="trend" aria-label={title} style={{ margin: 0 }}>
      <figcaption className="trend-head">
        <span className="trend-title">{title}</span>
        <button
          type="button"
          className="link-button"
          aria-expanded={showTable}
          aria-controls={tableId}
          onClick={() => setShowTable((v) => !v)}
        >
          {showTable ? "Hide data" : "View data"}
        </button>
      </figcaption>
      {loading && slow && (
        <div className="trend-progress" role="progressbar" aria-label={`Loading ${title}`} />
      )}
      <div
        ref={container}
        className="trend-canvas"
        style={{ height }}
        role="slider"
        aria-roledescription="chart cursor"
        tabIndex={0}
        aria-label={`${title}: arrow keys move the cursor; View data shows a table`}
        aria-valuemin={0}
        aria-valuemax={Math.max(0, data.actual.length - 1)}
        aria-valuenow={Math.max(0, position)}
        aria-valuetext={pointText}
        onKeyDown={onKeyDown}
      />
      {showTable && (
        <div id={tableId} className="data-table-wrap">
          <table className="data-table">
            <caption className="visually-hidden">
              {title}
              {data.actual.length > MAX_TABLE_ROWS ? ` (latest ${MAX_TABLE_ROWS} points)` : ""}
            </caption>
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col" className="num">
                  {settings.actualName ?? "Actual"} ({settings.unit})
                </th>
                {data.predicted?.length ? (
                  <th scope="col" className="num">
                    {settings.predictedName ?? "Predicted"} ({settings.unit})
                  </th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {rows.map(([t, v]) => (
                <tr key={t}>
                  <td title={formatIso(new Date(t))}>{formatDateTime(new Date(t))}</td>
                  <td className="num">{tableValue(v)}</td>
                  {data.predicted?.length ? (
                    <td className="num">{tableValue(predicted.get(t))}</td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </figure>
  );
}
