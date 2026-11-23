import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";

import { endExclusion } from "../../api/admin";
import { fetchAllAlerts } from "../../api/alerts";
import { fetchAsset } from "../../api/assets";
import { errorMessages } from "../../api/client";
import { fetchDiagnosis } from "../../api/diagnostics";
import { fetchForecasts, runForecast, type Forecast } from "../../api/forecasts";
import {
  fetchLatest,
  fetchModel,
  fetchOutputs,
  fetchScores,
  fetchStatusPeriods,
} from "../../api/models";
import type { Alert, ModelDetail, SensorNow } from "../../api/types";
import { useCases, useSensorHealth } from "../../app/data";
import { formatDateTime } from "../../app/format";
import { useScope } from "../../app/scope";
import { NE107_CODE, alertState, plainDescription, shortTag } from "../../app/words";
import { Chart, Legend, type Pt } from "../../components/Chart";
import { trendPoints } from "../../components/chartData";
import {
  Badge,
  Empty,
  HowTo,
  KeyValues,
  PageHeader,
  Panel,
  Pill,
  Problems,
  Tabs,
} from "../../components/ui";
import { bandTone } from "../../components/tones";
import { AckDialog, CaseDialog } from "../alerts/AlertDialogs";
import {
  forecastChart,
  intervalText,
  methodText,
  WINDOW_CHOICES,
} from "../diagnostics/forecastModel";
import { ExcludeDialog } from "./ExcludeDialog";

type Tab = "trends" | "diagnosis" | "forecast" | "sensors";
const DAY = 86_400_000;

/** /assets without an id: the worst equipment in scope. */
export function AnalysisIndexPage() {
  const scope = useScope();
  if (!scope.tree.length) return <p className="sec s13">Loading…</p>;
  const order: Record<string, number> = { Alert: 0, Watch: 1, Unknown: 2, Healthy: 3 };
  const pick = [...scope.equipment].sort(
    (a, b) =>
      (order[a.band ?? "z"] ?? 9) - (order[b.band ?? "z"] ?? 9) ||
      (a.health ?? 101) - (b.health ?? 101),
  )[0];
  if (!pick)
    return (
      <>
        <PageHeader title="Equipment analysis" />
        <Panel>
          <Empty>No equipment in this scope yet. Add equipment in Set up.</Empty>
        </Panel>
      </>
    );
  return <Navigate to={`/assets/${pick.id}`} replace />;
}

function needsAck(a: Alert): boolean {
  return a.state === "Active-Unacknowledged" || a.state === "RTN-Unacknowledged";
}

