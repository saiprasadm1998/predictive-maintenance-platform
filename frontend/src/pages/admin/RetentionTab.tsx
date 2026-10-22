import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { type Retention, fetchRetention, saveRetention } from "../../api/admin";
import { formatDateTime } from "../../app/format";
import { useAnnounce } from "../../app/liveContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Skeleton } from "../fleet/FleetPage";
import { Field, Problems } from "../registry/common";

/** NFR-DATA-01, ARC §6.3: how long samples, scores and outputs are kept, and their hourly
 * aggregates. The worker applies it once a day; data older than the limit is deleted. */
export function RetentionTab() {
  const retention = useQuery({
    queryKey: ["retention"],
    queryFn: ({ signal }) => fetchRetention(signal),
  });
  if (retention.isPending) return <Skeleton rows={3} />;
  if (retention.isError)
    return <p role="alert">The retention setting could not be loaded: {retention.error.message}</p>;
  return (
    <RetentionForm
      key={`${retention.data.raw_months}/${retention.data.aggregate_months}`}
      current={retention.data}
    />
  );
}

function RetentionForm({ current }: { current: Retention }) {
  const client = useQueryClient();
  const announce = useAnnounce();
  const [raw, setRaw] = useState(String(current.raw_months));
  const [aggregate, setAggregate] = useState(String(current.aggregate_months));
  const [confirming, setConfirming] = useState(false);
  const r = Number(raw);
  const a = Number(aggregate);
  const problems = [
    ...(Number.isInteger(r) && r >= 1 && r <= 600 ? [] : ["Raw data: whole months from 1 to 600"]),
    ...(Number.isInteger(a) && a >= 1 && a <= 1200
      ? []
      : ["Aggregates: whole months from 1 to 1,200"]),
    ...(a >= r ? [] : ["Aggregates are kept at least as long as raw data"]),
  ];
  const shorter = r < current.raw_months || a < current.aggregate_months;

  return (
    <section className="panel" aria-labelledby="retention-title">
      <h2 id="retention-title" className="panel-title">
        Retention
      </h2>
      <form
        className="form-grid"
        onSubmit={(e) => {
          e.preventDefault();
          if (!problems.length) setConfirming(true);
        }}
      >
        <Field label="Raw data: samples, scores and sensor outputs (months)">
          <input
            className="control"
            type="number"
            min={1}
            step={1}
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
          />
        </Field>
        <Field label="Hourly aggregates (months)">
          <input
            className="control"
            type="number"
            min={1}
            step={1}
            value={aggregate}
            onChange={(e) => setAggregate(e.target.value)}
          />
        </Field>
        <p className="muted small builder-wide">
          Last applied:{" "}
          {current.last_run_at
            ? `${formatDateTime(new Date(current.last_run_at))}${current.last_result ? `, ${current.last_result}` : ""}`
            : "not yet"}
        </p>
        <div className="builder-wide">
          <Problems problems={problems} />
          <div className="builder-buttons">
            <button type="submit" className="button button-primary" disabled={!!problems.length}>
              Save
            </button>
          </div>
        </div>
      </form>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Change how long data is kept?"
        consequence={
          shorter
            ? `At the next daily run, raw data older than ${r} months and aggregates older than ${a} months are deleted for good.`
            : `Raw data is kept for ${r} months and aggregates for ${a} months from now on.`
        }
        confirmLabel="Save"
        danger={shorter}
        onConfirm={async () => {
          await saveRetention(r, a);
          announce("Retention saved");
          await client.invalidateQueries({ queryKey: ["retention"] });
        }}
      />
    </section>
  );
}
