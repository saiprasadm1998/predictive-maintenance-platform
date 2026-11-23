import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { fetchAlert, fetchAllAlerts, fetchPriorityMatrix, unshelveAlerts } from "../../api/alerts";
import type { Alert, AlertDetail } from "../../api/types";
import { formatDateTime, formatDuration } from "../../app/format";
import { useScope } from "../../app/scope";
import { useMe } from "../../app/session";
import { alertState } from "../../app/words";
import {
  Badge,
  Empty,
  HowTo,
  Icon,
  ICONS,
  IdChip,
  Kpis,
  PageHeader,
  Pill,
} from "../../components/ui";
import { AckDialog, CaseDialog, ShelveDialog } from "./AlertDialogs";
import {
  PRIORITIES,
  SORTS,
  URGENCIES,
  allowed,
  filterQuery,
  loadSaved,
  modelText,
  persistenceText,
  readFilter,
  storeSaved,
  toApiFilter,
  writeFilter,
  type ListFilter,
} from "./alertsModel";

const STATE_OPTIONS = [
  ["", "All open"],
  ["Active-Unacknowledged", "Unacknowledged"],
  ["Active-Acknowledged", "Acknowledged"],
  ["RTN-Unacknowledged", "Returned"],
  ["Shelved", "Shelved"],
  ["Out of service", "Out of service"],
] as const;

type Quick = "all" | "unack" | "p1" | "shelved" | "case";

function age(from: string): string {
  return formatDuration(Date.now() - Date.parse(from));
}

function stateText(a: Alert): string {
  if (a.state === "Shelved" && a.shelved_until)
    return `Shelved, ${formatDuration(Date.parse(a.shelved_until) - Date.now())} left`;
  return alertState(a.state).label;
}

function urgencyText(a: Alert): string {
  if (!a.forecast_urgency) return "Not run";
  if (a.forecast_urgency === "None") return "No crossing";
  return a.forecast_upper_h !== null &&
    a.forecast_upper_h !== undefined &&
    a.forecast_lower_h !== null &&
    a.forecast_lower_h !== undefined
    ? `${a.forecast_urgency}, ${Math.round(a.forecast_lower_h)} to ${Math.round(a.forecast_upper_h)} h`
    : a.forecast_urgency;
}

/** A sensor alert that re-raised three or more times in a day is chattering (ISA-18.2). */
function chattering(a: Alert, all: readonly Alert[]): boolean {
  const day = Date.parse(a.raised_at) - 86_400_000;
  return (
    all.filter(
      (b) => b.model_id === a.model_id && b.tag_id === a.tag_id && Date.parse(b.raised_at) > day,
    ).length >= 3
  );
}

