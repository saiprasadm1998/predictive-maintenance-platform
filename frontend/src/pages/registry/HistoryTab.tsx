import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { fetchJob } from "../../api/models";
import {
  type HistoryOptions,
  type HistoryReport,
  fetchAllTags,
  loadHistory,
  uploadHistory,
} from "../../api/registry";
import { formatDateTime } from "../../app/format";
import { useAnnounce } from "../../app/liveContext";
import { Field, Problems } from "./common";
import { REJECT_REASONS } from "./registryModel";

const DEFAULTS: Omit<HistoryOptions, "source"> = {
  layout: null,
  mode: "skip",
  naive_as_utc: false,
  ts_column: "ts",
  tag_column: "tag",
  value_column: "value",
  quality_column: "quality",
};

/**
 * UC-02: import history from a CSV or Parquet file. A preview reads the whole file without
 * storing anything (rows, time range, tags, rejected rows by reason, samples already
 * stored); the import then loads the same upload. Both run as background jobs.
 */
export function HistoryTab({ editable }: { editable: boolean }) {
  const client = useQueryClient();
  const announce = useAnnounce();
  const fileId = useId();
  const sourcesId = useId();
  const tags = useQuery({
    queryKey: ["tags", "all"],
    queryFn: ({ signal }) => fetchAllTags(signal),
    enabled: editable,
  });
  const sources = useMemo(
    () => [...new Set((tags.data ?? []).map((t) => t.source))].sort(),
    [tags.data],
  );
  const [file, setFile] = useState<File | null>(null);
  const [options, setOptions] = useState<HistoryOptions>({ source: "", ...DEFAULTS });
  const [upload, setUpload] = useState<string | null>(null);
  const [previewJob, setPreviewJob] = useState<number | null>(null);
  const [importJob, setImportJob] = useState<number | null>(null);

  function change(next: Partial<HistoryOptions>) {
    setOptions({ ...options, ...next });
    setUpload(null);
    setPreviewJob(null);
    setImportJob(null);
  }

  const preview = useMutation({
    mutationFn: () => uploadHistory(file!, { ...options, source: options.source.trim() }, true),
    onSuccess: (queued) => {
      setUpload(queued.upload_id);
      setPreviewJob(queued.job_id);
      setImportJob(null);
    },
  });
  const load = useMutation({
    mutationFn: () => loadHistory(upload!, { ...options, source: options.source.trim() }),
    onSuccess: (queued) => setImportJob(queued.job_id),
  });

  if (!editable) return <p className="muted">Model Engineers and Administrators import history.</p>;
  const ready = !!file && !!options.source.trim();

  return (
    <section className="panel" aria-labelledby="history-title">
      <h2 id="history-title" className="panel-title">
        History import
      </h2>
      <p className="muted small">
        Long format (one row per sample: time, tag, value, optional quality) or wide format (a time
        column and one column per tag), as CSV or Parquet. Tags are matched by their source name
        within the chosen source. Times need a time zone unless you choose UTC below.
      </p>
      <div className="form-grid">
        <label className="field" htmlFor={fileId}>
          <span>File</span>
          <input
            id={fileId}
            className="control"
            type="file"
            accept=".csv,.parquet"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              change({});
            }}
          />
        </label>
        <Field label="Source (gateway)">
          <input
            className="control"
            list={sourcesId}
            value={options.source}
            onChange={(e) => change({ source: e.target.value })}
          />
        </Field>
        <datalist id={sourcesId}>
          {sources.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
        <Field label="Format">
          <select
            className="control"
            value={options.layout ?? ""}
            onChange={(e) =>
              change({ layout: (e.target.value || null) as HistoryOptions["layout"] })
            }
          >
            <option value="">Detect from the columns</option>
            <option value="long">Long: time, tag, value</option>
            <option value="wide">Wide: one column per tag</option>
          </select>
        </Field>
        <Field label="Samples already stored">
          <select
            className="control"
            value={options.mode}
            onChange={(e) => change({ mode: e.target.value as HistoryOptions["mode"] })}
          >
            <option value="skip">Keep them (skip the file's)</option>
            <option value="overwrite">Replace them with the file's</option>
          </select>
        </Field>
        <label className="field-inline builder-wide">
          <input
            type="checkbox"
            checked={options.naive_as_utc}
            onChange={(e) => change({ naive_as_utc: e.target.checked })}
          />
          <span>Times without a time zone are UTC</span>
        </label>
        <details className="builder-wide">
          <summary>Column names</summary>
          <div className="form-grid">
            {(["ts_column", "tag_column", "value_column", "quality_column"] as const).map((key) => (
              <Field key={key} label={key.replace("_column", "").replace("ts", "time")}>
                <input
                  className="control mono"
                  value={options[key]}
                  onChange={(e) => change({ [key]: e.target.value })}
                />
              </Field>
            ))}
          </div>
        </details>
      </div>
      <div className="builder-buttons">
        <button
          type="button"
          className="button"
          disabled={!ready || preview.isPending}
          onClick={() => preview.mutate()}
        >
          Preview
        </button>
      </div>
      <Problems error={preview.error ?? load.error} />
      {previewJob !== null && (
        <JobResult
          jobId={previewJob}
          title="Preview (nothing stored)"
          onDone={(report) =>
            announce(report.error ? "The file cannot be imported" : "Preview ready")
          }
          action={
            importJob === null && (
              <button
                type="button"
                className="button button-primary"
                disabled={load.isPending}
                onClick={() => load.mutate()}
              >
                Import
              </button>
            )
          }
        />
      )}
      {importJob !== null && (
        <JobResult
          jobId={importJob}
          title="Import"
          onDone={(report) => {
            announce(report.error ? "The import failed" : "History imported");
            void client.invalidateQueries({
              predicate: (q) => ["fleet", "assets", "sensors"].includes(String(q.queryKey[0])),
            });
          }}
        />
      )}
    </section>
  );
}

