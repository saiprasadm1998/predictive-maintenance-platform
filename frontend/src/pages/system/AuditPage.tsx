import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";

import { type AuditQuery, auditCsvUrl, fetchAuditPage, fetchUsers } from "../../api/admin";
import { Badge, Loading, PageHeader, Panel } from "../../components/ui";
import { changedFields } from "../admin/adminModel";

const ENTITIES = [
  "asset",
  "tag",
  "model",
  "model_version",
  "alert",
  "case",
  "sensor_exclusion",
  "failure_mode",
  "history_import",
  "user",
  "api_key",
  "dq_rules",
  "retention",
];

const stamp = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
const words = (s: string) => s.replace(/[._]/g, " ");
const show = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));

export function AuditPage() {
  const users = useQuery({
    queryKey: ["users"],
    queryFn: ({ signal }) => fetchUsers(signal),
    retry: false,
  });
  const [draft, setDraft] = useState({ from: "", to: "", user: "", entity: "", entityId: "" });
  const [query, setQuery] = useState<AuditQuery>({});
  const [open, setOpen] = useState<number | null>(null);
  const pages = useInfiniteQuery({
    queryKey: ["audit", query],
    queryFn: ({ pageParam, signal }) => fetchAuditPage(query, pageParam, signal),
    initialPageParam: null as number | null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const apply = () =>
    setQuery({
      from: draft.from ? new Date(draft.from).toISOString() : undefined,
      to: draft.to ? new Date(`${draft.to}T23:59:59`).toISOString() : undefined,
      user_id: draft.user ? Number(draft.user) : undefined,
      entity: draft.entity || undefined,
      entity_id: draft.entityId.trim() || undefined,
    });
  const who = (id: number | null, actor: string) =>
    id === null
      ? actor === "system"
        ? "System"
        : actor
      : (users.data?.find((u) => u.id === id)?.display_name ?? `User ${id}`);
  const rows = pages.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <>
      <PageHeader
        title="Audit log"
        sub="Every change: who, what, when, before and after. Records cannot be edited."
        actions={
          <a className="btn btn-s" href={auditCsvUrl(query)}>
            Export CSV
          </a>
        }
      />
      <Panel className="fill">
        <div className="filters" style={{ marginBottom: 12 }}>
          <div className="fld">
            <label htmlFor="au-f">From</label>
            <input
              id="au-f"
              className="in"
              type="date"
              value={draft.from}
              onChange={(e) => setDraft({ ...draft, from: e.target.value })}
            />
          </div>
          <div className="fld">
            <label htmlFor="au-t">To</label>
            <input
              id="au-t"
              className="in"
              type="date"
              value={draft.to}
              onChange={(e) => setDraft({ ...draft, to: e.target.value })}
            />
          </div>
          <div className="fld" style={{ width: 180 }}>
            <label htmlFor="au-u">User</label>
            <select
              id="au-u"
              className="sl"
              value={draft.user}
              onChange={(e) => setDraft({ ...draft, user: e.target.value })}
            >
              <option value="">Anyone</option>
              {(users.data ?? []).map((u) => (
                <option key={u.id} value={u.id}>
                  {u.display_name}
                </option>
              ))}
            </select>
          </div>
          <div className="fld" style={{ width: 180 }}>
            <label htmlFor="au-e">Record type</label>
            <select
              id="au-e"
              className="sl"
              value={draft.entity}
              onChange={(e) => setDraft({ ...draft, entity: e.target.value })}
            >
              <option value="">Any</option>
              {ENTITIES.map((e) => (
                <option key={e} value={e}>
                  {words(e)}
                </option>
              ))}
            </select>
          </div>
          <div className="fld" style={{ width: 200 }}>
            <label htmlFor="au-i">Record ID</label>
            <input
              id="au-i"
              className="in"
              placeholder="For example 12"
              value={draft.entityId}
              onChange={(e) => setDraft({ ...draft, entityId: e.target.value })}
            />
          </div>
          <button className="btn btn-s" type="button" onClick={apply}>
            Filter
          </button>
        </div>
        {pages.isPending ? (
          <Loading what="the audit log" />
        ) : (
          <div className="tw">
            <table className="tb">
              <thead>
                <tr>
                  <th style={{ width: 32 }} />
                  <th>Time</th>
                  <th>Who</th>
                  <th>Record</th>
                  <th>Action</th>
                  <th>Fields changed</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => {
                  const on = open === e.id;
                  const fields = changedFields(e);
                  return (
                    <Fragment key={e.id}>
                      <tr
                        style={
                          on
                            ? {
                                background: "var(--traverse-surface-selected)",
                                boxShadow: "inset 3px 0 0 var(--traverse-action-primary)",
                              }
                            : undefined
                        }
                      >
                        <td>
                          <button
                            className="qi"
                            type="button"
                            style={{ width: 28, height: 28 }}
                            aria-expanded={on}
                            aria-label={on ? "Hide the change" : "Show the change"}
                            onClick={() => setOpen(on ? null : e.id)}
                          >
                            {on ? "⌄" : "›"}
                          </button>
                        </td>
                        <td>{stamp(e.ts)}</td>
                        <td>{who(e.user_id, e.actor_type)}</td>
                        <td className="mono">
                          {words(e.entity)} {e.entity_id}
                        </td>
                        <td>
                          <Badge>{words(e.action)}</Badge>
                        </td>
                        <td className="sec">{fields.map(words).join(", ") || "n/a"}</td>
                      </tr>
                      {on && (
                        <tr>
                          <td />
                          <td colSpan={5}>
                            <div className="half" style={{ padding: "8px 0" }}>
                              {(["before", "after"] as const).map((side) => (
                                <div key={side}>
                                  <span className="cap">{side}</span>
                                  <pre
                                    className="mono"
                                    style={{ margin: "4px 0 0", whiteSpace: "pre-wrap" }}
                                  >
                                    {(fields.length ? fields : Object.keys(e[side] ?? {}))
                                      .map((k) => `${k}: ${show(e[side]?.[k] ?? "")}`)
                                      .join("\n") || "nothing"}
                                  </pre>
                                </div>
                              ))}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
            {rows.length === 0 && (
              <p className="sec s13" style={{ padding: 12 }}>
                No changes match.
              </p>
            )}
            {pages.hasNextPage && (
              <button
                className="btn btn-s"
                type="button"
                style={{ marginTop: 12 }}
                disabled={pages.isFetchingNextPage}
                onClick={() => void pages.fetchNextPage()}
              >
                Show older changes
              </button>
            )}
          </div>
        )}
      </Panel>
    </>
  );
}
