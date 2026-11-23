import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { fetchUsers } from "../../api/admin";
import { errorMessages } from "../../api/client";
import { fetchIngestionHealth } from "../../api/ingestion";
import { fetchJob } from "../../api/models";
import {
  type HistoryOptions,
  type HistoryReport,
  type QueuedJob,
  fetchImports,
  loadHistory,
  uploadHistory,
} from "../../api/registry";
import {
  Dialog,
  HowTo,
  ICONS,
  Kpis,
  Loading,
  PageHeader,
  Panel,
  Pill,
  Problems,
  type StepItem,
  Steps,
} from "../../components/ui";
import { REJECT_REASONS } from "../registry/registryModel";
import { useEquipmentSetup } from "./setupModel";

const DAY = 86_400_000;
const short = (iso: string) =>
  new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
const stamp = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

/** Column names and the first rows of a CSV, read in the browser. */
async function peek(file: File): Promise<{ columns: string[]; rows: string[][] } | null> {
  if (!file.name.toLowerCase().endsWith(".csv")) return null;
  const text = await file.slice(0, 64 * 1024).text();
  const lines = text
    .split(/\r?\n/)
    .filter((l) => l.trim())
    .slice(0, 6);
  const split = (l: string) => l.split(",").map((c) => c.trim().replace(/^"|"$/g, ""));
  const [head, ...rows] = lines.map(split);
  return head ? { columns: head, rows: rows.slice(0, 4) } : null;
}

function guess(columns: string[], patterns: RegExp[], fallback: string): string {
  for (const p of patterns) {
    const hit = columns.find((c) => p.test(c));
    if (hit) return hit;
  }
  return columns.includes(fallback) ? fallback : (columns[0] ?? fallback);
}

function useJob(job: QueuedJob | null) {
  return useQuery({
    queryKey: ["jobs", job?.job_id],
    queryFn: ({ signal }) => fetchJob(job!.job_id, signal),
    enabled: !!job,
    refetchInterval: (q) =>
      q.state.data && ["succeeded", "failed"].includes(q.state.data.status) ? false : 1000,
  });
}

/** What an import of a checked file will store: valid, new rows (or every valid row when
 * stored samples are replaced). */
function toLoad(report: HistoryReport, overwrite: boolean): number {
  const valid = report.rows_read - report.rejected - report.duplicates;
  return Math.max(0, overwrite ? valid : valid - report.overlap);
}

function ReportTable({
  report,
  overwrite = false,
}: {
  report: HistoryReport;
  overwrite?: boolean;
}) {
  const rejected = Object.entries(report.rejected_by_reason ?? {});
  const unmapped = Object.entries(report.unmapped_tags ?? {});
  return (
    <>
      <dl className="kvs">
        <dt>Rows read</dt>
        <dd>{report.rows_read.toLocaleString()}</dd>
        <dt>Tags found</dt>
        <dd>{report.tags_found}</dd>
        <dt>Time span</dt>
        <dd>
          {report.first_ts && report.last_ts
            ? `${stamp(report.first_ts)} to ${stamp(report.last_ts)}`
            : "n/a"}
        </dd>
        <dt>{report.preview ? "Would load" : "Loaded"}</dt>
        <dd>{(report.preview ? toLoad(report, overwrite) : report.loaded).toLocaleString()}</dd>
        <dt>Already stored</dt>
        <dd>{report.overlap.toLocaleString()}</dd>
        <dt>Rejected</dt>
        <dd>{report.rejected.toLocaleString()}</dd>
      </dl>
      {rejected.length > 0 && (
        <div className="notice" style={{ borderLeftColor: "var(--traverse-status-warning-fg)" }}>
          {rejected.map(([k, n]) => (
            <div key={k}>
              {REJECT_REASONS[k] ?? k}: {n.toLocaleString()} rows
            </div>
          ))}
          {unmapped.length > 0 && (
            <div>
              Not registered:{" "}
              {unmapped
                .slice(0, 5)
                .map(([t, n]) => `${t} (${n})`)
                .join(", ")}
              {unmapped.length > 5 ? ` and ${unmapped.length - 5} more` : ""}. Register them in Tags
              and mapping, then upload again.
            </div>
          )}
        </div>
      )}
    </>
  );
}

