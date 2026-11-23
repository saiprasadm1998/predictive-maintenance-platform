/**
 * Time-series chart drawn as SVG with the chart classes of tpm.css: lines, a dashed
 * prediction, an expected band, warning and alert limits, and hatched periods where the
 * model was not scoring normally.
 */
import { type ReactNode, useId } from "react";

import { formatDateTime } from "../app/format";

export type Pt = [number, number | null];

export interface Series {
  points: Pt[];
  cls: "pv" | "pv1" | "est" | "s3" | "s4";
}

export interface ChartProps {
  from: number;
  to: number;
  series: Series[];
  band?: [number, number, number][];
  limits?: { value: number; cls: "lw" | "la" | "thr" }[];
  hatched?: { from: number; to: number }[];
  /** Forecast cone: lower and upper bounds over time. */
  cone?: [number, number, number][];
  now?: number;
  yMin?: number;
  yMax?: number;
  yTitle?: string;
  height?: number;
  width?: number;
  label: string;
  onPick?: (t: number) => void;
  children?: ReactNode;
}

const L = 44;
const R = 12;
const T = 16;

function niceStep(raw: number): number {
  const p = 10 ** Math.floor(Math.log10(raw));
  const f = raw / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
}

function tickLabel(v: number): string {
  if (Math.abs(v) >= 1000) return v.toFixed(0);
  if (Math.abs(v) >= 10) return v.toFixed(0);
  return Number(v.toFixed(1)).toString();
}

function day(t: number, span: number): string {
  const s = formatDateTime(new Date(t));
  return span > 2 * 86_400_000 ? s.slice(0, 6) : s.slice(7) || s;
}

export function Chart(props: ChartProps) {
  const id = useId();
  const W = props.width ?? 640;
  const H = props.height ?? 240;
  const B = 28;
  const values: number[] = [];
  props.series.forEach((s) => s.points.forEach(([, v]) => v !== null && values.push(v)));
  props.band?.forEach(([, lo, hi]) => values.push(lo, hi));
  props.cone?.forEach(([, lo, hi]) => values.push(lo, hi));
  props.limits?.forEach((l) => values.push(l.value));
  const dataLo = values.length ? Math.min(...values) : 0;
  const dataHi = values.length ? Math.max(...values) : 1;
  const rawLo = props.yMin ?? dataLo;
  const rawHi = props.yMax ?? dataHi;
  const step = niceStep(Math.max(rawHi - rawLo, 1e-9) / 4);
  const lo = props.yMin ?? Math.floor(rawLo / step) * step;
  let hi = props.yMax ?? Math.ceil(rawHi / step) * step;
  if (hi <= lo) hi = lo + step * 4;
  const span = Math.max(1, props.to - props.from);
  const x = (t: number) => L + ((t - props.from) / span) * (W - L - R);
  const y = (v: number) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);

  const path = (pts: Pt[]) => {
    let d = "";
    let pen = false;
    for (const [t, v] of pts) {
      if (v === null || t < props.from || t > props.to) {
        pen = false;
        continue;
      }
      d += `${pen ? "L" : "M"}${x(t).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    }
    return d;
  };
  const area = (pts: [number, number, number][]) => {
    const inside = pts.filter(([t]) => t >= props.from && t <= props.to);
    if (inside.length < 2) return "";
    const top = inside.map(([t, , h]) => `${x(t).toFixed(1)},${y(h).toFixed(1)}`);
    const bottom = [...inside].reverse().map(([t, l]) => `${x(t).toFixed(1)},${y(l).toFixed(1)}`);
    return `M${top.join("L")}L${bottom.join("L")}Z`;
  };
  const ticks: number[] = [];
  for (let v = lo; v <= hi + step / 1000; v += step) ticks.push(v);

  return (
    <svg
      className="chart"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={props.label}
      onClick={
        props.onPick
          ? (e) => {
              const box = e.currentTarget.getBoundingClientRect();
              const px = ((e.clientX - box.left) / box.width) * W;
              if (px >= L && px <= W - R)
                props.onPick?.(props.from + ((px - L) / (W - L - R)) * span);
            }
          : undefined
      }
      style={props.onPick ? { cursor: "crosshair" } : undefined}
    >
      <defs>
        <pattern
          id={`${id}-h`}
          width="6"
          height="6"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(45)"
        >
          <rect width="6" height="6" className="hg" />
          <line x1="0" y1="0" x2="0" y2="6" className="hs" />
        </pattern>
      </defs>
      {ticks.map((v, i) => (
        <g key={i}>
          <line className={i === 0 ? "ax" : "g"} x1={L} x2={W - R} y1={y(v)} y2={y(v)} />
          <text x={L - 6} y={y(v) + 4} textAnchor="end">
            {tickLabel(v)}
          </text>
        </g>
      ))}
      {props.yTitle && (
        <text x={L} y={10} style={{ fontWeight: 600 }}>
          {props.yTitle}
        </text>
      )}
      {props.hatched?.map((h, i) => {
        const a = Math.max(props.from, h.from);
        const b = Math.min(props.to, h.to);
        if (b <= a) return null;
        return (
          <rect
            key={i}
            x={x(a)}
            y={T}
            width={Math.max(2, x(b) - x(a))}
            height={H - T - B}
            fill={`url(#${id}-h)`}
            opacity={0.8}
          />
        );
      })}
      {props.band && <path className="band" d={area(props.band)} opacity={0.8} />}
      {props.cone && <path className="cone" d={area(props.cone)} />}
      {props.limits?.map((l, i) =>
        l.value >= lo && l.value <= hi ? (
          <line key={i} className={l.cls} x1={L} x2={W - R} y1={y(l.value)} y2={y(l.value)} />
        ) : null,
      )}
      {props.now !== undefined && props.now > props.from && props.now < props.to && (
        <line className="now" x1={x(props.now)} x2={x(props.now)} y1={T} y2={H - B} />
      )}
      {props.series.map((s, i) => (
        <path key={i} className={s.cls} d={path(s.points)} />
      ))}
      <text x={L} y={H - 8}>
        {day(props.from, span)}
      </text>
      <text x={(L + W - R) / 2} y={H - 8} textAnchor="middle">
        {day(props.from + span / 2, span)}
      </text>
      <text x={W - R} y={H - 8} textAnchor="end">
        {day(props.to, span)}
      </text>
      {props.children}
    </svg>
  );
}

export function Legend({ items }: { items: { cls?: string; label: string }[] }) {
  return (
    <div className="lg">
      {items.map((i) => (
        <span key={i.label}>
          <i className={i.cls} />
          {i.label}
        </span>
      ))}
    </div>
  );
}
