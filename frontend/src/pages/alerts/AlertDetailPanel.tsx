import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { acknowledgeAlerts, fetchAlert, unshelveAlerts } from "../../api/alerts";
import type { AlertDetail } from "../../api/types";
import { formatDateTime, formatDi, formatHealth, formatIso } from "../../app/format";
import { AlertStateChip } from "../../components/AlertStateChip";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { StatusChip } from "../../components/StatusChip";
import type { AlertState, Ne107 } from "../../components/status";
import { Skeleton } from "../fleet/FleetPage";
import { allowed, modelText } from "./alertsModel";

interface Trace {
  cycle?: string;
  di?: number;
  health?: number;
  value?: number;
  rule?: { kind?: string; warning?: number; alert?: number };
  inputs?: Record<
    string,
    { dq?: string; value?: number | null; usable?: boolean; sample_ts?: string }
  >;
}

const ACTIONS: Record<string, string> = {
  raise: "Raised",
  escalate: "Escalated",
  clear: "Condition cleared",
  acknowledge: "Acknowledged",
  shelve: "Shelved",
  unshelve_active: "Shelf ended (still active)",
  unshelve_normal: "Shelf ended (closed)",
  out_of_service: "Out of service",
  return_to_service: "Back in service",
};

/**
 * One alert in full, beside the list (?alert=ID): what it was based on (NFR-ACC-01: the
 * cycle, the value against the limits, every input with its data quality) and its history,
 * who did what and why.
 */
export function AlertDetailPanel({
  id,
  carried,
  onClose,
  onChanged,
}: {
  id: number;
  carried: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const detail = useQuery({
    queryKey: ["alerts", "detail", id],
    queryFn: ({ signal }) => fetchAlert(id, signal),
  });
  const [acking, setAcking] = useState(false);
  const act = useMutation({
    mutationFn: (run: () => Promise<unknown>) => run(),
    onSuccess: onChanged,
  });
  const a = detail.data;
  return (
    <aside className="panel alert-panel" aria-labelledby="alert-panel-title">
      <div className="panel-head">
        <h2 id="alert-panel-title" className="panel-title">
          Alert {id}
        </h2>
        <button
          type="button"
          className="link-button"
          onClick={onClose}
          aria-label="Close the alert details"
        >
          Close
        </button>
      </div>
      {detail.isPending ? (
        <Skeleton rows={6} />
      ) : detail.isError ? (
        <p role="alert">{detail.error.message}</p>
      ) : a ? (
        <Body
          alert={a}
          carried={carried}
          onAck={() => setAcking(true)}
          onUnshelve={() => void act.mutateAsync(() => unshelveAlerts([a.id]))}
        />
      ) : null}
      {a && (
        <ConfirmDialog
          open={acking}
          onOpenChange={setAcking}
          title={`Acknowledge alert ${a.id}`}
          consequence="Acknowledging records that you have seen it; it stays active until the condition clears."
          confirmLabel="Acknowledge"
          reasonLabel="Comment"
          reasonOptional
          onConfirm={async (comment) => {
            await act.mutateAsync(() => acknowledgeAlerts([a.id], comment));
          }}
        />
      )}
    </aside>
  );
}

function Body({
  alert: a,
  carried,
  onAck,
  onUnshelve,
}: {
  alert: AlertDetail;
  carried: string;
  onAck: () => void;
  onUnshelve: () => void;
}) {
  const trace = a.trace as Trace;
  const can = allowed([a]);
  const inputs = Object.entries(trace.inputs ?? {});
  void carried;
  return (
    <div className="alert-panel-body">
      <AlertStateChip
        state={a.state as AlertState}
        severity={a.severity}
        shelvedUntil={a.shelved_until ? new Date(a.shelved_until) : null}
      />
      <table className="summary-table">
        <tbody>
          <tr>
            <th scope="row">Asset</th>
            <td>
              <Link to={`/assets/${a.asset_id}?alert=${a.id}`}>{a.asset_path}</Link>
            </td>
          </tr>
          <tr>
            <th scope="row">Model and rule</th>
            <td>{modelText(a)}</td>
          </tr>
          <tr>
            <th scope="row">Priority</th>
            <td>
              {a.priority ?? "—"} · {a.severity}
            </td>
          </tr>
          <tr>
            <th scope="row">Raised</th>
            <td title={formatIso(new Date(a.raised_at))}>
              {formatDateTime(new Date(a.raised_at))}
            </td>
          </tr>
          {a.shelve_reason && (
            <tr>
              <th scope="row">Shelved because</th>
              <td>{a.shelve_reason}</td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="field-inline">
        <button type="button" className="button" disabled={!can.ack} onClick={onAck}>
          Acknowledge
        </button>
        <button type="button" className="button" disabled={!can.unshelve} onClick={onUnshelve}>
          Unshelve
        </button>
      </div>

      <h3 className="panel-title">Based on</h3>
      <p>
        Cycle {trace.cycle ? formatDateTime(new Date(trace.cycle)) : "—"}:{" "}
        {trace.rule?.kind === "di" ? "Deviation Index" : `|z| of ${a.tag ?? "the sensor"}`}{" "}
        <b>{typeof trace.value === "number" ? trace.value.toFixed(1) : "—"}</b> against warning{" "}
        {trace.rule?.warning ?? "—"} and alert {trace.rule?.alert ?? "—"}. DI {formatDi(trace.di)},
        Health {formatHealth(trace.health)}.
      </p>
      {inputs.length > 0 && (
        <details>
          <summary>Inputs at that cycle ({inputs.length})</summary>
          <table className="tree-table">
            <thead>
              <tr>
                <th scope="col">Tag</th>
                <th scope="col" className="num">
                  Value
                </th>
                <th scope="col">Quality</th>
                <th scope="col">Used</th>
              </tr>
            </thead>
            <tbody>
              {inputs.map(([tag, input]) => (
                <tr key={tag}>
                  <td>{tag}</td>
                  <td className="num">{input.value ?? "—"}</td>
                  <td>
                    {input.dq ? (
                      <StatusChip kind="ne107" value={input.dq as Ne107} size="s" />
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{input.usable ? "yes" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      <h3 className="panel-title">History</h3>
      <ol className="history">
        {a.history.map((h, i) => (
          <li key={i}>
            <time dateTime={h.ts} title={formatIso(new Date(h.ts))}>
              {formatDateTime(new Date(h.ts))}
            </time>{" "}
            <b>{ACTIONS[h.action] ?? h.action}</b>
            {h.from_state ? ` · ${h.from_state} → ${h.to_state}` : ` · ${h.to_state}`} ·{" "}
            {h.priority} {h.severity}
            {" · "}
            {h.user ?? "system"}
            {h.comment ? <div className="muted">“{h.comment}”</div> : null}
          </li>
        ))}
      </ol>
    </div>
  );
}
