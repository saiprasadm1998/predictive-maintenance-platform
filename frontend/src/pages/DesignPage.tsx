import { useMemo, useState } from "react";

import { AlertStateChip } from "../components/AlertStateChip";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { HealthBar } from "../components/HealthBar";
import { HealthScore } from "../components/HealthScore";
import { StatusChip } from "../components/StatusChip";
import { ALERT_STATES, BANDS, NE107, SEVERITIES } from "../components/status";
import { TrendChart } from "../components/TrendChart";
import type { TrendData } from "../components/trendOptions";

/** Development only (/design): every shared component with sample data, for review. */
export function DesignPage() {
  const [open, setOpen] = useState(false);
  const [now] = useState(() => Date.now());
  const { data, settings } = useMemo(() => sample(now), [now]);
  return (
    <div style={{ display: "grid", gap: 12, maxWidth: 1100 }}>
      <section className="panel">
        <h2 className="panel-title">Status chips (PDS §3.2)</h2>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
          {BANDS.map((b) => (
            <StatusChip
              key={b}
              kind="band"
              value={b}
              detail={b === "Unknown" ? "insufficient data" : null}
            />
          ))}
          {SEVERITIES.map((s) => (
            <StatusChip key={s} kind="severity" value={s} />
          ))}
          {NE107.map((n) => (
            <StatusChip
              key={n}
              kind="ne107"
              value={n}
              detail={n === "Failure" ? "flatline" : null}
              size="s"
            />
          ))}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 16, marginTop: 12 }}>
          {ALERT_STATES.map((state) => (
            <AlertStateChip
              key={state}
              state={state}
              severity="Alert"
              shelvedUntil={new Date(now + 3 * 3_600_000 + 20 * 60_000)}
            />
          ))}
          <AlertStateChip state="Active-Unacknowledged" severity="Warning" />
        </div>
      </section>
      <section className="panel" style={{ display: "flex", gap: 40, alignItems: "center" }}>
        <HealthScore health={41} band="Alert" di={29.5} diWarning={15} diAlert={25} />
        <HealthScore health={null} band="Unknown" di={null} unknownReason="no data" />
        <div style={{ display: "grid", gap: 8 }}>
          <HealthBar health={38} warningAt={60} alertAt={40} />
          <HealthBar health={94} warningAt={60} alertAt={40} />
          <HealthBar health={null} />
        </div>
      </section>
      <section className="panel">
        <TrendChart title="TI-1012 DE bearing temperature" data={data} settings={settings} />
        <TrendChart
          title="Deviation Index"
          data={{
            actual: data.actual.map(([t, v]) => [t, v === null ? null : Math.max(0, (v - 75) * 3)]),
          }}
          settings={{ ...settings, unit: "%", actualName: "DI" }}
          height={140}
        />
      </section>
      <section className="panel">
        <button type="button" className="button" onClick={() => setOpen(true)}>
          Shelve alert…
        </button>
        <ConfirmDialog
          open={open}
          onOpenChange={setOpen}
          title="Shelve 1 alert"
          consequence="The alert stops showing as active until the shelf ends (at most 7 days)."
          confirmLabel="Shelve"
          reasonLabel="Reason"
          onConfirm={() => new Promise((resolve) => setTimeout(resolve, 600))}
        />
      </section>
    </div>
  );
}

function sample(now: number): {
  data: TrendData;
  settings: { unit: string; from: number; to: number };
} {
  const from = now - 24 * 3_600_000;
  const step = 5 * 60_000;
  const actual: [number, number | null][] = [];
  const predicted: [number, number | null][] = [];
  const band: [number, number, number][] = [];
  for (let t = from; t <= now; t += step) {
    const h = (t - from) / 3_600_000;
    const p = 78 + 2 * Math.sin(h / 3);
    const drift = h > 14 ? (h - 14) * 0.9 : 0;
    actual.push([t, h > 9 && h < 9.4 ? null : +(p + drift + Math.sin(h * 7) * 0.6).toFixed(2)]);
    predicted.push([t, +p.toFixed(2)]);
    band.push([t, +(p - 3).toFixed(2), +(p + 3).toFixed(2)]);
  }
  return {
    data: {
      actual,
      predicted,
      band,
      limits: { warning: [86], alert: [90] },
      excluded: [
        { from: from + 4 * 3_600_000, to: from + 5 * 3_600_000, reason: "outside operating mode" },
      ],
      bad: [from + 9.1 * 3_600_000, from + 9.3 * 3_600_000],
      alerts: [{ from: from + 20 * 3_600_000, to: now, severity: "Warning" }],
    },
    settings: { unit: "°C", from, to: now },
  };
}
