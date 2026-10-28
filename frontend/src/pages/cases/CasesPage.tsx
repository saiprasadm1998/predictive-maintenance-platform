import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";

import { type CaseFilter, type CaseStatus, fetchCases } from "../../api/cases";
import { useBreadcrumbs } from "../../app/breadcrumbs";
import { formatDateTime, formatIso } from "../../app/format";
import { useRowKeys } from "../../components/tableKeys";
import { Skeleton } from "../fleet/FleetPage";
import {
  OUTCOMES,
  STATUSES,
  dueText,
  outcomeLabel,
  statusClass,
  readCaseFilter,
  writeCaseFilter,
} from "./caseModel";

/**
 * SCR-09 Case list (PDS §4: "filterable list of cases by status, priority, assignee, due
 * date, outcome; overdue highlighting"). Open cases first, then priority, due date and
 * newest; the filter lives in the URL so a link reopens the same list.
 */
export function CasesPage() {
  useBreadcrumbs([{ label: "Cases" }]);
  const rowKeys = useRowKeys();
  const [params, setParams] = useSearchParams();
  const filter = readCaseFilter(params);
  const cases = useQuery({
    queryKey: ["cases", "list", params.toString()],
    queryFn: ({ signal }) => fetchCases(filter, signal),
    placeholderData: keepPreviousData,
  });

  function update(next: Partial<CaseFilter>) {
    setParams((current) => writeCaseFilter(current, { ...filter, ...next }), { replace: true });
  }

  const rows = cases.data ?? [];
  const overdue = rows.filter((c) => c.overdue).length;

  return (
    <div className="cases">
      <section className="panel filter-bar" aria-label="Filters">
        <label className="field-inline">
          <span>Status</span>
          <select
            className="control"
            value={filter.open_only ? "open" : (filter.status ?? "")}
            onChange={(e) =>
              e.target.value === "open"
                ? update({ open_only: true, status: null })
                : update({
                    open_only: false,
                    status: (e.target.value || null) as CaseStatus | null,
                  })
            }
          >
            <option value="">All</option>
            <option value="open">Open cases (not closed)</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="field-inline">
          <span>Priority</span>
          <select
            className="control"
            value={filter.priority ?? ""}
            onChange={(e) => update({ priority: e.target.value || null })}
          >
            <option value="">All</option>
            {["P1", "P2", "P3", "P4"].map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label className="field-inline">
          <span>Outcome</span>
          <select
            className="control"
            value={filter.outcome ?? ""}
            onChange={(e) => update({ outcome: (e.target.value || null) as CaseFilter["outcome"] })}
          >
            <option value="">All</option>
            {OUTCOMES.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field-inline">
          <input
            type="checkbox"
            checked={!!filter.mine}
            onChange={(e) => update({ mine: e.target.checked })}
          />
          Assigned to me
        </label>
        <label className="field-inline">
          <input
            type="checkbox"
            checked={!!filter.overdue}
            onChange={(e) => update({ overdue: e.target.checked })}
          />
          Overdue only
        </label>
        <label className="field-inline">
          <span className="visually-hidden">Search titles</span>
          <input
            className="control"
            type="search"
            placeholder="Search titles…"
            aria-label="Search titles"
            defaultValue={filter.q ?? ""}
            onKeyDown={(e) => {
              if (e.key === "Enter") update({ q: e.currentTarget.value.trim() || null });
            }}
          />
        </label>
      </section>

      <section className="panel" aria-labelledby="cases-title">
        <div className="panel-head">
          <h2 id="cases-title" className="panel-title">
            Cases{cases.data ? ` · ${rows.length}` : ""}
            {overdue ? ` · ${overdue} overdue` : ""}
          </h2>
          <span className="muted small">Create a case from the alert list or an asset.</span>
        </div>
        {cases.isPending ? (
          <Skeleton rows={6} />
        ) : cases.isError ? (
          <p role="alert">The cases could not be loaded: {cases.error.message}</p>
        ) : rows.length === 0 ? (
          <p className="muted">No case matches this filter.</p>
        ) : (
          <div className="case-table-wrap">
            <table ref={rowKeys} className="tree-table case-table">
              <caption className="visually-hidden">
                Cases: open first, then priority, due date and newest
              </caption>
              <thead>
                <tr>
                  <th scope="col">Case</th>
                  <th scope="col">Title</th>
                  <th scope="col">Asset</th>
                  <th scope="col">Status</th>
                  <th scope="col">Priority</th>
                  <th scope="col">Assignee</th>
                  <th scope="col">Due</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">Updated</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id} className={c.overdue ? "row-overdue" : undefined}>
                    <td>
                      <Link to={`/cases/${c.id}`}>{c.number}</Link>
                    </td>
                    <td>{c.title}</td>
                    <td>
                      <Link to={`/assets/${c.asset_id}`} title={c.asset_path}>
                        {c.asset_code}
                      </Link>
                    </td>
                    <td>
                      <span className={`case-status case-status-${statusClass(c.status)}`}>
                        {c.status}
                      </span>
                    </td>
                    <td>{c.priority}</td>
                    <td>{c.assignee ?? <span className="muted">Unassigned</span>}</td>
                    <td>{c.overdue ? <b className="overdue">{dueText(c)}</b> : dueText(c)}</td>
                    <td>
                      {outcomeLabel(c.outcome)}
                      {c.review_requested ? " · model review" : ""}
                    </td>
                    <td>
                      <time dateTime={c.updated_at} title={formatIso(new Date(c.updated_at))}>
                        {formatDateTime(new Date(c.updated_at))}
                      </time>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