function JobResult({
  jobId,
  title,
  onDone,
  action,
}: {
  jobId: number;
  title: string;
  onDone: (report: HistoryReport) => void;
  action?: React.ReactNode;
}) {
  const announced = useRef(false);
  const job = useQuery({
    queryKey: ["jobs", jobId],
    queryFn: ({ signal }) => fetchJob(jobId, signal),
    refetchInterval: (q) =>
      q.state.data && ["succeeded", "failed"].includes(q.state.data.status) ? false : 1500,
  });
  const data = job.data;
  const finished = data && ["succeeded", "failed"].includes(data.status);
  const report = (data?.result ?? null) as HistoryReport | null;
  useEffect(() => {
    if (finished && report && !announced.current) {
      announced.current = true;
      onDone(report);
    }
  }, [finished, report, onDone]);

  return (
    <div className="registry-report" aria-live="polite">
      <h3 className="panel-subtitle">{title}</h3>
      {!finished ? (
        <label className="field builder-progress">
          <span>
            {data?.status === "queued" ? "Waiting for the worker…" : "Reading the file"}
            {data?.progress != null ? `: ${Math.round(data.progress)} %` : "…"}
          </span>
          <progress max={100} value={data?.progress ?? undefined} />
        </label>
      ) : data.status === "failed" || !report ? (
        <p role="alert" className="form-error">
          The job failed: {data.error ?? "no result"}
        </p>
      ) : report.error ? (
        <p role="alert" className="form-error">
          The file cannot be imported: {report.error}
        </p>
      ) : (
        <HistorySummary report={report} action={action} />
      )}
    </div>
  );
}

function HistorySummary({ report, action }: { report: HistoryReport; action?: React.ReactNode }) {
  const n = (v: number) => v.toLocaleString("en-GB");
  const unmapped = Object.keys(report.unmapped_tags);
  const reasons = Object.entries(report.rejected_by_reason);
  return (
    <>
      <table className="summary-table">
        <caption className="visually-hidden">
          {report.preview ? "What the import would do" : "What the import did"}
        </caption>
        <tbody>
          <tr>
            <th scope="row">Format</th>
            <td>{report.layout ?? "—"}</td>
          </tr>
          <tr>
            <th scope="row">Samples read</th>
            <td className="num">{n(report.rows_read)}</td>
          </tr>
          {report.preview ? (
            <tr>
              <th scope="row">Would load</th>
              <td className="num">
                {n(report.rows_read - report.rejected)} ({n(report.overlap)} already stored)
              </td>
            </tr>
          ) : (
            <>
              <tr>
                <th scope="row">Loaded</th>
                <td className="num">{n(report.loaded)}</td>
              </tr>
              <tr>
                <th scope="row">Duplicates</th>
                <td className="num">{n(report.duplicates)}</td>
              </tr>
            </>
          )}
          <tr>
            <th scope="row">Rejected</th>
            <td className="num">
              {n(report.rejected)}
              {reasons.length > 0 &&
                ` (${reasons.map(([r, c]) => `${REJECT_REASONS[r] ?? r}: ${n(c)}`).join("; ")})`}
            </td>
          </tr>
          <tr>
            <th scope="row">Time range</th>
            <td>
              {report.first_ts && report.last_ts
                ? `${formatDateTime(new Date(report.first_ts))} – ${formatDateTime(new Date(report.last_ts))}`
                : "—"}
            </td>
          </tr>
          <tr>
            <th scope="row">Tags</th>
            <td>{n(report.tags_found)}</td>
          </tr>
          {unmapped.length > 0 && (
            <tr>
              <th scope="row">Not registered</th>
              <td className="mono">{unmapped.join(", ")}</td>
            </tr>
          )}
          {!report.preview && (
            <tr>
              <th scope="row">Counts reconcile</th>
              <td>{report.reconciles ? "✔ yes" : "✖ no"}</td>
            </tr>
          )}
        </tbody>
      </table>
      {report.problems.length > 0 && (
        <details>
          <summary>First rejected rows ({report.problems.length})</summary>
          <ul className="plain-list">
            {report.problems.map((p, i) => (
              <li key={i}>
                Row {p.row}: {REJECT_REASONS[p.reason] ?? p.reason} ({p.detail})
              </li>
            ))}
          </ul>
        </details>
      )}
      {action && <div className="builder-buttons">{action}</div>}
    </>
  );
}
