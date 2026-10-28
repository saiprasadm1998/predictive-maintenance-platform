import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { type SensorHealth, fetchSensorHealth } from "../../api/admin";
import { fetchAllAssets } from "../../api/assets";
import { fetchAllTags } from "../../api/registry";
import { useBreadcrumbs } from "../../app/breadcrumbs";
import { formatDateTime, formatIso } from "../../app/format";
import { useMe } from "../../app/session";
import { StatusChip } from "../../components/StatusChip";
import { useRowKeys } from "../../components/tableKeys";
import { NE107, type Ne107 } from "../../components/status";
import { Skeleton } from "../fleet/FleetPage";
import { type ExclusionAction, ExclusionDialog } from "./ExclusionDialog";
import { canExclude, canOverride, figures, listed, ruleOrReason, scoringUse } from "./sensorsModel";

/**
 * SCR-07 Sensor health (PDS §4.7, FR-DQ-02 to -05, UC-14, wireframe 07): each sensor's
 * NAMUR NE 107 status, the rule or the engineer's reason that set it, the models it affects
 * and what scoring does with it. Figures filter by category (`?status=`), a site filter
 * narrows the plant (`?site=`); analysts and model engineers exclude, override and end.
 */
export function SensorHealthPage() {
  useBreadcrumbs([{ label: "Sensor health" }]);
  const rowKeys = useRowKeys();
  const me = useMe();
  const [params, setParams] = useSearchParams();
  const status = params.get("status");
  const site = params.get("site");
  const health = useQuery({
    queryKey: ["sensors", "health", site],
    queryFn: ({ signal }) => fetchSensorHealth(signal, site),
  });
  const tags = useQuery({
    queryKey: ["tags", "all"],
    queryFn: ({ signal }) => fetchAllTags(signal),
  });
  const assets = useQuery({
    queryKey: ["assets", "all"],
    queryFn: ({ signal }) => fetchAllAssets(signal),
  });
  const [action, setAction] = useState<ExclusionAction | null>(null);
  const byId = useMemo(() => new Map((tags.data ?? []).map((t) => [t.id, t])), [tags.data]);
  const sites = (assets.data ?? []).filter((a) => a.level === "site");
  const sensors = useMemo(() => health.data ?? [], [health.data]);
  const counts = useMemo(() => figures(sensors), [sensors]);
  const rows = useMemo(() => listed(sensors, status), [sensors, status]);
  const may = canExclude(me.data);

  function set(key: string, value: string | null) {
    setParams((current) => {
      const p = new URLSearchParams(current);
      if (value) p.set(key, value);
      else p.delete(key);
      return p;
    });
  }

  return (
    <div className="registry">
      <div className="filter-bar">
        <label className="field-inline">
          <span>Site</span>
          <select
            className="control"
            value={site ?? ""}
            onChange={(e) => set("site", e.target.value || null)}
          >
            <option value="">All sites</option>
            {sites.map((s) => (
              <option key={s.id} value={s.code}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {health.isPending ? (
        <Skeleton rows={8} />
      ) : health.isError ? (
        <p role="alert">Sensor health could not be loaded: {health.error.message}</p>
      ) : (
        <>
          <ul className="kpis" aria-label="Sensors by status">
            <li className="kpi">
              <button
                type="button"
                className="kpi-inner"
                aria-pressed={status === null}
                onClick={() => set("status", null)}
              >
                <span className="kpi-value">{counts.inModels.toLocaleString("en-GB")}</span>
                <span className="kpi-label">Sensors in models · show all non-Good</span>
              </button>
            </li>
            {NE107.filter((s) => s !== "Good").map((s) => (
              <li key={s} className="kpi">
                <button
                  type="button"
                  className="kpi-inner"
                  aria-pressed={status === s}
                  onClick={() => set("status", status === s ? null : s)}
                >
                  <span className="kpi-value">
                    {(counts.byStatus[s] ?? 0).toLocaleString("en-GB")}
                  </span>
                  <span className="kpi-label">
                    <StatusChip kind="ne107" value={s} size="s" bold={false} />
                  </span>
                </button>
              </li>
            ))}
            <li className="kpi">
              <div className="kpi-inner">
                <span className="kpi-value">{counts.impacted}</span>
                <span className="kpi-label">Models impacted</span>
              </div>
            </li>
          </ul>
          <section className="panel" aria-labelledby="sensors-title">
            <h2 id="sensors-title" className="panel-title">
              {status ? `Sensors in ${status}` : "Sensors with non-Good status"} ({rows.length})
            </h2>
            {rows.length === 0 ? (
              <p className="muted">
                {status
                  ? `No sensor is in ${status}.`
                  : "Every sensor is Good at the latest cycle."}
              </p>
            ) : (
              <table ref={rowKeys} className="tree-table">
                <caption className="visually-hidden">NAMUR NE 107 status per sensor</caption>
                <thead>
                  <tr>
                    <th scope="col">Status</th>
                    <th scope="col">Tag</th>
                    <th scope="col">Asset</th>
                    <th scope="col">Description</th>
                    <th scope="col">Rule / reason</th>
                    <th scope="col">Models</th>
                    <th scope="col">Scoring use</th>
                    <th scope="col">Since</th>
                    {may && <th scope="col">Action</th>}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((s) => (
                    <SensorRow
                      key={s.tag_id}
                      sensor={s}
                      assetId={byId.get(s.tag_id)?.asset_id}
                      description={byId.get(s.tag_id)?.description ?? ""}
                      may={may}
                      onAction={setAction}
                    />
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
      <ExclusionDialog action={action} onDone={() => setAction(null)} />
    </div>
  );
}

function SensorRow({
  sensor: s,
  assetId,
  description,
  may,
  onAction,
}: {
  sensor: SensorHealth;
  assetId: number | undefined;
  description: string;
  may: boolean;
  onAction: (action: ExclusionAction) => void;
}) {
  const manual = s.exclusion;
  return (
    <tr>
      <td>
        <StatusChip
          kind="ne107"
          value={(NE107.includes(s.status as Ne107) ? s.status : "Failure") as Ne107}
          size="s"
        />
      </td>
      <td className="mono">{s.source_name}</td>
      <td>{assetId ? <Link to={`/assets/${assetId}`}>{s.asset_code}</Link> : s.asset_code}</td>
      <td>{description}</td>
      <td>{ruleOrReason(s)}</td>
      <td title={s.models.join(", ")}>
        {s.models.length ? s.models.length : <span className="muted">0</span>}
      </td>
      <td>{scoringUse(s)}</td>
      <td title={formatIso(new Date(s.since))}>{formatDateTime(new Date(s.since))}</td>
      {may && (
        <td>
          <span className="lifecycle">
            {manual ? (
              <button
                type="button"
                className="button button-small"
                onClick={() =>
                  onAction({
                    kind: "end",
                    exclusionId: manual.id,
                    name: s.source_name,
                    what: manual.kind,
                  })
                }
              >
                End {manual.kind === "override" ? "override" : "exclusion"}
              </button>
            ) : (
              <>
                <button
                  type="button"
                  className="button button-small"
                  aria-label={`Exclude ${s.source_name}`}
                  onClick={() =>
                    onAction({ kind: "exclude", tagId: s.tag_id, name: s.source_name })
                  }
                >
                  Exclude…
                </button>
                {canOverride(s) && (
                  <button
                    type="button"
                    className="button button-small"
                    aria-label={`Override ${s.source_name}`}
                    onClick={() =>
                      onAction({ kind: "override", tagId: s.tag_id, name: s.source_name })
                    }
                  >
                    Override…
                  </button>
                )}
              </>
            )}
          </span>
        </td>
      )}
    </tr>
  );
}
