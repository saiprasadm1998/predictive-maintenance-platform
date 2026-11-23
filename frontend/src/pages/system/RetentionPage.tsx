import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { type Retention, type RetentionItem, fetchRetention, saveRetention } from "../../api/admin";
import { errorMessages } from "../../api/client";
import { HowTo, Loading, PageHeader, Panel, Problems } from "../../components/ui";

const YEAR = 365;
const stamp = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString("en-GB", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Not yet";

function size(bytes: number | null): string {
  if (bytes === null) return "n/a";
  if (bytes < 0.1 * 1024 ** 3) return "<0.1 GB";
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

/** The period in the unit the screen shows it. */
function shown(item: RetentionItem, days: number): string {
  return item.unit === "years" ? String(Math.round((days / YEAR) * 10) / 10) : String(days);
}

function toDays(item: RetentionItem, value: string): number {
  const n = Number(value);
  return item.unit === "years" ? Math.round(n * YEAR) : Math.round(n);
}

function minText(item: RetentionItem): string {
  return item.unit === "years" && item.min_days >= YEAR
    ? `${Math.round((item.min_days / YEAR) * 10) / 10} years`
    : `${item.min_days} days`;
}

function Form({ r }: { r: Retention }) {
  const client = useQueryClient();
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(r.items.map((i) => [i.kind, shown(i, i.days)])),
  );
  const problems = r.items
    .filter((i) => {
      const v = values[i.kind] ?? "";
      return v.trim() === "" || !Number.isFinite(Number(v)) || toDays(i, v) < i.min_days;
    })
    .map((i) => `${i.label}: at least ${minText(i)}`);
  const days = Object.fromEntries(r.items.map((i) => [i.kind, toDays(i, values[i.kind] ?? "0")]));
  const changed = r.items.some((i) => days[i.kind] !== i.days);
  const save = useMutation({
    mutationFn: () => saveRetention(days),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["retention"] }),
  });
  return (
    <>
      <PageHeader
        title="Retention"
        sub="How long each kind of data is kept before the nightly clean-up removes it"
        actions={
          <>
            <HowTo title="Retention">
              The clean-up runs once a night and removes what is older than each period. Training
              periods of deployed models are kept regardless, so a model can always be retrained.
              The minimums protect records the plant must keep.
            </HowTo>
            <button
              className="btn btn-p"
              type="button"
              disabled={!changed || problems.length > 0 || save.isPending}
              onClick={() => save.mutate()}
            >
              Save
            </button>
          </>
        }
      />
      <section
        className="strip"
        style={{ gridTemplateColumns: "repeat(4, minmax(0, 1fr))" }}
        aria-label="Storage and clean-up"
      >
        <div>
          <span className="l">Database size</span>
          <span className="v">
            {(r.database_bytes / 1024 ** 3).toFixed(1)}
            <small>GB</small>
          </span>
        </div>
        <div>
          <span className="l">Raw samples kept</span>
          <span className="v">
            {r.raw_samples === null
              ? "n/a"
              : r.raw_samples >= 1e6
                ? (r.raw_samples / 1e6).toFixed(0)
                : r.raw_samples.toLocaleString()}
            {r.raw_samples !== null && r.raw_samples >= 1e6 && <small>million</small>}
          </span>
        </div>
        <div>
          <span className="l">Last clean-up</span>
          <span className="v">
            {stamp(r.last_run_at)}
            {r.last_removed !== null && (
              <small>removed {r.last_removed.toLocaleString()} rows</small>
            )}
          </span>
        </div>
        <div>
          <span className="l">Next clean-up</span>
          <span className="v">{stamp(r.next_run_at)}</span>
        </div>
      </section>
      <Panel title="Retention periods" className="fill">
        <div className="tw">
          <table className="tb">
            <thead>
              <tr>
                <th>Data</th>
                <th>Keep for</th>
                <th>Minimum</th>
                <th style={{ textAlign: "right" }}>Size now</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {r.items.map((i) => (
                <tr key={i.kind}>
                  <td>
                    <b>{i.label}</b>
                  </td>
                  <td>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                      <input
                        className="in num"
                        style={{ width: 80, height: 32 }}
                        aria-label={`${i.label}, ${i.unit}`}
                        value={values[i.kind] ?? ""}
                        onChange={(e) => setValues({ ...values, [i.kind]: e.target.value })}
                      />
                      <span className="sec s13">{i.unit}</span>
                    </span>
                  </td>
                  <td className="sec">{minText(i)}</td>
                  <td className="num" style={{ textAlign: "right" }}>
                    {size(i.size_bytes)}
                  </td>
                  <td className="sec">{i.note || "None"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Problems messages={problems} />
        <Problems messages={save.isError ? errorMessages(save.error) : []} />
      </Panel>
    </>
  );
}

export function RetentionPage() {
  const r = useQuery({ queryKey: ["retention"], queryFn: ({ signal }) => fetchRetention(signal) });
  if (r.isPending) return <Loading what="retention" />;
  if (r.isError) return <Problems messages={errorMessages(r.error)} />;
  return <Form key={JSON.stringify(r.data.items.map((i) => i.days))} r={r.data} />;
}
