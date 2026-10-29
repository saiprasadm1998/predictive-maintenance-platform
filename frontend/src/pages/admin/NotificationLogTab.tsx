import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { type Delivery, fetchDeliveries, sendTestEmail } from "../../api/notifications";
import { formatDateTime, formatIso } from "../../app/format";
import { useAnnounce } from "../../app/liveContext";
import { Skeleton } from "../fleet/FleetPage";
import { Problems } from "../registry/common";

const STATUSES: Delivery["status"][] = ["pending", "sent", "failed", "held", "summarised"];

/** The delivery log (plan 8.5, administrators): every notification with its recipient,
 * state, attempts and last error, and a test e-mail through the relay. */
export function NotificationLogTab() {
  const [status, setStatus] = useState<Delivery["status"] | "">("");
  const log = useQuery({
    queryKey: ["notifications", "log", status],
    queryFn: ({ signal }) => fetchDeliveries(status || null, signal),
    refetchInterval: 30_000,
  });
  return (
    <>
      <TestEmail />
      <section className="panel" aria-labelledby="log-title">
        <div className="panel-head">
          <h2 id="log-title" className="panel-title">
            Notification log
          </h2>
          <label className="field-inline">
            <span>Status</span>
            <select
              className="control"
              value={status}
              onChange={(e) => setStatus(e.target.value as Delivery["status"] | "")}
            >
              <option value="">All</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        </div>
        {log.isPending ? (
          <Skeleton rows={4} />
        ) : log.isError ? (
          <p role="alert">The log could not be loaded: {log.error.message}</p>
        ) : log.data.length === 0 ? (
          <p className="muted">No notification yet.</p>
        ) : (
          <table className="tree-table">
            <caption className="visually-hidden">Notifications, newest first</caption>
            <thead>
              <tr>
                <th scope="col">Queued</th>
                <th scope="col">To</th>
                <th scope="col">Subject</th>
                <th scope="col">Status</th>
                <th scope="col" className="num">
                  Attempts
                </th>
                <th scope="col">Sent / next try</th>
                <th scope="col">Last error</th>
              </tr>
            </thead>
            <tbody>
              {log.data.map((d) => (
                <tr key={d.id}>
                  <td title={formatIso(new Date(d.created_at))}>
                    {formatDateTime(new Date(d.created_at))}
                  </td>
                  <td>{d.recipient}</td>
                  <td>{d.subject}</td>
                  <td className={d.status === "failed" ? "overdue" : undefined}>
                    {d.status}
                    {d.summary_id ? ` (in summary ${d.summary_id})` : ""}
                  </td>
                  <td className="num">{d.attempts}</td>
                  <td>
                    {d.sent_at
                      ? formatDateTime(new Date(d.sent_at))
                      : d.next_attempt_at
                        ? `next ${formatDateTime(new Date(d.next_attempt_at))}`
                        : "—"}
                  </td>
                  <td className="muted small">{d.last_error ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}

function TestEmail() {
  const announce = useAnnounce();
  const [to, setTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<string | null>(null);
  return (
    <section className="panel" aria-labelledby="test-title">
      <h2 id="test-title" className="panel-title">
        Test the e-mail relay
      </h2>
      <form
        className="field-row"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          setDone(null);
          try {
            await sendTestEmail(to.trim());
            setDone(`Sent to ${to.trim()}.`);
            announce("Test e-mail sent");
          } catch (caught) {
            setError(caught);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label className="field-inline">
          <span>To</span>
          <input
            className="control"
            type="email"
            value={to}
            required
            onChange={(e) => setTo(e.target.value)}
          />
        </label>
        <button type="submit" className="button" disabled={busy || !to.trim()}>
          Send test e-mail
        </button>
        {done && (
          <span role="status" className="muted">
            {done}
          </span>
        )}
      </form>
      <Problems error={error} />
    </section>
  );
}
