import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { acknowledgeAlerts, fetchAlerts } from "../../api/alerts";
import { fetchAsset } from "../../api/assets";
import {
  fetchLatest,
  fetchModel,
  fetchOutputs,
  fetchScores,
  fetchStatusPeriods,
} from "../../api/models";
import type { ModelDetail, SensorNow } from "../../api/types";
import { useBreadcrumbs } from "../../app/breadcrumbs";
import { formatDateTime, formatDi, formatHealth, formatIso, formatZ } from "../../app/format";
import { useAnnounce } from "../../app/liveContext";
import { useTimeRange } from "../../app/timeRange";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { StatusChip } from "../../components/StatusChip";
import { StatusShape } from "../../components/StatusShape";
import { TrendChart } from "../../components/TrendChart";
import type { Ne107 } from "../../components/status";
import { bandLook } from "../../components/status";
import { Skeleton } from "../fleet/FleetPage";
import {
  alertPeriods,
  alertSummary,
  alertWindow,
  comparableVersions,
  excludedPeriods,
  linePoints,
  needsAck,
  sensorChartData,
  sensorLabel,
  sensorOrder,
  topContributors,
  worstAlert,
} from "./assetModel";

const CHART_PX = 800;
const MAX_CHARTS = 6;

/**
 * SCR-03 Asset analysis (PDS §4.3, UC-09, FR-VIS-02, FR-DIA-01, FR-DQ-02): what is abnormal
 * on this asset, since when, and which sensors drive it. Every chart shares the global time
 * range and cursor; the state (model, version, charted sensors, alert) is in the URL.
 */
