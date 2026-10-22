import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { type AuditQuery, auditCsvUrl, fetchAuditPage, fetchUsers } from "../../api/admin";
import { formatDateTime } from "../../app/format";
import { fromLocalInput } from "../models/builderModel";
import { Field } from "../registry/common";
import { changedFields } from "./adminModel";

/** UC-19, FR-AUD-01: who changed what and when, newest first, filtered by time, user and
 * entity, with the before and after of each change, and the same filter as CSV. */
export function AuditTab() {
  const users = useQuery({ queryKey: ["users"], queryFn: ({ signal }) => fetchUsers(signal) });
  const [draft, setDraft] = useState({ from: "", to: "", user: "", entity: "", entityId: "" });
  const [query, setQuery] = useState<AuditQuery>({});
  const pages = useInfiniteQuery({
    queryKey: ["audit", query],
    queryFn: ({ pageParam, signal }) => fetchAuditPage(query, pageParam, signal),
    initialPageParam: null as number | null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const names = new Map((users.data ?? []).map((u) => [u.id, u.username]));
  const rows = pages.data?.pages.flatMap((p) => p.items) ?? [];

  function apply() {
    const iso = (text: string) => (text ? fromLocalInput(text).toISOString() : undefined);
    setQuery({
      from: iso(draft.from),
      to: iso(draft.to),
      user_id: draft.user ? Number(draft.user) : undefined,
      entity: draft.entity.trim() || undefined,
      entity_id: draft.entityId.trim() || undefined,
    });
  }

  return (
    <section className="panel" aria-labelledby="audit-title">
      <div className="panel-head">
        <h2 id="audit-title" className="panel-title">
          Audit log
        </h2>
        <a className="button button-small" href={auditCsvUrl(query)} download="audit.csv">
          Export CSV
        </a>
      </div>
      <form
        className="audit-filters"
        onSubmit={(e) => {
          e.preventDefault();
          apply();
        }}
      >
        <Field label="From">
          <input
            className="control"
            type="datetime-local"
            value={draft.from}
            onChange={(e) => setDraft({ ...draft, from: e.target.value })}
          />
        </Field>
        <Field label="To">
          <input
            className="control"
            type="datetime-local"
            value={draft.to}
            onChange={(e) => setDraft({ ...draft, to: e.target.value })}
          />
        </Field>
        <Field label="User">
          <select
            className="control"
            value={draft.user}
            onChange={(e) => setDraft({ ...draft, user: e.target.value })}
          >
            <option value="">Anyone</option>
            {(users.data ?? []).map((u) => (
              <option key={u.id} value={u.id}>
                {u.username}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Entity">
          <input
            className="control"
            placeholder="model, asset, tag, user…"
            value={draft.entity}
            onChange={(e) => setDraft({ ...draft, entity: e.target.value })}
          />
        </Field>
        <Field label="Entity ID">
          <input
            className="control"
            value={draft.entityId}
            onChange={(e) => setDraft({ ...draft, entityId: e.target.value })}
          />
        </Field>
        <button type="submit" className="button">
          Filter
        </button>
      </form>
      {pages.isError ? (
        <p role="alert">The audit log could not be loaded: {pages.error.message}</p>
      ) : (
        <table className="tree-table">
          <caption className="visually-hidden">Audit entries, newest first</caption>
          <thead>
            <tr>
              <th scope="col">Time</th>
              <th scope="col">Who</th>
              <th scope="col">What</th>
              <th scope="col">Action</th>
              <th scope="col">Change</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => {
              const fields = changedFields(e);
              return (
                <tr key={e.id}>
                  <td>{formatDateTime(new Date(e.ts))}</td>
                  <td>
                    {e.user_id !== null ? (names.get(e.user_id) ?? `#${e.user_id}`) : e.actor_type}
                  </td>
                  <td>
                    {e.entity} <span className="mono">{e.entity_id}</span>
                  </td>
                  <td>{e.action}</td>
                  <td>
                    {fields.length > 0 ? (
                      <details>
                        <summary>
                          {fields.slice(0, 4).join(", ")}
                          {fields.length > 4 ? ` +${fields.length - 4}` : ""}
                        </summary>
                        <pre className="audit-json">
                          {JSON.stringify({ before: e.before, after: e.after }, null, 2)}
                        </pre>
                      </details>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {pages.isPending && <p className="muted">Loading…</p>}
      {!pages.isPending && rows.length === 0 && <p className="muted">Nothing matches.</p>}
      {pages.hasNextPage && (
        <div className="builder-buttons">
          <button
            type="button"
            className="button"
            disabled={pages.isFetchingNextPage}
            onClick={() => void pages.fetchNextPage()}
          >
            Older entries
          </button>
        </div>
      )}
    </section>
  );
}
