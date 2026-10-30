import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { fetchJob, rescoreVersion } from "../../api/models";
import type { ModelDetail, VersionSummary } from "../../api/types";
import { formatDateTime } from "../../app/format";
import { useAnnounce } from "../../app/liveContext";
import { useTimeRange } from "../../app/timeRange";
import { Problems } from "../registry/common";
import { toLocalInput } from "./modelsModel";

/**
 * Re-score a past period (FR-RUN-05, model engineers): the period's scores and sensor
 * outputs are computed again as a background job. Alerts, e-mails and the live status are
 * not touched, and the latest live cycle is never replaced. Starts on the shown range.
 */
export function RescorePanel({ model, version }: { model: ModelDetail; version: VersionSummary }) {
  const client = useQueryClient();
  const announce = useAnnounce();
  const { range } = useTimeRange();
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState(() => toLocalInput(range.from));
  const [to, setTo] = useState(() => toLocalInput(range.to));
  const [jobId, setJobId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const job = useQuery({
    queryKey: ["jobs", jobId],
    queryFn: async ({ signal }) => {
      const found = await fetchJob(jobId!, signal);
      if (found.status === "succeeded") {
        announce(`${model.asset_code} / ${model.name} v${version.version} re-scored`);
        void client.invalidateQueries({
          predicate: (q) => ["scores", "models"].includes(String(q.queryKey[0])),
        });
      }
      return found;
    },
    enabled: jobId !== null,
    refetchInterval: (q) =>
      q.state.data && ["succeeded", "failed"].includes(q.state.data.status) ? false : 2000,
  });

  if (!open) {
    return (
      <button type="button" className="button" onClick={() => setOpen(true)}>
        Re-score…
      </button>
    );
  }
  const start = new Date(from);
  const end = new Date(to);
  const valid = !Number.isNaN(start.getTime()) && !Number.isNaN(end.getTime()) && start < end;
  const running = job.data ? !["succeeded", "failed"].includes(job.data.status) : jobId !== null;
  const result = job.data?.result as { cycles?: number; end?: string } | null | undefined;

  return (
    <section className="panel" aria-labelledby="rescore-title">
      <h2 id="rescore-title" className="panel-title">
        Re-score v{version.version}
      </h2>
      <p className="muted small">
        Replaces this version's scores and sensor outputs for the period, computed again from the
        stored samples with the current DI limits. No alert changes and no e-mail is sent; the
        latest live cycle is kept.
      </p>
      <form
        className="field-row"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            const queued = await rescoreVersion(version.id, start, end);
            setJobId(queued.job_id);
          } catch (caught) {
            setError(caught);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label className="field-inline">
          <span>From</span>
          <input
            className="control"
            type="datetime-local"
            value={from}
            required
            onChange={(e) => setFrom(e.target.value)}
          />
        </label>
        <label className="field-inline">
          <span>To</span>
          <input
            className="control"
            type="datetime-local"
            value={to}
            required
            onChange={(e) => setTo(e.target.value)}
          />
        </label>
        <button
          type="submit"
          className="button button-primary"
          disabled={!valid || busy || running}
        >
          Re-score
        </button>
        <button type="button" className="button" onClick={() => setOpen(false)} disabled={running}>
          Close
        </button>
      </form>
      {!valid && <p className="form-error">The period must end after it starts.</p>}
      <Problems error={error} />
      {jobId !== null && (
        <p role="status">
          {job.data?.status === "succeeded"
            ? `Done: ${result?.cycles ?? 0} cycles re-scored up to ${
                result?.end ? formatDateTime(new Date(result.end)) : "the end"
              }.`
            : job.data?.status === "failed"
              ? `Failed: ${job.data.error ?? "unknown error"}`
              : `Re-scoring… ${Math.round(job.data?.progress ?? 0)} %`}
        </p>
      )}
    </section>
  );
}
