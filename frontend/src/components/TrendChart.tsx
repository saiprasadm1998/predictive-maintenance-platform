import { useEffect, useId, useMemo, useRef, useState } from "react";

import { formatDateTime, formatIso } from "../app/format";
import { chartColors, echarts } from "./charting";
import { type TrendData, type TrendSettings, trendOptions } from "./trendOptions";

const MAX_TABLE_ROWS = 2000;

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
}: {
  title: string;
  data: TrendData;
  settings: TrendSettings;
  height?: number;
  group?: string;
  loading?: boolean;
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
    ? `${formatDateTime(new Date(point[0]))}: ${point[1] ?? "no value"} ${point[1] === null ? "" : settings.unit}`.trim()
    : "No point selected";
  const rows = data.actual.slice(-MAX_TABLE_ROWS);
  const predicted = new Map(data.predicted?.map(([t, v]) => [t, v]));
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
                    Predicted ({settings.unit})
                  </th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {rows.map(([t, v]) => (
                <tr key={t}>
                  <td title={formatIso(new Date(t))}>{formatDateTime(new Date(t))}</td>
                  <td className="num">{v ?? "—"}</td>
                  {data.predicted?.length ? (
                    <td className="num">{predicted.get(t) ?? "—"}</td>
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