export function AnalysisPage() {
  const { assetId } = useParams();
  const id = Number(assetId);
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab | null) ?? "trends";
  const [now] = useState(() => Date.now());
  const from = now - 7 * DAY;
  const asset = useQuery({
    queryKey: ["assets", id],
    queryFn: ({ signal }) => fetchAsset(id, signal),
  });
  const modelId = asset.data?.health.models[0]?.model_id;
  const model = useQuery({
    queryKey: ["models", modelId],
    queryFn: ({ signal }) => fetchModel(modelId!, signal),
    enabled: !!modelId,
  });
  const latest = useQuery({
    queryKey: ["models", modelId, "latest"],
    queryFn: ({ signal }) => fetchLatest(modelId!, null, signal),
    enabled: !!model.data?.in_service,
  });
  const alerts = useQuery({
    queryKey: ["alerts", "asset", asset.data?.code],
    queryFn: async ({ signal }) =>
      (await fetchAllAlerts({ asset: asset.data!.code }, signal)).items,
    enabled: !!asset.data,
  });
  const forecasts = useQuery({
    queryKey: ["forecasts", modelId],
    queryFn: ({ signal }) => fetchForecasts(modelId!, 5, signal),
    enabled: !!modelId,
  });
  const cases = useCases(true);
  const [dialog, setDialog] = useState<"ack" | "case" | null>(null);

  if (asset.isError) return <Problems messages={errorMessages(asset.error)} />;
  const a = asset.data;
  if (!a) return <p className="sec s13">Loading…</p>;

  const m = model.data;
  const open = (alerts.data ?? []).filter((x) => !x.closed_at);
  const unack = open.filter(needsAck);
  const worst = [...open].sort((x, y) => (x.priority ?? "P9").localeCompare(y.priority ?? "P9"))[0];
  const openCase = (cases.data ?? []).find((c) => c.asset_id === id);
  const sensors = latest.data?.sensors ?? [];
  const used = sensors.filter((s) => s.used !== false).length;
  const lastForecast = forecasts.data?.[0];
  const health = a.health.health;
  const band = a.health.band;
  const di = m?.runtime?.di;
  const setTab = (t: Tab) => {
    params.set("tab", t);
    setParams(params, { replace: true });
  };
  const parents = a.ancestors.slice(-3);
  const crumbs = [
    { label: "Overview", to: "/fleet" },
    ...parents.map((c, i) => ({
      label: c.name,
      to: i === parents.length - 1 ? `/units/${c.id}` : undefined,
    })),
    { label: a.name },
  ];
  const statusText = m?.runtime
    ? `${m.runtime.status} since ${formatDateTime(new Date(m.runtime.since))}`
    : m
      ? "Not deployed"
      : "No model";
  const caseCandidates = open.filter((x) => !x.case_id && !x.closed_at);

  return (
    <>
      <PageHeader
        crumbs={crumbs}
        title={`${a.name}${a.name.includes(a.code) ? "" : ` ${a.code}`}`}
        sub={
          <span className="chips" style={{ alignItems: "center" }}>
            {a.criticality && <Badge>Criticality {a.criticality}</Badge>}
            {a.asset_type && <Badge>{a.health.asset_type_name ?? a.asset_type}</Badge>}
            <span>Window: last 7 days</span>
          </span>
        }
        actions={
          <>
            <HowTo title="How to read this page">
              The model predicts what every sensor should read now. The Deviation Index measures how
              far the actual values are from those predictions; health is 100 at normal and 50 at
              the alert limit. Hatched periods were not scored normally.
            </HowTo>
            <button className="btn btn-s" type="button" onClick={() => setTab("diagnosis")}>
              Diagnose →
            </button>
            <button
              className="btn btn-s"
              type="button"
              disabled={!unack.length}
              onClick={() => setDialog("ack")}
            >
              Acknowledge ({unack.length})
            </button>
            {openCase ? (
              <Link className="btn btn-p" to={`/cases/${openCase.id}`}>
                Open {openCase.number}
              </Link>
            ) : (
              <button
                className="btn btn-p"
                type="button"
                disabled={!caseCandidates.length}
                onClick={() => setDialog("case")}
              >
                Create case
              </button>
            )}
          </>
        }
      />
      <div className="twor">
        <Panel title={`${a.name}${a.name.includes(a.code) ? "" : ` ${a.code}`}`}>
          <div style={{ display: "flex", alignItems: "center", gap: 14, margin: "4px 0 16px" }}>
            <span
              className="bigh"
              style={{
                color:
                  band === "Alert"
                    ? "var(--traverse-status-danger-fg)"
                    : band === "Watch"
                      ? "var(--traverse-status-warning-fg)"
                      : undefined,
              }}
            >
              {health === null ? "n/a" : Math.round(health)}
            </span>
            <Pill tone={bandTone(band)}>
              {band ?? "Not monitored"}
              {di !== null && di !== undefined ? `, DI ${di.toFixed(1)} %` : ""}
            </Pill>
          </div>
          <KeyValues
            rows={[
              [
                "Model",
                m ? (
                  <>
                    <Link
                      to={`/models/${m.id}/versions/${m.in_service?.version ?? m.latest.version}`}
                    >{`${m.name} v${m.in_service?.version ?? m.latest.version}`}</Link>
                    , {m.latest.algorithm.toUpperCase()}
                  </>
                ) : (
                  <Link to={`/models?asset=${a.code}`}>No model yet: build one</Link>
                ),
              ],
              ["Coverage", sensors.length ? `${used} of ${sensors.length} sensors` : "—"],
              [
                "Last scored",
                m?.runtime?.last_cycle
                  ? `${formatDateTime(new Date(m.runtime.last_cycle))}, 1-minute cycle`
                  : "Not scored yet",
              ],
              ["Status", m?.runtime?.reason ? `${statusText}: ${m.runtime.reason}` : statusText],
              [
                "Alert",
                worst
                  ? `${worst.priority ?? "—"}, ${alertState(worst.state).label.toLowerCase()}`
                  : "None open",
              ],
              ["Forecast", lastForecast ? forecastLine(lastForecast) : "None run yet"],
              [
                "Open case",
                openCase ? (
                  <>
                    <Link to={`/cases/${openCase.id}`}>{openCase.number}</Link>,{" "}
                    {openCase.status.toLowerCase()}
                  </>
                ) : (
                  "None"
                ),
              ],
            ]}
          />
        </Panel>
        <DeviationPanel model={m} from={from} to={now} />
      </div>
      <Tabs
        label="Analysis"
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "trends", label: "Trends and contributors" },
          { value: "diagnosis", label: "Diagnosis" },
          { value: "forecast", label: "Time to limit" },
          { value: "sensors", label: `Sensors (${sensors.length})` },
        ]}
      />
      {!m ? (
        <Panel>
          <Empty>
            No model scores this equipment yet. <Link to="/models">Build a model</Link> in Set up.
          </Empty>
        </Panel>
      ) : tab === "trends" ? (
        <TrendsTab model={m} sensors={sensors} from={from} to={now} />
      ) : tab === "diagnosis" ? (
        <DiagnosisTab
          model={m}
          sensors={sensors}
          onCase={() => setDialog("case")}
          onForecast={() => setTab("forecast")}
        />
      ) : tab === "forecast" ? (
        <ForecastTab model={m} sensors={sensors} alert={worst} last={lastForecast} />
      ) : (
        <SensorsTab model={m} sensors={sensors} />
      )}
      {dialog === "ack" && <AckDialog alerts={unack} onClose={() => setDialog(null)} />}
      {dialog === "case" && caseCandidates.length > 0 && (
        <CaseDialog
          alerts={caseCandidates}
          assetId={id}
          assetLabel={`${a.code} ${a.name}`}
          onClose={() => setDialog(null)}
        />
      )}
    </>
  );
}

