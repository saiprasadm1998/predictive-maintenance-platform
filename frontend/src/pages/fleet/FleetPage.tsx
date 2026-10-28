import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";

import { fetchAlerts } from "../../api/alerts";
import { fetchAssetTree } from "../../api/assets";
import { fetchFleetKpis } from "../../api/fleet";
import { fetchModels } from "../../api/models";
import type { Alert } from "../../api/types";
import { useBreadcrumbs } from "../../app/breadcrumbs";
import { formatDi, formatIso } from "../../app/format";
import { timeRangeParams } from "../../app/timeRange";
import { HealthBar } from "../../components/HealthBar";
import { StatusChip } from "../../components/StatusChip";
import { StatusShape } from "../../components/StatusShape";
import { type Band, BANDS, bandLook, severityLook } from "../../components/status";
import {
  type Deviation,
  age,
  allBranches,
  assetLink,
  assetLabel,
  changedIds,
  defaultExpanded,
  describeAlert,
  filterByBand,
  highestDeviation,
  recentAlerts,
  unknownReason,
  visibleRows,
  sortTree,
  type TreeSort,
} from "./fleetModel";
import { useRowKeys } from "../../components/tableKeys";

const HIGHLIGHT_MS = 2500;

function isBand(value: string | null): value is Band {
  return value !== null && (BANDS as readonly string[]).includes(value);
}

/** Link targets keep the global time range (PDS §2.2). */
function useWithRange() {
  const location = useLocation();
  const carried = timeRangeParams(new URLSearchParams(location.search)).toString();
  return (path: string, extra?: Record<string, string>) => {
    const params = new URLSearchParams(carried);
    for (const [k, v] of Object.entries(extra ?? {})) params.set(k, v);
    const query = params.toString();
    return `${path}${query ? `?${query}` : ""}`;
  };
}

/**
 * SCR-01 Fleet overview (PDS §4.1, UC-08, FR-VIS-01, FR-HLT-01): where the plant needs
 * attention now. Figures across the top, the hierarchy with health, the highest deviations
 * and the latest alerts. Updates arrive live; nothing re-sorts under the cursor.
 */