export function AlertsPage() {
  const scope = useScope();
  const me = useMe();
  const client = useQueryClient();
  const [params, setParams] = useSearchParams();
  const filter = readFilter(params);
  const quick =
    (params.get("q") as Quick | null) ?? (params.get("tab") === "shelved" ? "shelved" : "all");
  const detailId = params.get("alert") ? Number(params.get("alert")) : null;
  const grouped = params.get("group") !== "off";
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [dialog, setDialog] = useState<"ack" | "shelve" | "case" | null>(null);
  const [matrix, setMatrix] = useState(false);
  const [saved, setSaved] = useState(() => loadSaved(me.data?.username ?? ""));

  const list = useQuery({
    queryKey: ["alerts", "list", filterQuery(filter)],
    queryFn: async ({ signal }) => (await fetchAllAlerts(toApiFilter(filter), signal)).items,
  });
  const inScope = (list.data ?? []).filter((a) => scope.ids === null || scope.ids.has(a.asset_id));
  const needsAck = (a: Alert) =>
    a.state === "Active-Unacknowledged" || a.state === "RTN-Unacknowledged";
  const open = inScope.filter((a) => !a.closed_at);
  const quickRows = inScope.filter((a) => {
    switch (quick) {
      case "unack":
        return needsAck(a);
      case "p1":
        return a.priority === "P1";
      case "shelved":
        return a.state === "Shelved";
      case "case":
        return !!a.case_id;
      default:
        return true;
    }
  });

  // Group: the equipment's DI alert (or its most urgent alert) leads; the rest sit under it.
  const groups = (() => {
    const byAsset = new Map<number, Alert[]>();
    quickRows.forEach((a) => byAsset.set(a.asset_id, [...(byAsset.get(a.asset_id) ?? []), a]));
    const out: { lead: Alert; rest: Alert[] }[] = [];
    const seen = new Set<number>();
    quickRows.forEach((a) => {
      if (seen.has(a.asset_id)) return;
      seen.add(a.asset_id);
      const all = byAsset.get(a.asset_id)!;
      const lead = all.find((x) => x.kind === "di") ?? all[0]!;
      out.push({ lead, rest: all.filter((x) => x.id !== lead.id) });
    });
    return out;
  })();

  const chosen = inScope.filter((a) => selected.has(a.id));
  const can = allowed(chosen);
  const oneAsset = chosen.length > 0 && chosen.every((a) => a.asset_id === chosen[0]!.asset_id);
  const unshelve = useMutation({
    mutationFn: () => unshelveAlerts(chosen.map((a) => a.id)),
    onSuccess: () => {
      setSelected(new Set());
      void client.invalidateQueries({ queryKey: ["alerts"] });
    },
  });

  function setFilter(next: Partial<ListFilter>) {
    setParams(writeFilter(params, { ...filter, ...next }), { replace: true });
  }
  function setParam(key: string, value: string | null) {
    if (value === null) params.delete(key);
    else params.set(key, value);
    setParams(params, { replace: true });
  }
  function toggle(id: number) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  }

  const chip = (
    key: Quick,
    label: string,
    n: number,
    icon: string,
    tone?: "warning" | "danger" | "neutral" | "info",
  ) => ({
    label,
    value: n,
    icon,
    tone,
    pressed: quick === key,
    onClick: () => setParam("q", quick === key || key === "all" ? null : key),
  });

  const row = (a: Alert, child: boolean, rest: number) => {
    const st = alertState(a.state);
    const isOpen = expanded.has(a.id);
    return (
      <tr key={a.id} className={`${child ? "sub " : ""}${detailId === a.id ? "sel" : ""}`}>
        <td>
          <input
            type="checkbox"
            checked={selected.has(a.id)}
            onChange={() => toggle(a.id)}
            aria-label={`Select alert A-${a.id}`}
          />
        </td>
        <td>
          {!child && rest > 0 && (
            <button
              className="iconbtn"
              type="button"
              style={{ width: 32, height: 32 }}
              aria-expanded={isOpen}
              aria-label={`${isOpen ? "Hide" : "Show"} ${rest} related alerts`}
              onClick={() => {
                const next = new Set(expanded);
                if (isOpen) next.delete(a.id);
                else next.add(a.id);
                setExpanded(next);
              }}
            >
              <Icon d={isOpen ? "M6 9l6 6 6-6" : "M9 6l6 6-6 6"} size={16} />
            </button>
          )}
        </td>
        <td>
          <Pill>{a.priority ?? "—"}</Pill>
        </td>
        <td>
          <Pill tone={st.tone}>{stateText(a)}</Pill>
        </td>
        <td>
          <IdChip to={`/assets/${a.asset_id}?alert=${a.id}`}>{a.asset_code}</IdChip>
        </td>
        <td className="mono">
          {modelText(a)}
          {a.kind === "sensor" && chattering(a, inScope) && (
            <>
              {" "}
              <Badge tone="warning">Chattering</Badge>
            </>
          )}
        </td>
        <td>
          <Badge tone={a.severity === "Alert" ? "danger" : "warning"}>{a.severity}</Badge>
        </td>
        <td className="r num">{a.di === null ? "—" : a.di.toFixed(1)}</td>
        <td className="r num">{a.health === null ? "—" : Math.round(a.health)}</td>
        <td className="num">{persistenceText(a)}</td>
        <td className="r num">{age(a.raised_at)}</td>
        <td>
          <span className="sec">{urgencyText(a)}</span>
        </td>
        <td>
          {a.case_id ? (
            <Link className="idc" to={`/cases/${a.case_id}`}>
              {a.case_number}
            </Link>
          ) : null}
        </td>
        <td className="r">
          <button
            className="btn btn-g btn-sm"
            type="button"
            onClick={() => setParam("alert", String(a.id))}
          >
            Details
          </button>
        </td>
      </tr>
    );
  };

  return (
    <>
      <PageHeader
        title="Alerts"
        sub={`${quickRows.length} alerts. Unacknowledged first, then priority, then age.`}
        actions={
          <>
            <HowTo title="How to read this view">
              Shape and text carry the state; colour only supports them. Related sensor alerts sit
              under the equipment&apos;s main alert. The equipment opens its analysis on the
              alert&apos;s time window. Opening an alert does not acknowledge it.
            </HowTo>
            <button
              className="btn btn-s"
              type="button"
              disabled={!can.ack}
              onClick={() => setDialog("ack")}
            >
              Acknowledge
            </button>
            <button
              className="btn btn-s"
              type="button"
              disabled={!can.shelve}
              onClick={() => setDialog("shelve")}
            >
              Shelve
            </button>
            <button
              className="btn btn-s"
              type="button"
              disabled={!can.unshelve || unshelve.isPending}
              onClick={() => unshelve.mutate()}
            >
              Unshelve
            </button>
            <button
              className="btn btn-p"
              type="button"
              disabled={!oneAsset}
              title={
                chosen.length && !oneAsset ? "A case covers alerts of one equipment" : undefined
              }
              onClick={() => setDialog("case")}
            >
              Create case
            </button>
          </>
        }
      />
      <Kpis
        label="Alert filters"
        items={[
          chip("all", "Open alerts", open.length, ICONS.alert),
          chip("unack", "Unacknowledged", open.filter(needsAck).length, ICONS.bell, "warning"),
          chip(
            "p1",
            "Priority 1",
            open.filter((a) => a.priority === "P1").length,
            "M5 21V4h12l-2 4 2 4H5",
            "danger",
          ),
          chip(
            "shelved",
            "Shelved",
            open.filter((a) => a.state === "Shelved").length,
            ICONS.shelve,
            "neutral",
          ),
          chip(
            "case",
            "Linked to a case",
            open.filter((a) => !!a.case_id).length,
            ICONS.folder,
            "info",
          ),
        ]}
      />
      <div className={`alw${detailId ? " det" : ""}`}>
        <section className="pnl" aria-label="Alert queue">
          <div className="filters" style={{ marginBottom: 8 }}>
            <Select
              id="f2"
              label="State"
              width={160}
              value={filter.states[0] ?? ""}
              options={STATE_OPTIONS}
              onChange={(v) => setFilter({ states: v ? [v] : [] })}
            />
            <Select
              id="f3"
              label="Priority"
              width={110}
              value={filter.priorities[0] ?? ""}
              options={[["", "All"], ...PRIORITIES.map((p) => [p, p] as const)]}
              onChange={(v) => setFilter({ priorities: v ? [v] : [] })}
            />
            <Select
              id="f4"
              label="Severity"
              width={120}
              value={filter.severities[0] ?? ""}
              options={[
                ["", "All"],
                ["Alert", "Alert"],
                ["Warning", "Warning"],
              ]}
              onChange={(v) => setFilter({ severities: v ? [v] : [] })}
            />
            <Select
              id="f5"
              label="Rule"
              width={150}
              value={filter.kind ?? ""}
              options={[
                ["", "All rules"],
                ["di", "Deviation"],
                ["sensor", "Sensor |z|"],
              ]}
              onChange={(v) => setFilter({ kind: (v || null) as ListFilter["kind"] })}
            />
            <Select
              id="f6"
              label="Urgency"
              width={130}
              value={filter.urgencies[0] ?? ""}
              options={[["", "All"], ...URGENCIES.map((u) => [u, u] as const)]}
              onChange={(v) => setFilter({ urgencies: v ? [v] : [] })}
            />
            <Select
              id="f7"
              label="Case"
              width={130}
              value={filter.hasCase ?? ""}
              options={[
                ["", "All"],
                ["yes", "With case"],
                ["no", "No case"],
              ]}
              onChange={(v) => setFilter({ hasCase: (v || null) as ListFilter["hasCase"] })}
            />
          </div>
          <div className="filters" style={{ marginBottom: 12, justifyContent: "space-between" }}>
            <div className="filters" style={{ alignItems: "center" }}>
              <Select
                id="f8"
                label="Sort"
                width={200}
                value={filter.sort}
                options={SORTS}
                onChange={(v) => setFilter({ sort: v as ListFilter["sort"] })}
              />
              <Select
                id="f9"
                label="Saved filters"
                width={200}
                value=""
                options={[
                  ["", saved.length ? "Choose…" : "None"],
                  ...saved.map((s) => [s.query, s.name] as const),
                ]}
                onChange={(v) => v && setParams(new URLSearchParams(v), { replace: true })}
              />
              <label className="chk" style={{ marginTop: 18 }}>
                <input
                  type="checkbox"
                  checked={filter.closed}
                  onChange={(e) => setFilter({ closed: e.target.checked })}
                />
                Include closed
              </label>
              <label className="chk" style={{ marginTop: 18 }}>
                <input
                  type="checkbox"
                  checked={grouped}
                  onChange={(e) => setParam("group", e.target.checked ? null : "off")}
                />
                Group by equipment
              </label>
            </div>
            <button
              className="btn btn-g"
              type="button"
              style={{ marginTop: 18 }}
              onClick={() => {
                const name = window.prompt("Name this filter");
                if (!name || !me.data) return;
                const next = [
                  ...saved.filter((s) => s.name !== name),
                  { name, query: filterQuery(filter) },
                ];
                storeSaved(me.data.username, next);
                setSaved(next);
              }}
            >
              Save filter
            </button>
          </div>
          <div className="tw">
            <table className="tb">
              <thead>
                <tr>
                  <th style={{ width: 40 }}>
                    <span className="sr">Select</span>
                  </th>
                  <th style={{ width: 40 }}>
                    <span className="sr">Expand</span>
                  </th>
                  <th>Priority</th>
                  <th>State</th>
                  <th>Equipment</th>
                  <th>Model · rule</th>
                  <th>Severity</th>
                  <th className="r">DI %</th>
                  <th className="r">Health</th>
                  <th>Persistence</th>
                  <th className="r">Age</th>
                  <th>Urgency</th>
                  <th>Case</th>
                  <th>
                    <span className="sr">Details</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {grouped
                  ? groups.map((g) => (
                      <Fragment key={g.lead.id}>
                        {row(g.lead, false, g.rest.length)}
                        {expanded.has(g.lead.id) && g.rest.map((a) => row(a, true, 0))}
                      </Fragment>
                    ))
                  : quickRows.map((a) => row(a, false, 0))}
              </tbody>
            </table>
            {list.isPending && <p className="sec s13">Loading…</p>}
            {list.isSuccess && quickRows.length === 0 && (
              <Empty>No alerts match these filters.</Empty>
            )}
          </div>
          <button
            className="btn btn-g"
            type="button"
            aria-expanded={matrix}
            onClick={() => setMatrix(!matrix)}
            style={{ alignSelf: "flex-start", marginTop: 12 }}
          >
            {matrix ? "Hide priority matrix" : "Show priority matrix (criticality × severity)"}
          </button>
          {matrix && <PriorityMatrix />}
        </section>
        {detailId && (
          <AlertInspector
            id={detailId}
            onClose={() => setParam("alert", null)}
            onAck={(a) => {
              setSelected(new Set([a.id]));
              setDialog("ack");
            }}
            onShelve={(a) => {
              setSelected(new Set([a.id]));
              setDialog("shelve");
            }}
            onCase={(a) => {
              setSelected(new Set([a.id]));
              setDialog("case");
            }}
          />
        )}
      </div>
      {dialog === "ack" && (
        <AckDialog
          alerts={chosen}
          onClose={(done) => {
            setDialog(null);
            if (done) setSelected(new Set());
          }}
        />
      )}
      {dialog === "shelve" && (
        <ShelveDialog
          alerts={chosen}
          onClose={(done) => {
            setDialog(null);
            if (done) setSelected(new Set());
          }}
        />
      )}
      {dialog === "case" && chosen[0] && (
        <CaseDialog
          alerts={chosen}
          assetId={chosen[0].asset_id}
          assetLabel={chosen[0].asset_code}
          onClose={(done) => {
            setDialog(null);
            if (done) setSelected(new Set());
          }}
        />
      )}
    </>
  );
}