function forecastLine(f: Forecast): string {
  if (!f.valid || f.lower_h === null) return "No trend towards the limit";
  return `${f.urgency}, ${intervalText(f.lower_h, f.upper_h)} to ${f.threshold_kind === "custom" ? "threshold" : f.threshold_kind}`;
}

function DeviationPanel({
  model,
  from,
  to,
}: {
  model: ModelDetail | undefined;
  from: number;
  to: number;
}) {
  const id = model?.id;
  const scores = useQuery({
    queryKey: ["scores", id, "7d-asset"],
    queryFn: ({ signal }) => fetchScores(id!, new Date(from), new Date(to), 500, signal),
    enabled: !!id,
  });
  const periods = useQuery({
    queryKey: ["models", id, "periods", from],
    queryFn: ({ signal }) => fetchStatusPeriods(id!, new Date(from), new Date(to), null, signal),
    enabled: !!id,
  });
  const rule = model?.alert_rules.find((r) => r.kind === "di");
  const hatched = (periods.data ?? [])
    .filter((p) => p.status !== "Running")
    .map((p) => ({
      from: Date.parse(p.start),
      to: Math.max(Date.parse(p.end), Date.parse(p.start) + 60_000),
    }));
  return (
    <Panel
      title="Deviation Index and health"
      actions={
        rule ? (
          <span className="meta">
            Warning {rule.warning} · alert {rule.alert} · hatched = not scored normally
          </span>
        ) : undefined
      }
    >
      {!id ? (
        <Empty>No model yet.</Empty>
      ) : (
        <>
          <Chart
            from={from}
            to={to}
            height={150}
            yMin={0}
            yTitle="Deviation, %"
            label="Deviation Index, last 7 days"
            hatched={hatched}
            series={scores.data ? [{ points: trendPoints(scores.data, "di"), cls: "pv" }] : []}
            limits={
              rule
                ? [
                    { value: rule.warning, cls: "lw" },
                    { value: rule.alert, cls: "la" },
                  ]
                : []
            }
          />
          <Chart
            from={from}
            to={to}
            height={130}
            yMin={0}
            yMax={100}
            yTitle="Health"
            label="Health, last 7 days"
            hatched={hatched}
            series={scores.data ? [{ points: trendPoints(scores.data, "health"), cls: "s4" }] : []}
          />
          <Legend
            items={[
              { label: "Deviation" },
              { cls: "hp", label: "Health" },
              { cls: "w", label: "Warning" },
              { cls: "a", label: "Alert" },
              { cls: "hx", label: "Not scored normally" },
            ]}
          />
        </>
      )}
    </Panel>
  );
}

