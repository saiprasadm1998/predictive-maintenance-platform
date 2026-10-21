import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";

import {
  acknowledgeAlerts,
  fetchAllAlerts,
  fetchPriorityMatrix,
  shelveAlerts,
  unshelveAlerts,
} from "../../api/alerts";
import { fetchAllAssets } from "../../api/assets";
import type { Alert } from "../../api/types";
import { formatDi, formatHealth, formatIso } from "../../app/format";
import { useAnnounce } from "../../app/liveContext";
import { useMe } from "../../app/session";
import { timeRangeParams } from "../../app/timeRange";
import { AlertStateChip } from "../../components/AlertStateChip";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { StatusShape } from "../../components/StatusShape";
import { type AlertState, severityLook } from "../../components/status";
import { Skeleton } from "../fleet/FleetPage";
import { age } from "../fleet/fleetModel";
import { AlertDetailPanel } from "./AlertDetailPanel";
import {
  KINDS,
  PRIORITIES,
  SEVERITIES,
  STATES,
  type SavedFilter,
  allowed,
  filterQuery,
  liveView,
  loadSaved,
  menuLabel,
  modelText,
  persistenceText,
  readFilter,
  storeSaved,
  toApiFilter,
  writeFilter,
} from "./alertsModel";
import { FilterMenu } from "./FilterMenu";

const ROW_HEIGHT = 40;
const SHELVE_FOR = [
  [60, "1 hour"],
  [4 * 60, "4 hours"],
  [8 * 60, "8 hours"],
  [24 * 60, "24 hours"],
  [3 * 24 * 60, "3 days"],
  [7 * 24 * 60, "7 days (the most allowed)"],
] as const;
const STATE_LABELS = new Map<string, string>(STATES.map(([v, l]) => [v, l]));
const KIND_LABELS = new Map<string, string>(KINDS.map(([v, l]) => [v, l]));

/**
 * SCR-02 Alert list (PDS §4.2, UC-10, FR-ALM-02, -03): the prioritised work queue across
 * the hierarchy. Unacknowledged first, then priority, then age (the server's order); filters
 * and the open alert live in the URL; bulk acknowledge, shelve and unshelve; live updates
 * never re-sort under the user, a "new alerts" button does.
 */
