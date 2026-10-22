import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { fetchSensorHealth } from "../../api/admin";
import { fetchAllTags } from "../../api/registry";
import { useBreadcrumbs } from "../../app/breadcrumbs";
import { formatDateTime } from "../../app/format";
import { StatusChip } from "../../components/StatusChip";
import { NE107, type Ne107 } from "../../components/status";
import { EFFECT_LABELS, RULE_LABELS } from "../admin/adminModel";
import { Skeleton } from "../fleet/FleetPage";

const ORDER: Record<string, number> = Object.fromEntries(
  ["Failure", "Out of specification", "Function check", "Maintenance required", "Good"].map(
    (s, i) => [s, i],
  ),
);

/**
 * SCR-07 Sensor health (PDS §4.7, FR-DQ-02, wireframe 07): each sensor's NAMUR NE 107
 * status at the latest scoring cycle, the rule that set it and what scoring does with it.
 * Non-Good sensors are listed, worst first; a figure filters the list (`?status=`).
 * Overrides and manual exclusion arrive with sensor health in plan 8.1.
 */
export function SensorHealthPage() {
  useBreadcrumbs([{ label: "Sensor health" }]);
  const [params, setParams] = useSearchParams();
  const status = params.get("status");
  const health = useQuery({
    queryKey: ["sensors", "health"],
    queryFn: ({ signal }) => fetchSensorHealth(signal),
  });
  const tags = useQuery({
    queryKey: ["tags", "all"],
    queryFn: ({ signal }) => fetchAllTags(signal),
  });
  const byId = useMemo(() => new Map((tags.data ?? []).map((t) => [t.id, t])), [tags.data]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const s of health.data ?? []) c[s.status] = (c[s.status] ?? 0) + 1;
    return c;
  }, [health.data]);
  const rows = useMemo(
    () =>
      (health.data ?? [])
        .filter((s) => (status ? s.status === status : s.status !== "Good"))
        .sort(
          (a, b) =>
            (ORDER[a.status] ?? 9) - (ORDER[b.status] ?? 9) ||
            a.asset_code.localeCompare(b.asset_code) ||
            a.source_name.localeCompare(b.source_name),
        ),
    [health.data, status],
  );

  function filter(next: string | null) {
    setParams((current) => {
      const p = new URLSearchParams(current);
      if (next) p.set("status", next);
      else p.delete("status");
      return p;
    });
  }

  if (health.isPending) return <Skeleton rows={8} />;
  if (health.isError)
    return <p role="alert">Sensor health could not be loaded: {health.error.message}</p>;

  return (
    <div className="registry">
      <ul className="kpis" aria-label="Sensors by status">
        <li className="kpi">
          <button
            type="button"
            className="kpi-inner"
            aria-pressed={status === null}
            onClick={() => filter(null)}
          >
            <span className="kpi-value">{health.data.length.toLocaleString("en-GB")}</span>
            <span className="kpi-label">Sensors · show all non-Good</span>
          </button>
        </li>
        {NE107.filter((s) => s !== "Good").map((s) => (
          <li key={s} className="kpi">
            <button
              type="button"
              className="kpi-inner"
              aria-pressed={status === s}
              onClick={() => filter(status === s ? null : s)}
            >
              <span className="kpi-value">{(counts[s] ?? 0).toLocaleString("en-GB")}</span>
              <span className="kpi-label">
                <StatusChip kind="ne107" value={s} size="s" bold={false} />
              </span>
            </button>
          </li>
        ))}
      </ul>
      <section className="panel" aria-labelledby="sensors-title">
        <h2 id="sensors-title" className="panel-title">
          {status ? `Sensors in ${status}` : "Sensors with non-Good status"} ({rows.length})
        </h2>
        {rows.length === 0 ? (
          <p className="muted">
            {status ? `No sensor is in ${status}.` : "Every sensor is Good at the latest cycle."}
          </p>
        ) : (
          <table className="tree-table">
            <caption className="visually-hidden">NAMUR NE 107 status per sensor</caption>
            <thead>
              <tr>
                <th scope="col">Status</th>
                <th scope="col">Tag</th>
                <th scope="col">Asset</th>
                <th scope="col">Description</th>
                <th scope="col">Rule</th>
                <th scope="col">Scoring use</th>
                <th scope="col">Since</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => {
                const tag = byId.get(s.tag_id);
                return (
                  <tr key={s.tag_id}>
                    <td>
                      <StatusChip
                        kind="ne107"
                        value={(NE107.includes(s.status as Ne107) ? s.status : "Failure") as Ne107}
                        size="s"
                      />
                    </td>
                    <td className="mono">{s.source_name}</td>
                    <td>
                      {tag ? (
                        <Link to={`/assets/${tag.asset_id}`}>{s.asset_code}</Link>
                      ) : (
                        s.asset_code
                      )}
                    </td>
                    <td>{tag?.description ?? ""}</td>
                    <td>{RULE_LABELS[s.rule] ?? s.rule}</td>
                    <td>{EFFECT_LABELS[s.effect] ?? s.effect}</td>
                    <td>{formatDateTime(new Date(s.since))}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <p className="muted small">
          Overriding a status and excluding a sensor by hand arrive with sensor health in Release 2.
        </p>
      </section>
    </div>
  );
}