function sensorLabel(s: { source_name: string; description: string }) {
  return (
    <>
      <span className="mono" style={{ fontWeight: 700 }}>
        {shortTag(s.source_name)}
      </span>{" "}
      {plainDescription(s.source_name, s.description)}
    </>
  );
}

function TrendsTab({
  model,
  sensors,
  from,
  to,
}: {
  model: ModelDetail;
  sensors: SensorNow[];
  from: number;
  to: number;
}) {
  const [params] = useSearchParams();
  const asked = params.get("sensor");
  const ranked = useMemo(
    () =>
      sensors
        .filter((s) => s.used !== false && (s.contribution ?? 0) > 0)
        .sort((a, b) => (b.contribution ?? 0) - (a.contribution ?? 0)),
    [sensors],
  );
  const [picked, setPicked] = useState<string[] | null>(null);
  const chosen = picked ?? (asked ? [asked] : ranked.slice(0, 2).map((s) => s.source_name));
  const outputs = useQuery({
    queryKey: ["models", model.id, "outputs", chosen.join(","), from],
    queryFn: ({ signal }) =>
      fetchOutputs(model.id, chosen, new Date(from), new Date(to), 300, null, signal),
    enabled: chosen.length > 0 && !!model.in_service,
  });
  const toggle = (name: string) => {
    const base = picked ?? chosen;
    setPicked(base.includes(name) ? base.filter((n) => n !== name) : [...base, name].slice(-4));
  };
  return (
    <div className="twor">
      <Panel title="Top contributors now">
        {ranked.length === 0 ? (
          <Empty>No contributions in the latest cycle.</Empty>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {ranked.slice(0, 6).map((s) => {
              const on = chosen.includes(s.source_name);
              const share = Math.round((s.contribution ?? 0) * 100);
              return (
                <button
                  key={s.tag_id}
                  type="button"
                  className={`sel-btn${on ? " on" : ""}`}
                  aria-pressed={on}
                  onClick={() => toggle(s.source_name)}
                >
                  <span className="s13" style={{ flex: 1, minWidth: 0 }}>
                    {sensorLabel(s)}
                  </span>
                  <span className="bar8" style={{ width: 70 }}>
                    <i style={{ width: `${share}%` }} />
                  </span>
                  <span className="num" style={{ width: 44, textAlign: "right" }}>
                    {share} %
                  </span>
                  <span className="meta" style={{ width: 52, textAlign: "right" }}>
                    {s.z === null
                      ? ""
                      : `${s.z > 0 ? "▲" : "▼"} ${s.z > 0 ? "+" : "−"}${Math.abs(s.z).toFixed(1)}σ`}
                  </span>
                </button>
              );
            })}
            <p className="meta" style={{ marginTop: 8 }}>
              Select a sensor to chart it; select again to remove it.
            </p>
          </div>
        )}
      </Panel>
      <Panel>
        {chosen.length === 0 ? (
          <Empty>Select a sensor to chart it.</Empty>
        ) : (
          <div className="half">
            {chosen.map((name) => {
              const s = sensors.find((x) => x.source_name === name);
              const t = outputs.data?.find((o) => o.source_name === name);
              const pred = t ? trendPoints(t, "predicted") : [];
              const width = s?.sigma ? s.warning * s.sigma : null;
              const band =
                width === null
                  ? undefined
                  : pred
                      .filter((p): p is [number, number] => p[1] !== null)
                      .map(([tt, v]) => [tt, v - width, v + width] as [number, number, number]);
              return (
                <div key={name}>
                  <div className="pt s13">
                    {s ? (
                      <>
                        {shortTag(s.source_name)} {plainDescription(s.source_name, s.description)}:
                        actual (solid) vs predicted (dashed)
                      </>
                    ) : (
                      name
                    )}
                  </div>
                  <Chart
                    from={from}
                    to={to}
                    width={420}
                    height={230}
                    label={`${name} actual and predicted`}
                    band={band}
                    series={
                      t
                        ? [
                            { points: trendPoints(t, "actual"), cls: "pv1" },
                            { points: pred, cls: "est" },
                          ]
                        : []
                    }
                  />
                </div>
              );
            })}
          </div>
        )}
        <Legend
          items={[
            { label: "Actual" },
            { cls: "ds", label: "Predicted" },
            { cls: "bx", label: "Expected band" },
          ]}
        />
      </Panel>
    </div>
  );
}