export function AssetPage() {
  const id = Number(useParams().assetId);
  const [params, setParams] = useSearchParams();
  const { range, setCustom } = useTimeRange();
  const client = useQueryClient();
  const announce = useAnnounce();

  const detail = useQuery({
    queryKey: ["assets", "detail", id],
    queryFn: ({ signal }) => fetchAsset(id, signal),
    enabled: Number.isFinite(id),
  });
  const asset = detail.data;
  const models = asset?.health.models ?? [];
  const modelId = Number(params.get("model")) || models[0]?.model_id || null;
  const version = Number(params.get("version")) || null;

  useBreadcrumbs(
    asset
      ? [
          { label: "Fleet", to: "/fleet" },
          ...asset.ancestors.map((a) => ({ label: a.name, to: `/units/${a.id}` })),
          { label: asset.name.includes(asset.code) ? asset.name : `${asset.code} ${asset.name}` },
        ]
      : null,
  );

  const model = useQuery({
    queryKey: ["models", "detail", modelId],
    queryFn: ({ signal }) => fetchModel(modelId!, signal),
    enabled: modelId !== null,
  });
  const latest = useQuery({
    queryKey: ["models", "latest", modelId, version],
    queryFn: ({ signal }) => fetchLatest(modelId!, version, signal),
    enabled: modelId !== null,
  });
  const alerts = useQuery({
    queryKey: ["alerts", "model", modelId],
    queryFn: ({ signal }) =>
      fetchAlerts({ modelId: modelId!, includeClosed: true, limit: 1000 }, signal),
    enabled: modelId !== null,
  });

  // An alert link (?alert=ID) opens on that alert's window, once.
  const alertParam = Number(params.get("alert")) || null;
  const linked = alerts.data?.items.find((a) => a.id === alertParam) ?? null;
  const hasRange = params.has("from") || params.has("range");
  useEffect(() => {
    if (linked && !hasRange) {
      const window = alertWindow(linked);
      setCustom(window.from, window.to);
    }
  }, [linked, hasRange, setCustom]);

  const from = range.from;
  const to = range.to;
  const rangeKey = [from.toISOString(), to.toISOString()];
  const scores = useQuery({
    queryKey: ["scores", modelId, version, ...rangeKey],
    queryFn: ({ signal }) => fetchScores(modelId!, from, to, CHART_PX, signal, version),
    enabled: modelId !== null,
  });
  const periods = useQuery({
    queryKey: ["models", "periods", modelId, version, ...rangeKey],
    queryFn: ({ signal }) => fetchStatusPeriods(modelId!, from, to, version, signal),
    enabled: modelId !== null,
  });

  const sensors = useMemo(() => latest.data?.sensors ?? [], [latest.data]);
  const contributors = useMemo(() => topContributors(sensors), [sensors]);
  const chosen = useMemo(() => {
    const listed = params.get("sensors");
    if (listed !== null) return listed.split(",").filter(Boolean);
    return contributors.slice(0, 2).map((c) => c.sensor.source_name);
  }, [params, contributors]);
  const outputs = useQuery({
    queryKey: ["scores", "outputs", modelId, version, chosen.join(","), ...rangeKey],
    queryFn: ({ signal }) => fetchOutputs(modelId!, chosen, from, to, CHART_PX, version, signal),
    enabled: modelId !== null && chosen.length > 0,
  });

  function toggleSensor(name: string) {
    const next = chosen.includes(name)
      ? chosen.filter((n) => n !== name)
      : [...chosen, name].slice(-MAX_CHARTS);
    setParams((current) => {
      const p = new URLSearchParams(current);
      p.set("sensors", next.join(","));
      return p;
    });
  }

  function chooseVersion(value: string) {
    setParams((current) => {
      const p = new URLSearchParams(current);
      if (value) p.set("version", value);
      else p.delete("version");
      return p;
    });
  }

  const openUnack = (alerts.data?.items ?? []).filter((a) => !a.closed_at && needsAck(a));
  const [acking, setAcking] = useState(false);
  const ack = useMutation({
    mutationFn: (comment: string) =>
      acknowledgeAlerts(
        openUnack.map((a) => a.id),
        comment,
      ),
    onSuccess: (done) => {
      announce(`${done.length} alert${done.length === 1 ? "" : "s"} acknowledged`);
      void client.invalidateQueries({
        predicate: (q) => ["alerts", "assets", "fleet", "models"].includes(String(q.queryKey[0])),
      });
    },
  });

  if (detail.isError) {
    return (
      <section className="panel" role="alert">
        {detail.error.message}
      </section>
    );
  }
  if (!asset) return <Skeleton rows={8} />;
  if (!modelId) {
    return (
      <section className="panel empty-state">
        <h2 className="panel-title">{asset.name}</h2>
        <p>
          This asset has no model in service, so there is nothing to analyse yet. Models are created
          under Models.
        </p>
      </section>
    );
  }

  const m = model.data;
  const diRule = m?.alert_rules.find((r) => r.kind === "di");
  const alertBars = alertPeriods(alerts.data?.items ?? []);
  const excluded = excludedPeriods(periods.data ?? [], m?.runtime ?? null, to.getTime());
  const settings = { from: from.getTime(), to: to.getTime() };
  const byName = new Map(sensors.map((s) => [s.source_name, s]));

  return (
    <div className="asset">
      <div className="asset-actions">
        {models.length > 1 && (
          <label className="field-inline">
            <span>Model</span>
            <select
              className="control"
              value={modelId}
              onChange={(e) =>
                setParams((c) => {
                  const p = new URLSearchParams(c);
                  p.set("model", e.target.value);
                  p.delete("version");
                  p.delete("sensors");
                  return p;
                })
              }
            >
              {models.map((x) => (
                <option key={x.model_id} value={x.model_id}>
                  {x.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <button
          type="button"
          className="button"
          disabled={!openUnack.length}
          onClick={() => setAcking(true)}
        >
          Acknowledge{openUnack.length ? ` (${openUnack.length})` : ""}
        </button>
        <span className="muted later-note">Exclude sensor and Diagnose arrive in Release 2.</span>
      </div>

      <div className="asset-grid">
        <section className="panel summary" aria-labelledby="summary-title">
          <h2 id="summary-title" className="panel-title">
            {asset.name}
          </h2>
          <Summary
            model={m}
            latest={latest.data}
            alert={worstAlert(alerts.data?.items ?? [])}
            version={version}
            onVersion={chooseVersion}
          />
        </section>

        <section className="panel" aria-label="Deviation Index and Health">
          <TrendChart
            title={`Deviation Index (%)${diRule ? ` · warning ${diRule.warning} · alert ${diRule.alert}` : ""} · shaded = not scored normally`}
            data={{
              actual: scores.data ? linePoints(scores.data, "di") : [],
              limits: diRule ? { warning: [diRule.warning], alert: [diRule.alert] } : undefined,
              excluded,
              alerts: alertBars,
            }}
            settings={{ ...settings, unit: "%", actualName: "DI" }}
            height={210}
            loading={scores.isPending}
          />
          <TrendChart
            title="Health score"
            data={{ actual: scores.data ? linePoints(scores.data, "health") : [], excluded }}
            settings={{ ...settings, unit: "", actualName: "Health" }}
            height={120}
            loading={scores.isPending}
          />
        </section>

        <section className="panel" aria-labelledby="contrib-title">
          <h2 id="contrib-title" className="panel-title">
            Top contributors now
          </h2>
          {latest.isPending ? (
            <Skeleton rows={5} />
          ) : contributors.length === 0 ? (
            <p className="muted">No deviation to explain at the latest cycle.</p>
          ) : (
            <ul className="contributors">
              {contributors.map((c) => (
                <li key={c.sensor.tag_id}>
                  <button
                    type="button"
                    className="contributor"
                    aria-pressed={chosen.includes(c.sensor.source_name)}
                    onClick={() => toggleSensor(c.sensor.source_name)}
                  >
                    <span className="contributor-name" title={sensorLabel(c.sensor)}>
                      {sensorLabel(c.sensor)}
                    </span>
                    <span className="contributor-bar" aria-hidden="true">
                      <span style={{ width: `${Math.round(c.share * 100)}%` }} />
                    </span>
                    <span className="num">{Math.round(c.share * 100)} %</span>
                    <span className="num contributor-z">
                      <span aria-hidden="true">
                        {c.direction === "up" ? "▲" : c.direction === "down" ? "▼" : ""}
                      </span>
                      <span className="visually-hidden">
                        {c.direction === "up" ? "above" : "below"} predicted,{" "}
                      </span>
                      {formatZ(c.sensor.z)}σ
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="muted small">Select a sensor to chart it; select it again to remove it.</p>
        </section>

        <section className="panel" aria-label="Sensors">
          <div className="multiples">
            {chosen.length === 0 && (
              <p className="muted">Choose a sensor below or among the contributors to chart it.</p>
            )}
            {(outputs.data ?? []).map((trend) => {
              const sensor = byName.get(trend.source_name);
              return (
                <TrendChart
                  key={trend.source_name}
                  title={`${sensor ? sensorLabel(sensor) : trend.source_name}: actual (solid) vs predicted (dashed), expected band`}
                  data={sensorChartData(trend, sensor, alertBars)}
                  settings={{ ...settings, unit: sensor?.unit ?? "", actualName: "Actual" }}
                  height={170}
                />
              );
            })}
            {outputs.isPending && chosen.length > 0 && <Skeleton rows={4} />}
          </div>
          <SensorTable
            sensors={sensorOrder(sensors)}
            charted={chosen}
            onToggle={toggleSensor}
            ts={latest.data?.ts ?? null}
          />
        </section>
      </div>

      <ConfirmDialog
        open={acking}
        onOpenChange={setAcking}
        title={`Acknowledge ${openUnack.length} alert${openUnack.length === 1 ? "" : "s"} on ${asset.code}`}
        consequence="Acknowledging records that you have seen them; they stay active until the condition clears. Viewing never acknowledges."
        confirmLabel="Acknowledge"
        reasonLabel="Comment"
        reasonOptional
        onConfirm={async (comment) => {
          await ack.mutateAsync(comment);
        }}
      />
      <p className="muted small">
        <Link to={`/alerts?scope=${encodeURIComponent(asset.code)}&closed=true`}>
          All alerts of this asset
        </Link>
      </p>
    </div>
  );
}

function Summary({
  model,
  latest,
  alert,
  version,
  onVersion,
}: {
  model: ModelDetail | undefined;
  latest: { ts: string | null; version: number; sensors: SensorNow[] } | undefined;
  alert: ReturnType<typeof worstAlert>;
  version: number | null;
  onVersion: (value: string) => void;
}) {
  if (!model) return <Skeleton rows={5} />;
  const runtime = model.runtime;
  const band = runtime?.band ?? "Unknown";
  const look = bandLook(band);
  const current = model.in_service ?? model.latest;
  const cycle = Number(
    (model.versions.find((v) => v.id === current.id)?.params ?? {}).cycle_s ?? 60,
  );
  const used = latest?.sensors.filter((s) => s.used).length ?? 0;
  const total = latest?.sensors.length ?? 0;
  const unusable = latest?.sensors.filter((s) => s.used === false) ?? [];
  const running = runtime?.status === "Running";
  const versions = comparableVersions(model);
  return (
    <div className="summary-body">
      <div className="summary-score">
        <StatusShape shape={look.shape} tone={look.tone} size={30} />
        <span className={`summary-health tone-${look.tone}`}>{formatHealth(runtime?.health)}</span>
        <span className={`chip chip-m tone-${look.tone}`}>
          {look.label} · DI {formatDi(runtime?.di)}
        </span>
      </div>
      {!running && runtime && (
        <div className="summary-state" role="status">
          <StatusChip kind="band" value="Unknown" detail={runtime.status} />
          {runtime.reason ? <div>{runtime.reason}</div> : null}
          {runtime.status === "Insufficient data" && unusable.length > 0 && (
            <div>Not usable now: {unusable.map((s) => sensorLabel(s)).join(", ")}.</div>
          )}
        </div>
      )}
      <table className="summary-table">
        <tbody>
          <tr>
            <th scope="row">Model</th>
            <td>
              {model.asset_code} / {model.name} v{latest?.version ?? current.version} ·{" "}
              {current.algorithm}
            </td>
          </tr>
          {versions.length > 1 && (
            <tr>
              <th scope="row">
                <label htmlFor="version-select">Compare version</label>
              </th>
              <td>
                <select
                  id="version-select"
                  className="control"
                  value={version ?? ""}
                  onChange={(e) => onVersion(e.target.value)}
                >
                  <option value="">All versions (as scored)</option>
                  {versions.map((v) => (
                    <option key={v.id} value={v.version}>
                      v{v.version} · {v.status}
                    </option>
                  ))}
                </select>
              </td>
            </tr>
          )}
          <tr>
            <th scope="row">Coverage</th>
            <td>
              {used} / {total} sensors
            </td>
          </tr>
          <tr>
            <th scope="row">Last scored</th>
            <td title={latest?.ts ? formatIso(new Date(latest.ts)) : undefined}>
              {latest?.ts
                ? `${formatDateTime(new Date(latest.ts))} (${cycle / 60} min cycle)`
                : "Not scored yet"}
            </td>
          </tr>
          <tr>
            <th scope="row">Status</th>
            <td>
              {runtime?.status ?? "Not scored yet"}
              {runtime?.since ? ` since ${formatDateTime(new Date(runtime.since))}` : ""}
            </td>
          </tr>
          <tr>
            <th scope="row">Alert</th>
            <td>{alert ? alertSummary(alert) : "None open"}</td>
          </tr>
          <tr>
            <th scope="row">Forecast</th>
            <td className="muted">Release 2 (prognostics)</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function SensorTable({
  sensors,
  charted,
  onToggle,
  ts,
}: {
  sensors: SensorNow[];
  charted: readonly string[];
  onToggle: (name: string) => void;
  ts: string | null;
}) {
  return (
    <table className="tree-table sensor-table">
      <caption className="visually-hidden">
        Sensors at the latest cycle{ts ? ` (${formatDateTime(new Date(ts))})` : ""}, largest
        deviation first
      </caption>
      <thead>
        <tr>
          <th scope="col">Sensor</th>
          <th scope="col">Unit</th>
          <th scope="col" className="num">
            Actual
          </th>
          <th scope="col" className="num">
            Predicted
          </th>
          <th scope="col" className="num">
            z
          </th>
          <th scope="col">Signal status (NE 107)</th>
          <th scope="col">
            <span className="visually-hidden">Chart</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {sensors.map((s) => {
          const on = charted.includes(s.source_name);
          const status = s.dq_status as Ne107;
          return (
            <tr key={s.tag_id}>
              <td>{sensorLabel(s)}</td>
              <td className="muted">{s.unit}</td>
              <td className="num">{fmt(s.actual)}</td>
              <td className="num">{fmt(s.predicted)}</td>
              <td className="num">{formatZ(s.z)}</td>
              <td>
                <StatusChip
                  kind="ne107"
                  value={status}
                  detail={
                    status !== "Good" && s.dq_rule && s.dq_rule !== "none"
                      ? s.dq_rule.replace(/_/g, " ")
                      : null
                  }
                  size="s"
                />
              </td>
              <td>
                <button
                  type="button"
                  className="link-button"
                  aria-pressed={on}
                  aria-label={`${on ? "Remove" : "Chart"} ${sensorLabel(s)}`}
                  onClick={() => onToggle(s.source_name)}
                >
                  {on ? "Charted" : "Chart"}
                </button>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function fmt(value: number | null): string {
  if (value === null) return "—";
  const digits = Math.abs(value) >= 100 ? 1 : 2;
  return value.toLocaleString("en-GB", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}
