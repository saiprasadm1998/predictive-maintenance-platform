import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "../../api/client";
import { fetchAudit, fetchModel, fetchScores, fetchStatusPeriods } from "../../api/models";
import type { AuditEntry, ModelDetail, VersionDetail } from "../../api/types";
import { useBreadcrumbs } from "../../app/breadcrumbs";
import { formatDateTime, formatIso } from "../../app/format";
import { useTimeRange } from "../../app/timeRange";
import { TrendChart } from "../../components/TrendChart";
import { excludedPeriods, linePoints, sensorLabel } from "../asset/assetModel";
import { Skeleton } from "../fleet/FleetPage";
import { LifecycleActions } from "./LifecycleActions";

/**
 * SCR-11 Model version detail (PDS §4.8, FR-MOD-06, FR-AUD-01): configuration, training
 * definition, validation metrics, playback of what this version scored, its alert limits,
 * and its audit history.
 */
export function VersionPage() {
  const modelId = Number(useParams().modelId);
  const number = Number(useParams().version);
  const { range } = useTimeRange();
  const model = useQuery({
    queryKey: ["models", "detail", modelId],
    queryFn: ({ signal }) => fetchModel(modelId, signal),
  });
  const m = model.data;
  const version = m?.versions.find((v) => v.version === number);
  useBreadcrumbs(
    m
      ? [
          { label: "Models", to: "/models" },
          { label: `${m.asset_code} / ${m.name}` },
          { label: `v${number}` },
        ]
      : null,
  );

  const playable =
    version && ["Deployed", "Paused", "Superseded", "Retired"].includes(version.status);
  const key = [range.from.toISOString(), range.to.toISOString()];
  const scores = useQuery({
    queryKey: ["scores", modelId, number, ...key],
    queryFn: ({ signal }) => fetchScores(modelId, range.from, range.to, 800, signal, number),
    enabled: !!playable,
  });
  const periods = useQuery({
    queryKey: ["models", "periods", modelId, number, ...key],
    queryFn: ({ signal }) => fetchStatusPeriods(modelId, range.from, range.to, number, signal),
    enabled: !!playable,
  });
  const audit = useQuery({
    queryKey: ["models", "audit", version?.id],
    queryFn: async ({ signal }) => {
      const [ofVersion, ofModel] = await Promise.all([
        fetchAudit("model_version", version!.id, signal),
        fetchAudit("model", modelId, signal),
      ]);
      return [...ofVersion.items, ...ofModel.items].sort((a, b) => b.ts.localeCompare(a.ts));
    },
    enabled: !!version,
    retry: false,
  });

  if (model.isError)
    return (
      <section className="panel" role="alert">
        {model.error.message}
      </section>
    );
  if (!m) return <Skeleton rows={8} />;
  if (!version) {
    return (
      <section className="panel" role="alert">
        {m.asset_code} / {m.name} has no version {number}.{" "}
        <Link to="/models">Back to the models</Link>.
      </section>
    );
  }
  const di = m.alert_rules.find((r) => r.kind === "di");
  const tagNames = new Map(version.sensors.map((s) => [s.tag_id, sensorLabel(s)]));

  return (
    <div className="version">
      <section className="panel version-head" aria-label="Version summary">
        <div>
          <div className="unit-title">
            {m.asset_code} / {m.name} · v{version.version}
          </div>
          <div className="muted">
            {version.algorithm} · {version.status}
            {version.status_changed_at
              ? ` since ${formatDateTime(new Date(version.status_changed_at))}`
              : ""}{" "}
            · created {formatDateTime(new Date(version.created_at))}
          </div>
          {version.error && (
            <p role="alert" className="form-error">
              {version.error}
            </p>
          )}
        </div>
        <div className="field-inline">
          <VersionPicker model={m} current={number} />
          <LifecycleActions model={m} />
        </div>
      </section>

      <div className="version-grid">
        <section className="panel" aria-labelledby="config-title">
          <h2 id="config-title" className="panel-title">
            Configuration and training definition
          </h2>
          <table className="summary-table">
            <tbody>
              <tr>
                <th scope="row">Algorithm</th>
                <td>{version.algorithm}</td>
              </tr>
              <tr>
                <th scope="row">Parameters</th>
                <td>
                  {Object.entries(version.params)
                    .map(([k, v]) => `${k} ${String(v)}`)
                    .join(" · ") || "—"}
                </td>
              </tr>
              <tr>
                <th scope="row">Training periods</th>
                <td>{(version.training_periods ?? []).map(period).join("; ") || "—"}</td>
              </tr>
              <tr>
                <th scope="row">Validation period</th>
                <td>{version.validation_period ? period(version.validation_period) : "—"}</td>
              </tr>
              <tr>
                <th scope="row">Operating mode</th>
                <td>{(version.mode_filters ?? []).join(" and ") || "always"}</td>
              </tr>
              <tr>
                <th scope="row">Artefact</th>
                <td className="mono">
                  {version.artefact_sha256
                    ? `SHA-256 ${version.artefact_sha256.slice(0, 16)}…`
                    : "not trained"}
                </td>
              </tr>
            </tbody>
          </table>
          <h3 className="panel-title">Sensors ({version.sensors.length})</h3>
          <ul className="plain-list">
            {version.sensors.map((s) => (
              <li key={s.tag_id}>
                {sensorLabel(s)}
                {s.required ? <b> · required</b> : null}
              </li>
            ))}
          </ul>
        </section>

        <section className="panel" aria-labelledby="metrics-title">
          <h2 id="metrics-title" className="panel-title">
            Training and validation
          </h2>
          <Metrics version={version} />
          <h3 className="panel-title">Alert limits (active)</h3>
          <table className="tree-table">
            <thead>
              <tr>
                <th scope="col">Rule</th>
                <th scope="col" className="num">
                  Warning
                </th>
                <th scope="col" className="num">
                  Alert
                </th>
                <th scope="col">Persistence</th>
                <th scope="col">State</th>
              </tr>
            </thead>
            <tbody>
              {m.alert_rules.map((r) => (
                <tr key={r.id}>
                  <td>
                    {r.kind === "di"
                      ? "Deviation Index (%)"
                      : `|z| of ${tagNames.get(r.tag_id ?? -1) ?? r.tag_id}`}
                  </td>
                  <td className="num">{r.warning}</td>
                  <td className="num">{r.alert}</td>
                  <td>
                    {r.persistence_n !== undefined
                      ? `${r.persistence_n} of ${r.persistence_m}`
                      : "—"}
                  </td>
                  <td>{STATE_TEXT[r.state] ?? r.state}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">
            Proposed limits from validation arrive with the prediction model (Phase 7).
          </p>
        </section>
      </div>

      <section className="panel" aria-label="Playback">
        {playable ? (
          <TrendChart
            title={`Playback: Deviation Index scored by v${version.version} (%)`}
            data={{
              actual: scores.data ? linePoints(scores.data, "di") : [],
              limits: di ? { warning: [di.warning], alert: [di.alert] } : undefined,
              excluded: excludedPeriods(periods.data ?? [], null, range.to.getTime()),
            }}
            settings={{
              from: range.from.getTime(),
              to: range.to.getTime(),
              unit: "%",
              actualName: "DI",
            }}
            height={200}
            loading={scores.isPending}
          />
        ) : (
          <p className="muted">
            v{version.version} has not been in service, so there is nothing to play back yet.
          </p>
        )}
      </section>

      <section className="panel" aria-labelledby="audit-title">
        <h2 id="audit-title" className="panel-title">
          Audit history
        </h2>
        {audit.isPending ? (
          <Skeleton rows={4} />
        ) : audit.isError ? (
          <p className="muted">
            {audit.error instanceof ApiError && audit.error.status === 403
              ? "The audit history is shown to administrators."
              : audit.error.message}
          </p>
        ) : (
          <AuditList entries={audit.data} />
        )}
      </section>
    </div>
  );
}

const STATE_TEXT: Record<string, string> = {
  "Active-Unacknowledged": "Active · unack",
  "Active-Acknowledged": "Active · ack",
  "RTN-Unacknowledged": "RTN · unack",
};

function period(p: { start: string; end: string }): string {
  return `${formatDateTime(new Date(p.start))} – ${formatDateTime(new Date(p.end))}`;
}

function VersionPicker({ model, current }: { model: ModelDetail; current: number }) {
  return (
    <nav aria-label="Versions" className="field-inline">
      {model.versions.map((v) =>
        v.version === current ? (
          <b key={v.id} aria-current="page">
            v{v.version}
          </b>
        ) : (
          <Link key={v.id} to={`/models/${model.id}/versions/${v.version}`} title={v.status}>
            v{v.version}
          </Link>
        ),
      )}
    </nav>
  );
}

function Metrics({ version }: { version: VersionDetail }) {
  const metrics = version.metrics ?? {};
  const value = (key: string) =>
    typeof metrics[key] === "number" ? metrics[key].toLocaleString("en-GB") : "—";
  const floored = Array.isArray(metrics.floored_sensors)
    ? (metrics.floored_sensors as string[])
    : [];
  if (!version.metrics) return <p className="muted">Not trained yet.</p>;
  return (
    <table className="summary-table">
      <tbody>
        <tr>
          <th scope="row">Training cycles kept</th>
          <td>
            {value("training_retained")} of {value("training_cycles")}
          </td>
        </tr>
        <tr>
          <th scope="row">Validation cycles kept</th>
          <td>
            {value("validation_retained")} of {value("validation_cycles")}
          </td>
        </tr>
        <tr>
          <th scope="row">Floored sensors</th>
          <td>{floored.length ? floored.join(", ") : "none"}</td>
        </tr>
      </tbody>
    </table>
  );
}

const AUDIT_ACTIONS: Record<string, string> = {
  create: "Model created",
  update_draft: "Draft changed",
  fix_failed: "Failed version reopened",
  new_version: "New version",
  train: "Training started",
  trained: "Trained and validated",
  train_failed: "Training failed",
};

function AuditList({ entries }: { entries: AuditEntry[] }) {
  if (!entries.length) return <p className="muted">No changes recorded.</p>;
  return (
    <ol className="history">
      {entries.map((e) => (
        <li key={e.id}>
          <time dateTime={e.ts} title={formatIso(new Date(e.ts))}>
            {formatDateTime(new Date(e.ts))}
          </time>{" "}
          <b>{AUDIT_ACTIONS[e.action] ?? e.action.replace(/_/g, " ")}</b> ·{" "}
          {e.entity.replace("_", " ")} {e.entity_id} ·{" "}
          {e.actor_type === "system" ? "system" : `user ${e.user_id ?? "?"}`}
          {e.after && "status" in e.after ? (
            <span className="muted"> → {String(e.after.status)}</span>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