export function FleetPage() {
  const rowKeys = useRowKeys();
  const [params, setParams] = useSearchParams();
  const band = isBand(params.get("band")) ? (params.get("band") as Band) : null;
  const withRange = useWithRange();

  const tree = useQuery({
    queryKey: ["assets", "tree"],
    queryFn: ({ signal }) => fetchAssetTree(signal),
  });
  const kpis = useQuery({
    queryKey: ["fleet", "kpis"],
    queryFn: ({ signal }) => fetchFleetKpis(signal),
  });
  const models = useQuery({
    queryKey: ["models", "list"],
    queryFn: ({ signal }) => fetchModels(signal),
  });
  const alerts = useQuery({
    queryKey: ["alerts", "open", 100],
    queryFn: ({ signal }) => fetchAlerts({ limit: 100 }, signal),
  });

  const roots = useMemo(() => tree.data ?? [], [tree.data]);
  useBreadcrumbs([
    {
      label: roots.length
        ? `Fleet overview · ${roots
            .flatMap((r) => (r.children.length ? r.children : [r]))
            .map((n) => n.name)
            .sort((a, b) => a.localeCompare(b))
            .join(", ")}`
        : "Fleet overview",
    },
  ]);

  // Live highlight: rows whose figures changed since the previous read.
  const previous = useRef(new Map<number, string>());
  const [flash, setFlash] = useState<Set<number>>(new Set());
  useEffect(() => {
    if (!tree.data) return;
    const { changed, next } = changedIds(previous.current, tree.data);
    previous.current = next;
    if (!changed.size) return;
    const show = window.setTimeout(() => setFlash(changed), 0);
    const hide = window.setTimeout(() => setFlash(new Set()), HIGHLIGHT_MS);
    return () => {
      window.clearTimeout(show);
      window.clearTimeout(hide);
    };
  }, [tree.data]);

  const sortParam = params.get("sort");
  const sort: TreeSort = sortParam === "band" || sortParam === "health" ? sortParam : "name";
  const shown = useMemo(
    () => sortTree(band ? filterByBand(roots, band) : roots, sort),
    [roots, band, sort],
  );
  function sortBy(next: TreeSort) {
    setParams((current) => {
      const p = new URLSearchParams(current);
      if (next === "name") p.delete("sort");
      else p.set("sort", next);
      return p;
    });
  }
  const sortHeader = (key: TreeSort, label: string) => (
    <th
      scope="col"
      aria-sort={sort === key ? (key === "name" ? "ascending" : "descending") : "none"}
    >
      <button type="button" className="link-button sort-button" onClick={() => sortBy(key)}>
        {label}
        <span aria-hidden="true">{sort === key ? " ▾" : ""}</span>
      </button>
    </th>
  );
  const [expanded, setExpanded] = useState<Set<number> | null>(null);
  const open = expanded ?? (band ? allBranches(shown) : defaultExpanded(roots));
  const rows = visibleRows(shown, open);

  function toggle(id: number) {
    const next = new Set(open);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setExpanded(next);
  }

  function setBand(next: Band | null) {
    setParams((current) => {
      const p = new URLSearchParams(current);
      if (next) p.set("band", next);
      else p.delete("band");
      return p;
    });
    setExpanded(null);
  }

  const counts = kpis.data?.assets_by_band ?? {};
  const stale = kpis.data?.stale_models ?? [];
  const modelNames = new Map((models.data ?? []).map((m) => [m.id, `${m.asset_code} / ${m.name}`]));
  const deviations = useMemo(
    () => highestDeviation(models.data ?? [], roots),
    [models.data, roots],
  );
  const recent = recentAlerts(alerts.data?.items ?? []);

  if (tree.isSuccess && roots.length === 0) {
    return (
      <section className="panel empty-state">
        <h2 className="panel-title">No assets yet</h2>
        <p>
          The plant hierarchy is empty. An administrator imports it under{" "}
          <Link to="/admin/registry">Administration › Registry and import</Link>.
        </p>
      </section>
    );
  }

  return (
    <div className="fleet">
      {stale.length > 0 && (
        <div className="banner banner-watch" role="status">
          <StatusShape shape="diamond" tone="watch" />
          <span>
            <b>No new scores</b> for {stale.length} model{stale.length === 1 ? "" : "s"} in the last
            three cycles:{" "}
            {stale
              .slice(0, 5)
              .map((id) => modelNames.get(id) ?? `model ${id}`)
              .join(", ")}
            {stale.length > 5 ? ` and ${stale.length - 5} more` : ""}. Their figures may be out of
            date; check the data feed.
          </span>
        </div>
      )}

      {kpis.isError && (
        <p role="alert" className="panel">
          The fleet figures could not be loaded: {kpis.error.message}
        </p>
      )}
      <ul className="kpis" aria-label="Fleet figures">
        <Kpi
          value={kpis.data?.models_by_status.Running}
          label="Models running"
          to={withRange("/models")}
        />
        {(["Alert", "Watch", "Unknown"] as const).map((b) => (
          <Kpi
            key={b}
            value={counts[b] ?? (kpis.data ? 0 : undefined)}
            label={b === "Unknown" ? "Unknown / insufficient data" : `Assets in ${b}`}
            band={b}
            pressed={band === b}
            onClick={() => setBand(band === b ? null : b)}
          />
        ))}
        <Kpi
          value={kpis.data?.sensors_by_status.Failure ?? (kpis.data ? 0 : undefined)}
          label="Sensor faults"
          fault
          to={withRange("/sensors", { status: "Failure" })}
        />
        <Kpi
          value={kpis.data?.open_cases ?? (kpis.data ? 0 : undefined)}
          label="Open cases"
          to={withRange("/cases", { open_only: "true" })}
        />
      </ul>

      <div className="fleet-body">
        <section className="panel fleet-tree" aria-labelledby="tree-title">
          <div className="panel-head">
            <h2 id="tree-title" className="panel-title">
              Asset hierarchy · health
            </h2>
            {band && (
              <span className="filter-note" role="status">
                Showing branches with assets in {band}.{" "}
                <button type="button" className="link-button" onClick={() => setBand(null)}>
                  Show all
                </button>
              </span>
            )}
          </div>
          {tree.isPending ? (
            <Skeleton rows={8} />
          ) : tree.isError ? (
            <p role="alert">The hierarchy could not be loaded: {tree.error.message}</p>
          ) : (
            <table ref={rowKeys} className="tree-table">
              <thead>
                <tr>
                  {sortHeader("name", "Asset")}
                  <th scope="col">Type</th>
                  {sortHeader("band", "Band")}
                  {sortHeader("health", "Health score")}
                  <th scope="col" className="num">
                    Active alerts
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ node, depth, hasChildren, expanded: isOpen }) => {
                  const reason = unknownReason(node);
                  return (
                    <tr key={node.id} className={flash.has(node.id) ? "row-flash" : undefined}>
                      <td>
                        <span className="tree-name" style={{ paddingLeft: depth * 16 }}>
                          {hasChildren ? (
                            <button
                              type="button"
                              className="tree-toggle"
                              aria-expanded={isOpen}
                              aria-label={`${isOpen ? "Collapse" : "Expand"} ${node.name}`}
                              onClick={() => toggle(node.id)}
                            >
                              <span aria-hidden="true">{isOpen ? "▾" : "▸"}</span>
                            </button>
                          ) : (
                            <span className="tree-toggle-space" />
                          )}
                          <Link to={withRange(assetLink(node))}>
                            {node.level === "equipment" ? assetLabel(node) : node.name}
                          </Link>
                        </span>
                      </td>
                      <td className="muted">{node.asset_type_name ?? ""}</td>
                      <td title={reason ?? undefined}>
                        {node.band ? (
                          <StatusChip kind="band" value={node.band} />
                        ) : (
                          <span className="muted">Not monitored</span>
                        )}
                        {reason ? <span className="visually-hidden"> ({reason})</span> : null}
                      </td>
                      <td>
                        {node.band === "Unknown" && node.health === null ? (
                          <span className="muted cell-clip" title={reason ?? undefined}>
                            — {reason ?? "insufficient data"}
                          </span>
                        ) : node.band ? (
                          <HealthBar health={node.health} label={`Health of ${node.name}`} />
                        ) : null}
                      </td>
                      <td className="num">{node.open_alerts || ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>

        <div className="fleet-side">
          <section className="panel" aria-labelledby="deviation-title">
            <h2 id="deviation-title" className="panel-title">
              Highest deviation now
            </h2>
            {models.isError ? (
              <p role="alert">The models could not be loaded: {models.error.message}</p>
            ) : (
              <DeviationList items={deviations} link={withRange} loading={models.isPending} />
            )}
          </section>
          <section className="panel" aria-labelledby="recent-title">
            <h2 id="recent-title" className="panel-title">
              Recent alerts
            </h2>
            {alerts.isError ? (
              <p role="alert">The alerts could not be loaded: {alerts.error.message}</p>
            ) : (
              <RecentAlerts items={recent} loading={alerts.isPending} link={withRange} />
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function Kpi({
  value,
  label,
  band,
  fault,
  to,
  onClick,
  pressed,
  note,
}: {
  value: number | null | undefined;
  label: string;
  band?: Band;
  fault?: boolean;
  to?: string;
  onClick?: () => void;
  pressed?: boolean;
  note?: string;
}) {
  const look = band ? bandLook(band) : null;
  const body = (
    <>
      <span className="kpi-value">
        {look && <StatusShape shape={look.shape} tone={look.tone} size={18} />}
        {fault && <StatusShape shape="square" tone="fault" size={18} />}
        <span className={look ? `tone-${look.tone}` : fault ? "tone-fault" : undefined}>
          {value === undefined ? "…" : value === null ? "—" : value}
        </span>
      </span>
      <span className="kpi-label">{label}</span>
      {note && <span className="kpi-note muted">{note}</span>}
    </>
  );
  return (
    <li className="kpi">
      {to ? (
        <Link className="kpi-inner" to={to}>
          {body}
        </Link>
      ) : onClick ? (
        <button type="button" className="kpi-inner" aria-pressed={pressed} onClick={onClick}>
          {body}
        </button>
      ) : (
        <div className="kpi-inner">{body}</div>
      )}
    </li>
  );
}

/** PDS §6: no re-sorting under the cursor; while it is over the list, the order holds. */
function DeviationList({
  items,
  link,
  loading,
}: {
  items: Deviation[];
  link: (path: string) => string;
  loading: boolean;
}) {
  const [frozen, setFrozen] = useState<number[] | null>(null);
  const holder = useRef<HTMLDivElement>(null);
  const order = useRef<number[]>([]);
  useEffect(() => {
    order.current = items.map((d) => d.modelId);
  }, [items]);
  useEffect(() => {
    const element = holder.current;
    if (!element) return;
    const hold = () => setFrozen((f) => f ?? order.current);
    const release = (event: Event) => {
      const next = (event as FocusEvent).relatedTarget;
      if (!(next instanceof Node && element.contains(next))) setFrozen(null);
    };
    element.addEventListener("mouseenter", hold);
    element.addEventListener("mouseleave", release);
    element.addEventListener("focusin", hold);
    element.addEventListener("focusout", release);
    return () => {
      element.removeEventListener("mouseenter", hold);
      element.removeEventListener("mouseleave", release);
      element.removeEventListener("focusin", hold);
      element.removeEventListener("focusout", release);
    };
  }, [loading, items.length]);
  const shown = frozen
    ? frozen
        .map((id) => items.find((d) => d.modelId === id))
        .filter((d): d is Deviation => d !== undefined)
    : items;
  if (loading) return <Skeleton rows={4} />;
  if (!items.length) return <p className="muted">No model is running yet.</p>;
  return (
    // Pointer or keyboard focus inside the list holds its order.
    <div ref={holder}>
      <ul className="side-list">
        {shown.map((d) => {
          const look = bandLook(d.band);
          return (
            <li key={d.modelId}>
              {d.assetId ? <Link to={link(`/assets/${d.assetId}`)}>{d.label}</Link> : d.label}
              <span className={`chip chip-m tone-${look.tone}`}>
                <StatusShape shape={look.shape} tone={look.tone} />
                <span>
                  <span className="visually-hidden">{look.label}, </span>DI {formatDi(d.di)}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function RecentAlerts({
  items,
  loading,
  link,
}: {
  items: Alert[];
  loading: boolean;
  link: (path: string, extra?: Record<string, string>) => string;
}) {
  if (loading) return <Skeleton rows={4} />;
  if (!items.length) return <p className="muted">No open alerts.</p>;
  const now = new Date();
  return (
    <ul className="side-list">
      {items.map((a) => {
        const look = severityLook(a.severity);
        const raised = new Date(a.raised_at);
        return (
          <li key={a.id}>
            <span className={`chip chip-m tone-${look.tone} recent-priority`}>
              <StatusShape shape={look.shape} tone={look.tone} />
              <span>
                <span className="visually-hidden">{look.label} </span>
                {a.priority ?? "—"}
              </span>
            </span>
            <Link className="recent-text" to={link("/alerts", { alert: String(a.id) })}>
              {describeAlert(a)}
            </Link>
            <time className="muted" dateTime={a.raised_at} title={formatIso(raised)}>
              {age(raised, now)}
            </time>
          </li>
        );
      })}
    </ul>
  );
}

export function Skeleton({ rows }: { rows: number }) {
  return (
    <div className="skeleton" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton-row" />
      ))}
    </div>
  );
}
