import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { fetchModels } from "../../api/models";
import { useBreadcrumbs } from "../../app/breadcrumbs";
import { formatDateTime, formatDi, formatIso } from "../../app/format";
import { StatusChip } from "../../components/StatusChip";
import { Skeleton } from "../fleet/FleetPage";
import { LifecycleActions } from "./LifecycleActions";
import { alertRate } from "./modelsModel";
import { useRowKeys } from "../../components/tableKeys";

/**
 * SCR-10 Model management (PDS §4.8, FR-MOD-07): every model with the version in service,
 * its runtime status, when it was trained, its alert rate, and the lifecycle actions.
 */
export function ModelsPage() {
  const rowKeys = useRowKeys();
  useBreadcrumbs([{ label: "Model management" }]);
  const [params, setParams] = useSearchParams();
  const status = params.get("status");
  const models = useQuery({
    queryKey: ["models", "list"],
    queryFn: ({ signal }) => fetchModels(signal),
  });
  const rows = useMemo(
    () =>
      (models.data ?? [])
        .filter((m) => !status || (m.runtime?.status ?? "Not scored yet") === status)
        .sort((a, b) => a.asset_code.localeCompare(b.asset_code) || a.name.localeCompare(b.name)),
    [models.data, status],
  );
  const statuses = [
    ...new Set((models.data ?? []).map((m) => m.runtime?.status ?? "Not scored yet")),
  ].sort();

  return (
    <section className="panel" aria-labelledby="models-title">
      <div className="panel-head">
        <h2 id="models-title" className="panel-title">
          Models ({rows.length})
        </h2>
        <Link className="button button-primary" to="/models/new/build/1">
          New model
        </Link>
        <label className="field-inline">
          <span>Runtime status</span>
          <select
            className="control"
            value={status ?? ""}
            onChange={(e) =>
              setParams((c) => {
                const p = new URLSearchParams(c);
                if (e.target.value) p.set("status", e.target.value);
                else p.delete("status");
                return p;
              })
            }
          >
            <option value="">All</option>
            {statuses.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>
      {models.isPending ? (
        <Skeleton rows={6} />
      ) : models.isError ? (
        <p role="alert">{models.error.message}</p>
      ) : rows.length === 0 ? (
        <p className="muted">
          No models{status ? ` with status ${status}` : ""}. New models are built with the model
          builder (next step of this phase).
        </p>
      ) : (
        <table ref={rowKeys} className="tree-table models-table">
          <thead>
            <tr>
              <th scope="col">Asset / model</th>
              <th scope="col">In service</th>
              <th scope="col">Runtime</th>
              <th scope="col">Band</th>
              <th scope="col" className="num">
                DI
              </th>
              <th scope="col">Trained / deployed</th>
              <th scope="col" className="num">
                Alerts (30 d)
              </th>
              <th scope="col">Latest version</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => {
              const current = m.in_service;
              const when = current?.status_changed_at ?? current?.created_at;
              const newer = m.latest.id !== current?.id;
              return (
                <tr key={m.id}>
                  <td>
                    <Link to={`/models/${m.id}/versions/${current?.version ?? m.latest.version}`}>
                      {m.asset_code} / {m.name}
                    </Link>
                  </td>
                  <td>
                    {current ? (
                      `v${current.version} · ${current.algorithm} · ${current.status}`
                    ) : (
                      <span className="muted">none</span>
                    )}
                  </td>
                  <td>{m.runtime?.status ?? <span className="muted">Not scored yet</span>}</td>
                  <td>
                    {m.runtime ? <StatusChip kind="band" value={m.runtime.band} size="s" /> : "—"}
                  </td>
                  <td className="num">{formatDi(m.runtime?.di)}</td>
                  <td>
                    {when ? (
                      <time dateTime={when} title={formatIso(new Date(when))}>
                        {formatDateTime(new Date(when))}
                      </time>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="num" title={`${m.alerts_30d} raised in the last 30 days`}>
                    {alertRate(m.alerts_30d)}
                  </td>
                  <td>
                    {newer ? (
                      <Link to={`/models/${m.id}/versions/${m.latest.version}`}>
                        v{m.latest.version} · {m.latest.status}
                      </Link>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>
                    <LifecycleActions model={m} compact />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