function DiagnosisTab({
  model,
  sensors,
  onCase,
  onForecast,
}: {
  model: ModelDetail;
  sensors: SensorNow[];
  onCase: () => void;
  onForecast: () => void;
}) {
  const diag = useQuery({
    queryKey: ["models", model.id, "diagnosis", "now"],
    queryFn: ({ signal }) => fetchDiagnosis(model.id, null, signal),
  });
  const [pick, setPick] = useState(0);
  const [done, setDone] = useState<Set<string>>(new Set());
  const modes = diag.data?.modes ?? [];
  const cur = modes[pick];
  const label = (role: string, source: string | null) => {
    const s = sensors.find((x) => x.source_name === source);
    return s?.description || role.replace(/_/g, " ");
  };
  return (
    <div className="two">
      <Panel
        title="Failure-mode match, current"
        actions={
          <button className="btn btn-s btn-sm" type="button" onClick={onCase}>
            Create case
          </button>
        }
      >
        {diag.isPending ? (
          <p className="sec s13">Loading…</p>
        ) : modes.length === 0 ? (
          <Empty>
            {diag.data?.note || "No failure modes are defined for this equipment type."}
          </Empty>
        ) : (
          <>
            {modes.slice(0, 6).map((mm, i) => {
              const score = Math.round(mm.score ?? 0);
              const tr = mm.trend.filter((p) => p.score !== null);
              const d = tr
                .map(
                  (p, j) =>
                    `${j ? "L" : "M"}${((j / Math.max(1, tr.length - 1)) * 70).toFixed(1)},${(18 - ((p.score ?? 0) / 100) * 16).toFixed(1)}`,
                )
                .join("");
              return (
                <button
                  key={mm.mode.id}
                  type="button"
                  className={`sel-btn${i === pick ? " on" : ""}`}
                  aria-pressed={i === pick}
                  onClick={() => setPick(i)}
                >
                  <span style={{ flex: 1 }}>
                    <b>{mm.mode.name}</b>{" "}
                    <span className="meta">ISO 14224: {mm.mode.iso_code}</span>
                  </span>
                  <span className="bar8" style={{ width: 140 }}>
                    <i style={{ width: `${score}%` }} />
                  </span>
                  <span className="num" style={{ width: 52, textAlign: "right" }}>
                    {mm.insufficient_evidence ? "n/a" : `${score} %`}
                  </span>
                  <svg
                    className="mspark"
                    viewBox="0 0 70 20"
                    width="70"
                    height="20"
                    aria-hidden="true"
                  >
                    <path d={d} />
                  </svg>
                </button>
              );
            })}
            <p className="meta" style={{ margin: "8px 0 12px" }}>
              Score = weighted agreement of the observed residual signature with the mode&apos;s
              defined symptoms; a relative ranking, not a calibrated probability.
            </p>
            {cur && (
              <>
                <span className="pt">Symptoms: {cur.mode.name}</span>
                <div className="tw" style={{ marginTop: 8 }}>
                  <table className="tb">
                    <thead>
                      <tr>
                        <th>Symptom (role)</th>
                        <th>Expected</th>
                        <th className="r">Observed z</th>
                        <th className="r">Weight</th>
                        <th>Result</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cur.symptoms.map((s, i) => (
                        <tr key={i}>
                          <td>{label(s.role, s.source_name)}</td>
                          <td>
                            {s.direction === "up"
                              ? "Rise"
                              : s.direction === "down"
                                ? "Fall"
                                : "Any"}
                          </td>
                          <td className="r num">
                            {s.z === null
                              ? "n/a"
                              : `${s.z > 0 ? "+" : "−"}${Math.abs(s.z).toFixed(1)}`}
                          </td>
                          <td className="r num">{s.weight}</td>
                          <td>
                            <Pill
                              tone={
                                s.result === "match"
                                  ? "neutral"
                                  : s.result === "not evaluated"
                                    ? "unknown"
                                    : "neutral"
                              }
                            >
                              {s.result === "match"
                                ? "✓ Match"
                                : s.result === "partial"
                                  ? "Partial"
                                  : s.result === "no match"
                                    ? "No match"
                                    : "Not evaluated"}
                            </Pill>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </>
        )}
      </Panel>
      <Panel title="Recommended tasks">
        {cur?.mode.tasks.length ? (
          <div style={{ display: "flex", flexDirection: "column" }}>
            {cur.mode.tasks.map((t) => (
              <label key={t} className="chk">
                <input
                  type="checkbox"
                  checked={done.has(t)}
                  onChange={() => {
                    const n = new Set(done);
                    if (n.has(t)) n.delete(t);
                    else n.add(t);
                    setDone(n);
                  }}
                />
                {t}
              </label>
            ))}
          </div>
        ) : (
          <Empty>No tasks for this mode.</Empty>
        )}
        <div
          style={{
            marginTop: "auto",
            display: "flex",
            flexDirection: "column",
            gap: 8,
            paddingTop: 16,
          }}
        >
          <p className="meta">Tasks are copied into a case with its snapshot.</p>
          <button
            className="btn btn-s"
            type="button"
            style={{ alignSelf: "flex-start" }}
            onClick={onForecast}
          >
            Time to limit →
          </button>
        </div>
      </Panel>
    </div>
  );
}

function ForecastTab({
  model,
  sensors,
  alert,
  last,
}: {
  model: ModelDetail;
  sensors: SensorNow[];
  alert: Alert | undefined;
  last: Forecast | undefined;
}) {
  const client = useQueryClient();
  const [target, setTarget] = useState<string>(
    last ? (last.target === "di" ? "di" : String(last.tag_id)) : "di",
  );
  const [kind, setKind] = useState<"alert" | "warning">("alert");
  const [series, setSeries] = useState<"corrected" | "actual" | "residual">("corrected");
  const [limit, setLimit] = useState("");
  const [windowDays, setWindowDays] = useState(7);
  const onSensor = target !== "di";
  const sensor = sensors.find((s) => String(s.tag_id) === target);
  const [shown, setShown] = useState<Forecast | undefined>(last);
  const run = useMutation({
    mutationFn: () =>
      runForecast({
        model_id: model.id,
        target: onSensor ? series : "di",
        tag_id: onSensor ? Number(target) : null,
        threshold_kind: onSensor ? "custom" : kind,
        threshold: onSensor ? Number(limit) : null,
        window_days: windowDays,
        alert_id: alert?.id ?? null,
      }),
    onSuccess: (f) => {
      setShown(f);
      void client.invalidateQueries({ queryKey: ["forecasts"] });
      void client.invalidateQueries({ queryKey: ["alerts"] });
    },
  });
  const f = shown ?? last;
  const chart = f ? forecastChart(f) : null;
  const toPts = (pts: [number, number | null][] | undefined): Pt[] => pts ?? [];
  return (
    <div className="two">
      <Panel
        title="Time-to-threshold forecast"
        actions={
          f ? (
            <Pill tone={f.urgency === "Immediate" || f.urgency === "High" ? "warning" : "neutral"}>
              {f.urgency}
            </Pill>
          ) : undefined
        }
      >
        {!f || !chart ? (
          <Empty>No forecast yet. Choose a target and run one.</Empty>
        ) : (
          <>
            <Chart
              from={chart.from}
              to={chart.to}
              height={260}
              label="Forecast"
              now={Date.parse(f.at)}
              series={[
                { points: toPts(chart.data.actual), cls: "pv1" },
                { points: toPts(chart.data.predicted), cls: "est" },
              ]}
              cone={chart.data.band}
              limits={[{ value: f.threshold, cls: "thr" }]}
            />
            <Legend
              items={[
                {
                  label:
                    f.target === "di"
                      ? "Deviation Index"
                      : f.target === "corrected"
                        ? "At reference load"
                        : f.target === "residual"
                          ? "Residual"
                          : "Measured value",
                },
                { cls: "ds", label: "Projection" },
                { cls: "cx", label: "80 % interval" },
              ]}
            />
            <p className="s13" style={{ marginTop: 8 }}>
              {f.summary} Run {formatDateTime(new Date(f.created_at))}
              {f.alert_id ? `; stored with alert A-${f.alert_id}` : ""}.
            </p>
          </>
        )}
      </Panel>
      <Panel title="Settings">
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div className="fld">
            <label htmlFor="fc-t">Target</label>
            <select
              id="fc-t"
              className="sl"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            >
              <option value="di">Deviation Index</option>
              {sensors.map((s) => (
                <option key={s.tag_id} value={s.tag_id}>
                  {shortTag(s.source_name)} {plainDescription(s.source_name, s.description)}
                </option>
              ))}
            </select>
          </div>
          {onSensor ? (
            <>
              <div className="fld">
                <label htmlFor="fc-s">Trend</label>
                <select
                  id="fc-s"
                  className="sl"
                  value={series}
                  onChange={(e) => setSeries(e.target.value as typeof series)}
                >
                  <option value="corrected">Load-corrected (at the training median load)</option>
                  <option value="actual">Measured value</option>
                  <option value="residual">Residual (measured minus expected)</option>
                </select>
              </div>
              <div className="fld">
                <label htmlFor="fc-l">Limit{sensor?.unit ? ` (${sensor.unit})` : ""}</label>
                <input
                  id="fc-l"
                  className="in num"
                  inputMode="decimal"
                  placeholder="Alarm limit"
                  value={limit}
                  onChange={(e) => setLimit(e.target.value)}
                />
              </div>
            </>
          ) : (
            <div className="fld">
              <label htmlFor="fc-h">Threshold</label>
              <select
                id="fc-h"
                className="sl"
                value={kind}
                onChange={(e) => setKind(e.target.value as "alert" | "warning")}
              >
                <option value="alert">Alert limit</option>
                <option value="warning">Warning limit</option>
              </select>
            </div>
          )}
          <div className="fld">
            <label htmlFor="fc-w">Fit window</label>
            <select
              id="fc-w"
              className="sl"
              value={windowDays}
              onChange={(e) => setWindowDays(Number(e.target.value))}
            >
              {WINDOW_CHOICES.map((w) => (
                <option key={w} value={w}>
                  {w === 1 ? "24 hours" : `${w} days`}
                </option>
              ))}
            </select>
          </div>
          {f && <p className="meta">Method: {methodText(f).replace(/^method: /, "")}.</p>}
          <Problems messages={run.isError ? errorMessages(run.error) : []} />
          <button
            className="btn btn-p"
            type="button"
            disabled={
              run.isPending ||
              !model.in_service ||
              (onSensor && (limit.trim() === "" || !Number.isFinite(Number(limit))))
            }
            onClick={() => run.mutate()}
            style={{ alignSelf: "flex-start" }}
          >
            {run.isPending ? "Running…" : "Run forecast"}
          </button>
        </div>
      </Panel>
    </div>
  );
}

function SensorsTab({ model, sensors }: { model: ModelDetail; sensors: SensorNow[] }) {
  const health = useSensorHealth();
  const client = useQueryClient();
  const [excluding, setExcluding] = useState<SensorNow | null>(null);
  const end = useMutation({
    mutationFn: (exclusionId: number) => endExclusion(exclusionId),
    onSuccess: () =>
      void client.invalidateQueries({
        predicate: (q) => ["sensors", "models"].includes(String(q.queryKey[0])),
      }),
  });
  const version = model.in_service?.version ?? model.latest.version;
  const detail = model.versions.find((v) => v.version === version);
  const required = new Set(detail?.sensors.filter((s) => s.required).map((s) => s.tag_id) ?? []);
  const used = sensors.filter((s) => s.used !== false).length;
  const fmt = (v: number | null) =>
    v === null ? "n/a" : Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(2);
  return (
    <Panel
      title={`Sensors in model ${model.name} v${version}`}
      actions={
        <span className="meta">
          {used} of {sensors.length} used this cycle
        </span>
      }
    >
      <div className="tw">
        <table className="tb">
          <thead>
            <tr>
              <th>Sensor</th>
              <th>Kind</th>
              <th>Unit</th>
              <th className="r">Actual</th>
              <th className="r">Predicted</th>
              <th className="r">z</th>
              <th>Signal status (NE 107)</th>
              <th className="r">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sensors.map((s) => {
              const h = health.data?.find((x) => x.tag_id === s.tag_id);
              const ne = NE107_CODE[s.dq_status];
              const exclusion = h?.exclusion;
              return (
                <tr key={s.tag_id}>
                  <td>
                    <span className="mono">{shortTag(s.source_name)}</span>{" "}
                    {plainDescription(s.source_name, s.description)}
                  </td>
                  <td>
                    <Badge>{required.has(s.tag_id) ? "Required" : "Monitored"}</Badge>
                  </td>
                  <td className="sec">{s.unit}</td>
                  <td className="r num">{fmt(s.actual)}</td>
                  <td className="r num">{fmt(s.predicted)}</td>
                  <td className="r num">
                    {s.z === null ? "n/a" : `${s.z > 0 ? "+" : "−"}${Math.abs(s.z).toFixed(1)}`}
                  </td>
                  <td>
                    <span className="ne">
                      {ne?.code && <span className={`diag ${ne.cls}`}>{ne.code}</span>}
                      {s.dq_status}
                      {exclusion
                        ? `, until ${formatDateTime(new Date(exclusion.expires_at)).slice(0, 6)}`
                        : ""}
                    </span>
                  </td>
                  <td className="r">
                    <Link
                      className="btn btn-g btn-sm"
                      to={`?tab=trends&sensor=${encodeURIComponent(s.source_name)}`}
                    >
                      Chart
                    </Link>{" "}
                    {exclusion ? (
                      <button
                        className="btn btn-s btn-sm"
                        type="button"
                        disabled={end.isPending}
                        onClick={() => end.mutate(exclusion.id)}
                      >
                        End
                      </button>
                    ) : (
                      <button
                        className="btn btn-s btn-sm"
                        type="button"
                        onClick={() => setExcluding(s)}
                      >
                        Exclude
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {sensors.length === 0 && <Empty>The model has not scored a cycle yet.</Empty>}
      </div>
      {excluding && (
        <ExcludeDialog
          tagId={excluding.tag_id}
          name={excluding.source_name}
          coverage={`Coverage drops to ${used - 1} of ${sensors.length}${(used - 1) / sensors.length >= 0.7 ? ", still above the 70 % needed to score." : ", below the 70 % needed to score: the model will stop scoring."}`}
          onClose={() => setExcluding(null)}
        />
      )}
    </Panel>
  );
}
