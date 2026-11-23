import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { fetchCases } from "../../api/cases";
import { formatDateTime } from "../../app/format";
import { useScope } from "../../app/scope";
import { caseStatusTone, OUTCOME_LABEL } from "../../app/words";
import { Empty, HowTo, ICONS, Kpis, PageHeader, Panel, Pill } from "../../components/ui";

const STATUSES = ["Open", "Investigating", "Action required", "Monitoring", "Closed", "Cancelled"];

export function CasesPage() {
  const [now] = useState(() => Date.now());
  const scope = useScope();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [outcome, setOutcome] = useState("");
  const [overdue, setOverdue] = useState(false);
  const [mine, setMine] = useState(false);
  const all = useQuery({
    queryKey: ["cases", "all"],
    queryFn: ({ signal }) => fetchCases({}, signal),
  });
  const filtered = useQuery({
    queryKey: ["cases", "list", mine],
    queryFn: ({ signal }) => fetchCases({ mine }, signal),
    enabled: mine,
  });
  const base = (mine ? filtered.data : all.data) ?? [];
  const inScope = (c: { asset_id: number }) => scope.ids === null || scope.ids.has(c.asset_id);
  const cases = (all.data ?? []).filter(inScope);
  const isOpen = (s: string) => s !== "Closed" && s !== "Cancelled";
  const monthAgo = now - 30 * 86_400_000;
  const closed30 = cases.filter((c) => c.closed_at && Date.parse(c.closed_at) > monthAgo);
  const needle = q.trim().toLowerCase();
  const rows = base.filter(
    (c) =>
      inScope(c) &&
      (!status || c.status === status) &&
      (!priority || c.priority === priority) &&
      (!outcome || c.outcome === outcome) &&
      (!overdue || c.overdue) &&
      (!needle || `${c.number} ${c.title} ${c.asset_code}`.toLowerCase().includes(needle)),
  );

  return (
    <>
      <PageHeader
        title="Cases"
        sub="From alert to recorded outcome"
        actions={
          <>
            <HowTo title="How cases work">
              A case starts from one or more alerts of one equipment and freezes the evidence at
              that moment. Assigning it starts the investigation. Actions track the work. A case
              closes only with an outcome; a true finding also needs the confirmed failure mode.
            </HowTo>
            <Link className="btn btn-p" to="/alerts?case=no">
              Create from an alert
            </Link>
          </>
        }
      />
      <Kpis
        cols={4}
        label="Case totals"
        items={[
          {
            label: "Open cases",
            value: cases.filter((c) => isOpen(c.status)).length,
            icon: ICONS.folder,
            tone: "info",
            sub: "Investigating or acting",
            onClick: () => setStatus(""),
            pressed: false,
          },
          {
            label: "Action required",
            value: cases.filter((c) => c.status === "Action required").length,
            icon: ICONS.alert,
            tone: "warning",
            sub: "Work to schedule",
            onClick: () => setStatus("Action required"),
            pressed: status === "Action required",
          },
          {
            label: "Overdue",
            value: cases.filter((c) => c.overdue).length,
            icon: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
            tone: "neutral",
            sub: "Past due date",
            onClick: () => setOverdue(!overdue),
            pressed: overdue,
          },
          {
            label: "Closed, last 30 days",
            value: closed30.length,
            icon: ICONS.check,
            tone: "success",
            sub: `${closed30.filter((c) => c.outcome === "true_finding").length} true findings`,
            onClick: () => setStatus("Closed"),
            pressed: status === "Closed",
          },
        ]}
      />
      <Panel className="fill">
        <div className="filters" style={{ marginBottom: 12, alignItems: "center" }}>
          <div className="fld">
            <label htmlFor="cs-f">Find</label>
            <input
              id="cs-f"
              className="in"
              type="search"
              placeholder="Case, title or equipment"
              style={{ width: 240 }}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <div className="fld">
            <label htmlFor="cs-s">Status</label>
            <select
              id="cs-s"
              className="sl"
              style={{ width: 170 }}
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="">All statuses</option>
              {STATUSES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="fld">
            <label htmlFor="cs-p">Priority</label>
            <select
              id="cs-p"
              className="sl"
              style={{ width: 130 }}
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
            >
              <option value="">All</option>
              {["P1", "P2", "P3", "P4"].map((p) => (
                <option key={p}>{p}</option>
              ))}
            </select>
          </div>
          <div className="fld">
            <label htmlFor="cs-o">Outcome</label>
            <select
              id="cs-o"
              className="sl"
              style={{ width: 180 }}
              value={outcome}
              onChange={(e) => setOutcome(e.target.value)}
            >
              <option value="">All outcomes</option>
              {Object.entries(OUTCOME_LABEL).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </div>
          <label className="chk" style={{ marginTop: 18 }}>
            <input
              type="checkbox"
              checked={overdue}
              onChange={(e) => setOverdue(e.target.checked)}
            />
            Overdue only
          </label>
          <label className="chk" style={{ marginTop: 18 }}>
            <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />
            Assigned to me
          </label>
        </div>
        <div className="tw">
          <table className="tb">
            <thead>
              <tr>
                <th>Case</th>
                <th>Title</th>
                <th>Equipment</th>
                <th>Priority</th>
                <th>Status</th>
                <th>Assignee</th>
                <th>Due</th>
                <th>Outcome</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <td>
                    <Link className="idc" to={`/cases/${c.id}`}>
                      {c.number} →
                    </Link>
                  </td>
                  <td className="w">{c.title}</td>
                  <td className="mono">{c.asset_code}</td>
                  <td>
                    <Pill>{c.priority}</Pill>
                  </td>
                  <td>
                    <Pill tone={caseStatusTone(c.status, c.outcome)}>{c.status}</Pill>
                  </td>
                  <td>{c.assignee ?? <span className="sec">Unassigned</span>}</td>
                  <td
                    className={c.overdue ? "" : "num"}
                    style={
                      c.overdue
                        ? { color: "var(--traverse-status-danger-fg)", fontWeight: 600 }
                        : undefined
                    }
                  >
                    {c.due ? formatDateTime(new Date(`${c.due}T12:00:00`)).slice(0, 6) : "—"}
                    {c.overdue ? ", overdue" : ""}
                  </td>
                  <td>{c.outcome ? OUTCOME_LABEL[c.outcome] : "n/a"}</td>
                  <td className="num sec">{formatDateTime(new Date(c.updated_at))}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {all.isSuccess && rows.length === 0 && <Empty>No cases match these filters.</Empty>}
        </div>
      </Panel>
    </>
  );
}