function Select({
  id,
  label,
  width,
  value,
  options,
  onChange,
}: {
  id: string;
  label: string;
  width: number;
  value: string;
  options: readonly (readonly [string, string])[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="fld">
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        className="sl"
        style={{ width }}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </div>
  );
}

function PriorityMatrix() {
  const cells = useQuery({
    queryKey: ["alerts", "matrix"],
    queryFn: ({ signal }) => fetchPriorityMatrix(signal),
  });
  const label: Record<string, string> = { A: "A, critical", B: "B, important", C: "C, other" };
  const p = (c: string, s: string) =>
    cells.data?.find((x) => x.criticality === c && x.severity === s)?.priority ?? "—";
  return (
    <div className="tw" style={{ maxWidth: 520 }}>
      <table className="tb">
        <thead>
          <tr>
            <th>Criticality</th>
            <th>Alert</th>
            <th>Warning</th>
          </tr>
        </thead>
        <tbody>
          {["A", "B", "C"].map((c) => (
            <tr key={c}>
              <td>{label[c]}</td>
              <td>
                <Pill>{p(c, "Alert")}</Pill>
              </td>
              <td>
                <Pill>{p(c, "Warning")}</Pill>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface Trace {
  cycle?: string;
  di?: number;
  health?: number;
  value?: number;
  rule?: { kind?: string; warning?: number; alert?: number };
  inputs?: Record<
    string,
    { dq?: string; value?: number | null; usable?: boolean; z?: number | null }
  >;
}

const HISTORY: Record<string, string> = {
  raise: "Raised",
  escalate: "Escalated",
  clear: "Condition cleared",
  acknowledge: "Acknowledged",
  shelve: "Shelved",
  unshelve_active: "Shelf ended, still active",
  unshelve_normal: "Shelf ended, closed",
  out_of_service: "Out of service",
  return_to_service: "Back in service",
  rule_removed: "Closed: rule removed or switched off",
};

function historyText(h: AlertDetail["history"][number]): string {
  const what = HISTORY[h.action] ?? h.action;
  const states = h.from_state
    ? `${alertState(h.from_state).label.toLowerCase()} to ${alertState(h.to_state).label.toLowerCase()}`
    : alertState(h.to_state).label.toLowerCase();
  const who = h.user ?? "System";
  return `${what}: ${states}. ${h.priority} ${h.severity.toLowerCase()}. ${who}${h.comment ? `: "${h.comment}"` : "."}`;
}

export function AlertInspector({
  id,
  onClose,
  onAck,
  onShelve,
  onCase,
}: {
  id: number;
  onClose: () => void;
  onAck: (a: Alert) => void;
  onShelve: (a: Alert) => void;
  onCase: (a: Alert) => void;
}) {
  const detail = useQuery({
    queryKey: ["alerts", "detail", id],
    queryFn: ({ signal }) => fetchAlert(id, signal),
  });
  const [inputs, setInputs] = useState(false);
  const a = detail.data;
  const trace = (a?.trace ?? {}) as Trace;
  const ins = Object.entries(trace.inputs ?? {});
  const can = a ? allowed([a]) : null;
  const st = a ? alertState(a.state) : null;
  return (
    <aside className="pnl" aria-labelledby="dt-h">
      <div className="pnlh">
        <div className="t">
          <span className="pt" id="dt-h">
            Alert A-{id}
          </span>
          {st && <Pill tone={st.tone}>{st.label}</Pill>}
        </div>
        <button className="iconbtn" type="button" onClick={onClose} aria-label="Close details">
          <Icon d={ICONS.close} />
        </button>
      </div>
      {!a ? (
        <p className="sec s13">{detail.isError ? detail.error.message : "Loading…"}</p>
      ) : (
        <>
          <dl className="kvs">
            <dt>Equipment</dt>
            <dd>
              <Link to={`/assets/${a.asset_id}?alert=${a.id}`}>{a.asset_path}</Link>
            </dd>
            <dt>Model and rule</dt>
            <dd className="mono">{modelText(a)}</dd>
            <dt>Priority</dt>
            <dd>
              {a.priority ?? "—"}, {a.severity}
            </dd>
            <dt>Raised</dt>
            <dd>{formatDateTime(new Date(a.raised_at))}</dd>
            {a.shelve_reason && (
              <>
                <dt>Shelved because</dt>
                <dd>{a.shelve_reason}</dd>
              </>
            )}
          </dl>
          <div className="acts" style={{ margin: "12px 0" }}>
            <button
              className="btn btn-s btn-sm"
              type="button"
              disabled={!can?.ack}
              onClick={() => onAck(a)}
            >
              Acknowledge
            </button>
            <button
              className="btn btn-s btn-sm"
              type="button"
              disabled={!can?.shelve}
              onClick={() => onShelve(a)}
            >
              Shelve
            </button>
            {a.case_id ? (
              <Link className="btn btn-s btn-sm" to={`/cases/${a.case_id}`}>
                Open {a.case_number}
              </Link>
            ) : (
              <button
                className="btn btn-p btn-sm"
                type="button"
                disabled={!!a.closed_at}
                onClick={() => onCase(a)}
              >
                Create case
              </button>
            )}
          </div>
          <span className="cap">Based on</span>
          <p className="s13" style={{ margin: "4px 0 8px" }}>
            Cycle {trace.cycle ? formatDateTime(new Date(trace.cycle)) : "—"}:{" "}
            {trace.rule?.kind === "di" ? "Deviation Index" : `|z| of ${a.tag ?? "the sensor"}`}{" "}
            {typeof trace.value === "number" ? trace.value.toFixed(1) : "—"} against warning{" "}
            {trace.rule?.warning ?? "—"} and alert {trace.rule?.alert ?? "—"}. Deviation{" "}
            {typeof trace.di === "number" ? `${trace.di.toFixed(1)} %` : "—"}, health{" "}
            {typeof trace.health === "number" ? Math.round(trace.health) : "—"}.
          </p>
          {ins.length > 0 && (
            <button
              className="btn btn-g btn-sm"
              type="button"
              aria-expanded={inputs}
              onClick={() => setInputs(!inputs)}
              style={{ alignSelf: "flex-start" }}
            >
              {inputs ? "Hide" : "Show"} inputs at that cycle ({ins.length})
            </button>
          )}
          {inputs && (
            <div style={{ margin: "4px 0 8px" }}>
              {ins.map(([tag, v]) => (
                <div key={tag} className="li" style={{ minHeight: 32, padding: "2px 0" }}>
                  <span className="mono grow">{tag}</span>
                  <span className="num s13">{v.value ?? "—"}</span>
                  <span className="meta" style={{ width: 90, textAlign: "right" }}>
                    {v.usable === false ? `not used${v.dq ? `, ${v.dq}` : ""}` : (v.dq ?? "")}
                  </span>
                </div>
              ))}
            </div>
          )}
          <span className="cap" style={{ marginTop: 8 }}>
            History
          </span>
          <ol className="hist" style={{ marginTop: 6 }}>
            {a.history.map((h, i) => (
              <li key={i}>
                <b>{formatDateTime(new Date(h.ts))}</b> {historyText(h)}
              </li>
            ))}
          </ol>
        </>
      )}
    </aside>
  );
}