/** Upload history: choose a file, match its columns, check it, import it. */
export function UploadDialog({ onClose }: { onClose: () => void }) {
  const client = useQueryClient();
  const health = useQuery({
    queryKey: ["ingestion", "health"],
    queryFn: ({ signal }) => fetchIngestionHealth(signal),
  });
  const [step, setStep] = useState(1);
  const [file, setFile] = useState<File | null>(null);
  const [sample, setSample] = useState<{ columns: string[]; rows: string[][] } | null>(null);
  const [options, setOptions] = useState<HistoryOptions>({
    source: "",
    layout: null,
    mode: "skip",
    naive_as_utc: false,
    ts_column: "ts",
    tag_column: "tag",
    value_column: "value",
    quality_column: "quality",
  });
  const [previewJob, setPreviewJob] = useState<QueuedJob | null>(null);
  const [importJob, setImportJob] = useState<QueuedJob | null>(null);
  const preview = useJob(previewJob);
  const imported = useJob(importJob);
  const sources = (health.data?.sources ?? []).map((s) => s.source);
  const source = options.source || sources[0] || "";

  const choose = async (f: File | null) => {
    setFile(f);
    setPreviewJob(null);
    if (!f) return setSample(null);
    const s = await peek(f);
    setSample(s);
    if (s) {
      const cols = s.columns;
      const long = cols.length <= 5 && cols.some((c) => /tag|name|point/i.test(c));
      setOptions((o) => ({
        ...o,
        layout: long ? "long" : "wide",
        ts_column: guess(cols, [/^ts$/i, /time/i, /date/i], "ts"),
        tag_column: guess(cols, [/^tag$/i, /tag/i, /name|point/i], "tag"),
        value_column: guess(cols, [/^value$/i, /val/i], "value"),
        quality_column: guess(cols, [/^quality$/i, /qual/i, /status/i], "quality"),
      }));
    }
  };
  const send = useMutation({
    mutationFn: () => uploadHistory(file!, { ...options, source }, true),
    onSuccess: (job) => {
      setPreviewJob(job);
      setStep(3);
    },
  });
  const load = useMutation({
    mutationFn: () => loadHistory(previewJob!.upload_id, { ...options, source }),
    onSuccess: (job) => {
      setImportJob(job);
      setStep(4);
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ["tags", "coverage"] });
      void client.invalidateQueries({ queryKey: ["imports"] });
    },
  });
  const pReport = preview.data?.result as HistoryReport | null | undefined;
  const iReport = imported.data?.result as HistoryReport | null | undefined;
  const pDone = preview.data && ["succeeded", "failed"].includes(preview.data.status);
  const iDone = imported.data && ["succeeded", "failed"].includes(imported.data.status);

  const labels = ["Choose file", "Match columns", "Check", "Import"];
  const steps: StepItem[] = labels.map((label, i) => ({
    label,
    state: i + 1 === step ? "on" : i + 1 < step ? "done" : "todo",
    onClick: i + 1 < step && step < 4 ? () => setStep(i + 1) : undefined,
  }));
  const set = (k: keyof HistoryOptions) => (e: { target: { value: string } }) =>
    setOptions({ ...options, [k]: e.target.value });

  return (
    <Dialog
      open
      wide
      onOpenChange={(o) => !o && onClose()}
      title="Upload history"
      footer={
        <>
          <button
            className="btn btn-s"
            type="button"
            disabled={step === 1 || step === 4}
            onClick={() => setStep(step - 1)}
          >
            Back
          </button>
          {step === 1 && (
            <button
              className="btn btn-p"
              type="button"
              disabled={!file || !source}
              onClick={() => setStep(2)}
            >
              Continue
            </button>
          )}
          {step === 2 && (
            <button
              className="btn btn-p"
              type="button"
              disabled={send.isPending}
              onClick={() => send.mutate()}
            >
              {send.isPending ? "Uploading…" : "Check the file"}
            </button>
          )}
          {step === 3 && (
            <button
              className="btn btn-p"
              type="button"
              disabled={
                !pDone ||
                preview.data?.status === "failed" ||
                !!pReport?.error ||
                !pReport ||
                toLoad(pReport, options.mode === "overwrite") === 0 ||
                load.isPending
              }
              onClick={() => load.mutate()}
            >
              Import {pReport ? toLoad(pReport, options.mode === "overwrite").toLocaleString() : ""}{" "}
              samples
            </button>
          )}
          {step === 4 && (
            <button className="btn btn-p" type="button" disabled={!iDone} onClick={onClose}>
              Done
            </button>
          )}
        </>
      }
    >
      <Steps steps={steps} label="Upload steps" />
      {step === 1 && (
        <div className="fg">
          <div className="fld span2">
            <label htmlFor="hu-f">
              File (CSV or Parquet: time, tag, value, quality; or one column per tag)
            </label>
            <input
              id="hu-f"
              className="in"
              type="file"
              accept=".csv,.parquet"
              style={{ paddingTop: 7 }}
              onChange={(e) => void choose(e.target.files?.[0] ?? null)}
            />
          </div>
          <div className="fld">
            <label htmlFor="hu-s">Gateway the tags belong to</label>
            <select id="hu-s" className="sl" value={source} onChange={set("source")}>
              {sources.length === 0 && <option value="">No gateways yet</option>}
              {sources.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="fld">
            <label htmlFor="hu-m">Samples already stored</label>
            <select id="hu-m" className="sl" value={options.mode} onChange={set("mode")}>
              <option value="skip">Keep the stored value</option>
              <option value="overwrite">Replace with the file</option>
            </select>
          </div>
          <label className="chk span2">
            <input
              type="checkbox"
              checked={options.naive_as_utc}
              onChange={(e) => setOptions({ ...options, naive_as_utc: e.target.checked })}
            />
            Times without a time zone are UTC
          </label>
        </div>
      )}
      {step === 2 && (
        <>
          <p className="sec s13">
            {sample
              ? `Detected ${options.layout} format. Check what each column holds.`
              : "Parquet files are read on the server. Name the columns if they differ from the defaults."}
          </p>
          <div className="fld" style={{ maxWidth: 260 }}>
            <label htmlFor="hu-l">Format</label>
            <select
              id="hu-l"
              className="sl"
              value={options.layout ?? ""}
              onChange={(e) =>
                setOptions({
                  ...options,
                  layout: (e.target.value || null) as HistoryOptions["layout"],
                })
              }
            >
              <option value="">Detect from the columns</option>
              <option value="long">Long: one row per tag and time</option>
              <option value="wide">Wide: one column per tag</option>
            </select>
          </div>
          <div className="fg f4">
            {(
              [
                ["ts_column", "Time"],
                ...(options.layout === "wide"
                  ? []
                  : [
                      ["tag_column", "Tag"],
                      ["value_column", "Value"],
                      ["quality_column", "Quality"],
                    ]),
              ] as [keyof HistoryOptions, string][]
            ).map(([k, label]) => (
              <div className="fld" key={k}>
                <label htmlFor={`hu-${k}`}>{label} column</label>
                {sample ? (
                  <select
                    id={`hu-${k}`}
                    className="sl mono"
                    value={String(options[k])}
                    onChange={set(k)}
                  >
                    {sample.columns.map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    id={`hu-${k}`}
                    className="in mono"
                    value={String(options[k])}
                    onChange={set(k)}
                  />
                )}
              </div>
            ))}
          </div>
          {sample && (
            <div className="tw">
              <table className="tb">
                <thead>
                  <tr>
                    {sample.columns.map((c) => (
                      <th key={c} className="mono">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sample.rows.map((r, i) => (
                    <tr key={i}>
                      {r.map((c, j) => (
                        <td key={j} className="mono">
                          {c}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Problems messages={send.isError ? errorMessages(send.error) : []} />
        </>
      )}
      {step === 3 && (
        <>
          {!pDone && <p className="sec s13">Checking the file. Nothing is stored yet…</p>}
          {preview.data?.status === "failed" && (
            <Problems messages={[preview.data.error ?? "The check failed."]} />
          )}
          {pReport?.error && <Problems messages={[pReport.error]} />}
          {pDone && pReport && !pReport.error && (
            <ReportTable report={pReport} overwrite={options.mode === "overwrite"} />
          )}
          <Problems messages={load.isError ? errorMessages(load.error) : []} />
        </>
      )}
      {step === 4 && (
        <>
          {!iDone && (
            <p className="sec s13">
              Importing
              {imported.data?.progress != null ? `, ${Math.round(imported.data.progress)} %` : ""}…
            </p>
          )}
          {imported.data?.status === "failed" && (
            <Problems messages={[imported.data.error ?? "The import failed."]} />
          )}
          {iDone && iReport && !iReport.error && (
            <>
              <Pill tone={iReport.reconciles ? "success" : "warning"}>
                {iReport.reconciles ? "Counts reconcile" : "Counts do not reconcile"}
              </Pill>
              <ReportTable report={iReport} />
            </>
          )}
        </>
      )}
    </Dialog>
  );
}

export function HistoryPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { rows, loading, tags, coverage } = useEquipmentSetup();
  const imports = useQuery({
    queryKey: ["imports"],
    queryFn: ({ signal }) => fetchImports(signal),
  });
  const users = useQuery({
    queryKey: ["users"],
    queryFn: ({ signal }) => fetchUsers(signal),
    retry: false,
  });
  const upload = params.get("upload") === "1" || location.pathname.endsWith("/upload");
  const openUpload = () => {
    params.set("upload", "1");
    setParams(params);
  };
  const closeUpload = () => {
    if (location.pathname.endsWith("/upload")) void navigate("/setup/history", { replace: true });
    else {
      params.delete("upload");
      setParams(params);
    }
  };
  if (loading)
    return (
      <>
        <Loading what="historical data" />
        {upload && <UploadDialog key="upload" onClose={closeUpload} />}
      </>
    );

  const cov = coverage.data ?? [];
  const byTag = new Map(cov.map((c) => [c.tag_id, c]));
  const first = cov.reduce<number | null>(
    (a, c) => Math.min(a ?? Infinity, Date.parse(c.first_ts)),
    null,
  );
  const last = cov.reduce<number | null>(
    (a, c) => Math.max(a ?? -Infinity, Date.parse(c.last_ts)),
    null,
  );
  const span = first !== null && last !== null ? Math.round((last - first) / DAY) : 0;
  const samples = cov.reduce((a, c) => a + c.samples, 0);
  const runs = imports.data ?? [];
  const lastRun = runs.find((r) => r.status === "succeeded");
  const userName = (id: number | null) =>
    users.data?.find((u) => u.id === id)?.display_name ?? (id ? `User ${id}` : "Gateway");

  const equipment = rows.map((r) => {
    const spans = r.tags.map((t) => byTag.get(t.id)).filter(Boolean) as typeof cov;
    const from = spans.length ? Math.min(...spans.map((c) => Date.parse(c.first_ts))) : null;
    const to = spans.length ? Math.max(...spans.map((c) => Date.parse(c.last_ts))) : null;
    return { r, withData: spans.length, from, to, gaps: Math.max(0, ...spans.map((c) => c.gaps)) };
  });
  const totalGaps = equipment.reduce((a, e) => a + e.gaps, 0);
  const bar = (from: number | null, to: number | null) => {
    if (first === null || last === null || from === null || to === null || last === first)
      return (
        <span
          className="hatch"
          style={{ display: "block", height: 10, width: "100%" }}
          aria-label="No data"
        />
      );
    const left = ((from - first) / (last - first)) * 100;
    const width = Math.max(2, ((to - from) / (last - first)) * 100);
    return (
      <span
        style={{
          position: "relative",
          display: "block",
          height: 10,
          width: "100%",
          background: "var(--traverse-status-unknown-bg)",
          borderRadius: 2,
        }}
      >
        <span
          style={{
            position: "absolute",
            left: `${left}%`,
            width: `${width}%`,
            top: 0,
            bottom: 0,
            background: "var(--traverse-action-primary)",
            borderRadius: 2,
          }}
        />
      </span>
    );
  };

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Setup overview", to: "/setup" }, { label: "Historical data" }]}
        title="Historical data"
        sub="History trains the models. Live data keeps arriving over MQTT."
        actions={
          <>
            <HowTo title="Historical data">
              Upload 6 to 12 months of 1-minute values covering every normal operating mode. Each
              file is checked first: nothing is stored until you import it. Tags must be registered
              before their history can be loaded.
            </HowTo>
            <button className="btn btn-p" type="button" onClick={openUpload}>
              Upload history
            </button>
          </>
        }
      />
      <Kpis
        cols={4}
        label="Stored history"
        items={[
          {
            label: "Span covered",
            value: (
              <>
                {span}
                <small>days</small>
              </>
            ),
            icon: ICONS.database,
            sub:
              first !== null && last !== null
                ? `${short(new Date(first).toISOString())} to ${short(new Date(last).toISOString())}`
                : "No data stored",
          },
          {
            label: "Tags with history",
            value: (
              <>
                {cov.length}
                <small>of {tags.data?.length ?? 0}</small>
              </>
            ),
            icon: ICONS.tag,
            sub: "1-minute values",
          },
          {
            label: "Samples stored",
            value:
              samples >= 1e6 ? (
                <>
                  {(samples / 1e6).toFixed(1)}
                  <small>million</small>
                </>
              ) : (
                samples.toLocaleString()
              ),
            icon: ICONS.database,
            sub:
              lastRun?.result?.rejected != null
                ? `${lastRun.result.rejected.toLocaleString()} rejected in last upload`
                : undefined,
          },
          {
            label: "Gaps over 1 hour",
            value: totalGaps,
            tone: totalGaps ? "warning" : undefined,
            icon: ICONS.alert,
            sub: "Shutdowns and outages, left out of training",
          },
        ]}
      />
      <div className="two">
        <Panel
          title="Coverage by equipment"
          actions={<span className="sec s13">Hatched = no data</span>}
        >
          <div className="tw">
            <table className="tb">
              <thead>
                <tr>
                  <th>Equipment</th>
                  <th>Tags</th>
                  <th>From</th>
                  <th>To</th>
                  <th style={{ width: "40%" }}>Coverage, {span} days</th>
                  <th style={{ textAlign: "right" }}>Gaps</th>
                </tr>
              </thead>
              <tbody>
                {equipment.map(({ r, withData, from, to, gaps }) => (
                  <tr key={r.node.id}>
                    <td>
                      <b className="mono">{r.node.code}</b>
                    </td>
                    <td className="num">
                      {withData} of {r.tags.length}
                    </td>
                    <td>{from ? short(new Date(from).toISOString()) : "n/a"}</td>
                    <td>{to ? short(new Date(to).toISOString()) : "n/a"}</td>
                    <td>{bar(from, to)}</td>
                    <td className="num" style={{ textAlign: "right" }}>
                      {gaps}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        <Panel title="Past uploads">
          {runs.length === 0 ? (
            <p className="sec s13">No uploads yet.</p>
          ) : (
            runs.map((run) => {
              const error = run.status === "failed" || run.result?.error;
              const tone = error
                ? "danger"
                : run.status === "succeeded"
                  ? run.result?.reconciles
                    ? "success"
                    : "warning"
                  : "info";
              const label = error
                ? `Rejected${run.result?.error ? `, ${String(run.result.error).slice(0, 40)}` : ""}`
                : run.status === "succeeded"
                  ? run.result?.reconciles
                    ? "Reconciled"
                    : "Loaded, check counts"
                  : "Importing";
              return (
                <div
                  key={run.job_id}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: 12,
                    padding: "8px 0",
                    borderTop: "1px solid var(--traverse-border-subtle)",
                  }}
                >
                  <span style={{ minWidth: 0 }}>
                    <span className="mono">{run.filename ?? `Import ${run.job_id}`}</span>
                    <br />
                    <span className="sec s13">
                      {userName(run.user_id)}, {stamp(run.created_at)}
                    </span>
                  </span>
                  <Pill tone={tone} trunc title={label}>
                    {label}
                  </Pill>
                </div>
              );
            })
          )}
        </Panel>
      </div>
      {upload && <UploadDialog key="upload" onClose={closeUpload} />}
    </>
  );
}