export function AlertsPage() {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const carried = timeRangeParams(new URLSearchParams(location.search)).toString();
  const filter = useMemo(() => readFilter(params), [params]);
  const apiFilter = useMemo(() => toApiFilter(filter), [filter]);
  const client = useQueryClient();
  const announce = useAnnounce();
  const me = useMe();
  const username = me.data?.username ?? "";

  const list = useQuery({
    queryKey: ["alerts", "list", apiFilter],
    queryFn: ({ signal }) => fetchAllAlerts(apiFilter, signal),
  });
  const assets = useQuery({
    queryKey: ["assets", "all"],
    queryFn: ({ signal }) => fetchAllAssets(signal),
  });

  // What the user is looking at keeps its order until they ask for the new list.
  const [accepted, setAccepted] = useState<number[] | null>(null);
  const filterKey = filterQuery(filter);
  const [acceptedFor, setAcceptedFor] = useState(filterKey);
  if (acceptedFor !== filterKey) {
    setAcceptedFor(filterKey);
    setAccepted(null);
  }
  const fresh = list.data?.items;
  useEffect(() => {
    if (fresh && accepted === null) setAccepted(fresh.map((a) => a.id));
  }, [fresh, accepted]);
  const shown = liveView(fresh ?? [], accepted);

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const selection = shown.rows.filter((a) => selected.has(a.id));
  const can = allowed(selection);

  function update(next: Partial<typeof filter>) {
    setParams((current) => writeFilter(current, { ...filter, ...next }));
    setSelected(new Set());
  }

  function refreshAll() {
    void client.invalidateQueries({
      predicate: (q) => ["alerts", "assets", "fleet", "models"].includes(String(q.queryKey[0])),
    });
  }

  const act = useMutation({
    mutationFn: async (action: () => Promise<Alert[]>) => action(),
    onSuccess: (done) => {
      setSelected(new Set());
      announce(`${done.length} alert${done.length === 1 ? "" : "s"} updated`);
      refreshAll();
    },
  });
  const [dialog, setDialog] = useState<null | "ack" | "shelve" | "unshelve">(null);
  const [minutes, setMinutes] = useState<number>(8 * 60);

  // saved filters
  const [saved, setSaved] = useState<SavedFilter[]>([]);
  useEffect(() => {
    if (username) setSaved(loadSaved(username));
  }, [username]);
  const [naming, setNaming] = useState<string | null>(null);
  function saveCurrent(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = naming?.trim();
    if (!name) return;
    const next = [...saved.filter((f) => f.name !== name), { name, query: filterKey }];
    setSaved(next);
    storeSaved(username, next);
    setNaming(null);
    announce(`Filter "${name}" saved`);
  }
  function deleteSaved(name: string) {
    const next = saved.filter((f) => f.name !== name);
    setSaved(next);
    storeSaved(username, next);
  }

  const openId = Number(params.get("alert")) || null;
  function openDetail(id: number | null) {
    setParams((current) => {
      const p = new URLSearchParams(current);
      if (id) p.set("alert", String(id));
      else p.delete("alert");
      return p;
    });
  }

  const scroller = useRef<HTMLDivElement>(null);
  // The virtualiser returns new functions each render; this app does not use the React
  // Compiler, so the rule's memoisation concern does not apply.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtual = useVirtualizer({
    count: shown.rows.length,
    getScrollElement: () => scroller.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
    initialRect: { width: 1200, height: 600 },
  });
  const items = virtual.getVirtualItems();
  const padTop = items[0]?.start ?? 0;
  const padBottom = items.length ? virtual.getTotalSize() - (items.at(-1)?.end ?? 0) : 0;

  const allChecked = shown.rows.length > 0 && shown.rows.every((a) => selected.has(a.id));
  const scopeOptions = assets.data ?? [];

  return (
    <div className={`alerts${openId ? " alerts-with-panel" : ""}`}>
      <div className="alerts-main">
        <section className="panel filter-bar" aria-label="Filters and actions">
          <label className="field-inline">
            <span className="visually-hidden">Scope</span>
            <select
              className="control"
              aria-label="Scope"
              value={filter.scope ?? ""}
              onChange={(e) => update({ scope: e.target.value || null })}
            >
              <option value="">Scope: All</option>
              {scopeOptions.map((a) => (
                <option key={a.id} value={a.code}>
                  Scope: {a.name}
                </option>
              ))}
            </select>
          </label>
          <FilterMenu
            name="State"
            options={STATES}
            chosen={filter.states}
            label={menuLabel("State", filter.states, STATE_LABELS)}
            onChange={(states) => update({ states })}
          />
          <FilterMenu
            name="Priority"
            options={PRIORITIES.map((p) => [p, p] as const)}
            chosen={filter.priorities}
            label={menuLabel("Priority", filter.priorities)}
            onChange={(priorities) => update({ priorities })}
          />
          <FilterMenu
            name="Severity"
            options={SEVERITIES.map((s) => [s, s] as const)}
            chosen={filter.severities}
            label={menuLabel("Severity", filter.severities)}
            onChange={(severities) => update({ severities })}
          />
          <FilterMenu
            name="Rule"
            options={KINDS}
            chosen={filter.kind ? [filter.kind] : []}
            label={menuLabel("Rule", filter.kind ? [filter.kind] : [], KIND_LABELS)}
            onChange={(kinds) =>
              update({ kind: (kinds.at(-1) as "di" | "sensor" | undefined) ?? null })
            }
          />
          <label className="field-inline">
            <input
              type="checkbox"
              checked={filter.closed}
              onChange={(e) => update({ closed: e.target.checked })}
            />
            Include closed
          </label>
          <label className="field-inline">
            <span className="visually-hidden">Saved filters</span>
            <select
              className="control"
              aria-label="Saved filters"
              value=""
              onChange={(e) => {
                const chosen = saved.find((f) => f.name === e.target.value);
                if (chosen)
                  setParams((c) => writeFilter(c, readFilter(new URLSearchParams(chosen.query))));
              }}
            >
              <option value="">Saved filters…</option>
              {saved.map((f) => (
                <option key={f.name} value={f.name}>
                  {f.name}
                </option>
              ))}
            </select>
          </label>
          {naming === null ? (
            <button type="button" className="link-button" onClick={() => setNaming("")}>
              Save filter
            </button>
          ) : (
            <form className="field-inline" onSubmit={saveCurrent}>
              <input
                className="control"
                aria-label="Name for this filter"
                placeholder="Name"
                value={naming}
                onChange={(e) => setNaming(e.target.value)}
              />
              <button type="submit" className="link-button">
                Save
              </button>
              <button type="button" className="link-button" onClick={() => setNaming(null)}>
                Cancel
              </button>
            </form>
          )}
          {saved.length > 0 && (
            <button
              type="button"
              className="link-button"
              onClick={() => {
                const current = saved.find((f) => f.query === filterKey);
                if (current) deleteSaved(current.name);
              }}
              disabled={!saved.some((f) => f.query === filterKey)}
            >
              Forget this filter
            </button>
          )}
          <span className="filter-spacer" />
          <button
            type="button"
            className="button"
            disabled={!can.ack}
            onClick={() => setDialog("ack")}
          >
            Acknowledge
          </button>
          <button
            type="button"
            className="button"
            disabled={!can.shelve}
            onClick={() => setDialog("shelve")}
          >
            Shelve…
          </button>
          <button
            type="button"
            className="button"
            disabled={!can.unshelve}
            onClick={() => setDialog("unshelve")}
          >
            Unshelve
          </button>
        </section>

        <section className="panel alerts-table-panel" aria-labelledby="alerts-title">
          <div className="panel-head">
            <h2 id="alerts-title" className="panel-title">
              Alerts ({shown.rows.length}
              {list.data?.truncated ? "+" : ""}) · unacknowledged first, then priority, then age
            </h2>
            {shown.incoming > 0 && (
              <button
                type="button"
                className="button new-items"
                onClick={() => setAccepted(fresh?.map((a) => a.id) ?? null)}
              >
                {shown.incoming} new alert{shown.incoming === 1 ? "" : "s"} · show
              </button>
            )}
          </div>
          {list.isPending ? (
            <Skeleton rows={8} />
          ) : list.isError ? (
            <p role="alert">The alerts could not be loaded: {list.error.message}</p>
          ) : shown.rows.length === 0 ? (
            <p className="muted">No alerts match these filters.</p>
          ) : (
            <div ref={scroller} className="alerts-scroll">
              <table
                className="tree-table alerts-table"
                aria-label="Alerts"
                aria-rowcount={shown.rows.length + 1}
              >
                <thead>
                  <tr aria-rowindex={1}>
                    <th scope="col" className="check">
                      <input
                        type="checkbox"
                        aria-label="Select all alerts shown"
                        checked={allChecked}
                        onChange={(e) =>
                          setSelected(
                            e.target.checked ? new Set(shown.rows.map((a) => a.id)) : new Set(),
                          )
                        }
                      />
                    </th>
                    <th scope="col">Priority</th>
                    <th scope="col">State</th>
                    <th scope="col">Asset</th>
                    <th scope="col">Model</th>
                    <th scope="col">Severity</th>
                    <th scope="col" className="num">
                      DI %
                    </th>
                    <th scope="col" className="num">
                      Health
                    </th>
                    <th scope="col">Persistence</th>
                    <th scope="col">Age</th>
                    <th scope="col">Forecast urgency</th>
                    <th scope="col">Case</th>
                    <th scope="col">
                      <span className="visually-hidden">Details</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {padTop > 0 && (
                    <tr aria-hidden="true">
                      <td colSpan={13} style={{ height: padTop, padding: 0, border: 0 }} />
                    </tr>
                  )}
                  {items.map((item) => {
                    const a = shown.rows[item.index]!;
                    return (
                      <AlertRow
                        key={a.id}
                        alert={a}
                        index={item.index}
                        checked={selected.has(a.id)}
                        open={openId === a.id}
                        onCheck={(on) => {
                          const next = new Set(selected);
                          if (on) next.add(a.id);
                          else next.delete(a.id);
                          setSelected(next);
                        }}
                        onDetails={() => openDetail(a.id)}
                      />
                    );
                  })}
                  {padBottom > 0 && (
                    <tr aria-hidden="true">
                      <td colSpan={13} style={{ height: padBottom, padding: 0, border: 0 }} />
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
          <p className="muted small">
            Shape and text carry the state; colour only supports them. The asset opens its analysis
            on the alert&apos;s window. Forecast urgency and cases arrive in Release 2.
          </p>
        </section>

        <PriorityMatrix />
      </div>

      {openId && (
        <AlertDetailPanel
          id={openId}
          carried={carried}
          onClose={() => openDetail(null)}
          onChanged={refreshAll}
        />
      )}

      <ConfirmDialog
        open={dialog === "ack"}
        onOpenChange={(o) => setDialog(o ? "ack" : null)}
        title={`Acknowledge ${selection.length} alert${selection.length === 1 ? "" : "s"}`}
        consequence="Acknowledging records that you have seen them; they stay active until the condition clears."
        confirmLabel="Acknowledge"
        reasonLabel="Comment"
        reasonOptional
        onConfirm={async (comment) => {
          await act.mutateAsync(() =>
            acknowledgeAlerts(
              selection.map((a) => a.id),
              comment,
            ),
          );
        }}
      />
      <ConfirmDialog
        open={dialog === "shelve"}
        onOpenChange={(o) => setDialog(o ? "shelve" : null)}
        title={`Shelve ${selection.length} alert${selection.length === 1 ? "" : "s"}`}
        consequence="Shelved alerts stop showing as active and stop notifying until the shelf ends; then they return to whatever their condition is."
        confirmLabel="Shelve"
        reasonLabel="Reason"
        onConfirm={async (reason) => {
          await act.mutateAsync(() =>
            shelveAlerts(
              selection.map((a) => a.id),
              reason,
              minutes,
            ),
          );
        }}
      >
        <label className="field">
          <span>For</span>
          <select
            className="control"
            value={minutes}
            onChange={(e) => setMinutes(Number(e.target.value))}
          >
            {SHELVE_FOR.map(([m, text]) => (
              <option key={m} value={m}>
                {text}
              </option>
            ))}
          </select>
        </label>
      </ConfirmDialog>
      <ConfirmDialog
        open={dialog === "unshelve"}
        onOpenChange={(o) => setDialog(o ? "unshelve" : null)}
        title={`Unshelve ${selection.length} alert${selection.length === 1 ? "" : "s"}`}
        consequence="The shelf ends now; each alert returns to active or closes, depending on its condition."
        confirmLabel="Unshelve"
        onConfirm={async () => {
          await act.mutateAsync(() => unshelveAlerts(selection.map((a) => a.id)));
        }}
      />
    </div>
  );
}

function AlertRow({
  alert: a,
  index,
  checked,
  open,
  onCheck,
  onDetails,
}: {
  alert: Alert;
  index: number;
  checked: boolean;
  open: boolean;
  onCheck: (on: boolean) => void;
  onDetails: () => void;
}) {
  const look = severityLook(a.severity);
  const oos = a.state === "Out of service";
  const unack = a.state === "Active-Unacknowledged" || a.state === "RTN-Unacknowledged";
  const raised = new Date(a.raised_at);
  // No time range carried: the asset screen opens on the alert's own window.
  const assetLink = `/assets/${a.asset_id}?alert=${a.id}`;
  return (
    <tr
      aria-rowindex={index + 2}
      aria-selected={checked}
      className={`${unack ? "row-unack" : ""}${open ? " row-open" : ""}`}
      style={{ height: ROW_HEIGHT }}
    >
      <td className="check">
        <input
          type="checkbox"
          aria-label={`Select alert ${a.id} on ${a.asset_code}`}
          checked={checked}
          onChange={(e) => onCheck(e.target.checked)}
        />
      </td>
      <td>
        {oos ? (
          <span className="chip chip-m tone-unknown">
            <StatusShape shape="dashed-square" tone="unknown" />
            <span>—</span>
          </span>
        ) : (
          <span className={`chip chip-m tone-${look.tone}`}>
            <StatusShape shape={look.shape} tone={look.tone} />
            <span>{a.priority}</span>
          </span>
        )}
      </td>
      <td>
        <AlertStateChip
          state={a.state as AlertState}
          severity={a.severity}
          shelvedUntil={a.shelved_until ? new Date(a.shelved_until) : null}
        />
      </td>
      <td>
        <Link to={assetLink}>{a.asset_path}</Link>
      </td>
      <td className="muted">{modelText(a)}</td>
      <td>{oos ? "—" : a.severity}</td>
      <td className="num">{oos ? "—" : formatDi(a.di).replace(" %", "")}</td>
      <td className="num">{oos ? "—" : formatHealth(a.health)}</td>
      <td>{persistenceText(a)}</td>
      <td>
        <time dateTime={a.raised_at} title={formatIso(raised)}>
          {age(raised)}
        </time>
      </td>
      <td className="muted">—</td>
      <td className="muted">—</td>
      <td>
        <button
          type="button"
          className="link-button"
          aria-label={`Details of alert ${a.id}`}
          aria-pressed={open}
          onClick={onDetails}
        >
          Details
        </button>
      </td>
    </tr>
  );
}

function PriorityMatrix() {
  const matrix = useQuery({
    queryKey: ["alerts", "matrix"],
    queryFn: ({ signal }) => fetchPriorityMatrix(signal),
  });
  const cell = (c: string, s: string) =>
    matrix.data?.find((m) => m.criticality === c && m.severity === s)?.priority ?? "—";
  return (
    <details className="panel matrix">
      <summary className="panel-title">Priority matrix (criticality × severity, UCS §6.6)</summary>
      <table className="tree-table matrix-table">
        <thead>
          <tr>
            <th scope="col">Asset criticality</th>
            <th scope="col">Warning</th>
            <th scope="col">Alert</th>
          </tr>
        </thead>
        <tbody>
          {["A", "B", "C"].map((c) => (
            <tr key={c}>
              <th scope="row">{c}</th>
              <td>{cell(c, "Warning")}</td>
              <td>{cell(c, "Alert")}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">
        Administrators change it under Administration; open alerts are re-prioritised at once.
      </p>
    </details>
  );
}
