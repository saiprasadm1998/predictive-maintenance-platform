import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { fetchAllAssets, fetchAssetTags } from "../../api/assets";
import { fetchCoverage, fetchTagTrend } from "../../api/registry";
import { ApiError } from "../../api/client";
import {
  changeVersion,
  fetchJob,
  fetchModels,
  previewTrainingData,
  saveAlertRules,
  saveModel,
  startTraining,
} from "../../api/models";
import type { ModelDetail } from "../../api/types";
import { formatDateTime } from "../../app/format";
import { useAnnounce } from "../../app/liveContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { TrendChart } from "../../components/TrendChart";
import { Skeleton } from "../fleet/FleetPage";
import {
  type BuilderDraft,
  DEFAULT_SENSOR,
  type DraftPeriod,
  MIN_CYCLE_S,
  alertRules,
  applyTemplate,
  clusterSummary,
  fromLocalInput,
  inService,
  newDraft,
  share,
  stepProblems,
  toDefinition,
  toLocalInput,
  trainingTrend,
  validationReport,
  withProposedLimits,
} from "./builderModel";
import { ValidationReportTable } from "./ValidationReport";

export interface StepProps {
  draft: BuilderDraft;
  setDraft: (draft: BuilderDraft) => void;
  model: ModelDetail | undefined;
  go: (step: number) => void;
  saved: (model: ModelDetail, draft: BuilderDraft, step: number) => void;
  done: (version: number) => void;
}

function problemsOf(error: unknown): string[] {
  if (error instanceof ApiError && Array.isArray(error.problem.problems))
    return error.problem.problems.map(String);
  return error instanceof Error ? [error.message] : [];
}

/** Back / Next with the step's problems listed (PDS §6: say what is wrong and where). */
function StepFooter({
  step,
  problems,
  go,
  next,
  nextLabel = "Next →",
  busy = false,
  error,
}: {
  step: number;
  problems: string[];
  go: (step: number) => void;
  next?: () => void;
  nextLabel?: string;
  busy?: boolean;
  error?: unknown;
}) {
  const [tried, setTried] = useState(false);
  const shown = [...(tried ? problems : []), ...problemsOf(error)];
  return (
    <div className="builder-foot">
      {shown.length > 0 && (
        <ul role="alert" className="err builder-problems">
          {shown.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      <div className="builder-buttons">
        {step > 1 && (
          <button type="button" className="btn btn-s" onClick={() => go(step - 1)}>
            ← Back
          </button>
        )}
        {next && (
          <button
            type="button"
            className="btn btn-p"
            disabled={busy}
            onClick={() => {
              setTried(true);
              if (!problems.length) next();
            }}
          >
            {busy ? "Working…" : nextLabel}
          </button>
        )}
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="pnl" aria-label={title}>
      <h2 className="pt">{title}</h2>
      {children}
    </section>
  );
}

// ------------------------------------------------------------------ 1 asset and sensors

export function StepAsset({ draft, setDraft, model, go }: StepProps) {
  const assets = useQuery({
    queryKey: ["assets", "all"],
    queryFn: ({ signal }) => fetchAllAssets(signal),
    enabled: !model,
  });
  const tags = useQuery({
    queryKey: ["tags", draft.asset],
    queryFn: ({ signal }) => fetchAssetTags(draft.asset, signal),
    enabled: !!draft.asset,
  });
  const models = useQuery({
    queryKey: ["models", "list"],
    queryFn: ({ signal }) => fetchModels(signal),
    enabled: !model,
  });
  const taken = !model
    ? models.data?.find((m) => m.asset_code === draft.asset && m.name === draft.name.trim())
    : undefined;
  const chosen = new Map(draft.sensors.map((s) => [s.tag, s]));
  const mapped = (tags.data ?? []).filter((t) => t.role !== null).length;

  function toggle(tag: string, on: boolean) {
    setDraft({
      ...draft,
      sensors: on
        ? [...draft.sensors, { tag, required: false }]
        : draft.sensors.filter((s) => s.tag !== tag),
    });
  }

  function require(tag: string, required: boolean) {
    setDraft({
      ...draft,
      sensors: draft.sensors.map((s) => (s.tag === tag ? { ...s, required } : s)),
    });
  }

  return (
    <Panel title="1. Asset and sensors">
      <div className="builder-fields">
        {model ? (
          <p>
            Asset <strong>{model.asset_code}</strong>, model <strong>{model.name}</strong>
          </p>
        ) : (
          <>
            <label className="fld">
              <span>Asset</span>
              <select
                className="in"
                value={draft.asset}
                onChange={(e) => setDraft({ ...newDraft(e.target.value), name: draft.name })}
              >
                <option value="">Choose…</option>
                {(assets.data ?? [])
                  .filter((a) => a.level === "equipment" || a.level === "component")
                  .map((a) => (
                    <option key={a.id} value={a.code}>
                      {a.code} {a.name}
                    </option>
                  ))}
              </select>
            </label>
            <label className="fld">
              <span>Model name</span>
              <input
                className="in"
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
            </label>
          </>
        )}
        <label className="fld builder-wide">
          <span>Description</span>
          <input
            className="in"
            value={draft.description}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
          />
        </label>
      </div>
      {draft.asset &&
        (tags.isPending ? (
          <Skeleton rows={6} />
        ) : tags.isError ? (
          <p role="alert">The asset's tags could not be loaded: {tags.error.message}</p>
        ) : (
          <>
            <div className="builder-row">
              <p className="sec">
                {draft.sensors.length} of {tags.data.length} tags selected. A required sensor must
                be usable for the model to score.
              </p>
              <button
                type="button"
                className="btn btn-s btn-sm"
                disabled={!mapped}
                onClick={() => setDraft(applyTemplate(draft, tags.data))}
              >
                Apply asset-type template ({mapped} tags)
              </button>
            </div>
            <table className="tb">
              <caption className="sr">Tags of {draft.asset}</caption>
              <thead>
                <tr>
                  <th scope="col">Use</th>
                  <th scope="col">Tag</th>
                  <th scope="col">Description</th>
                  <th scope="col">Unit</th>
                  <th scope="col">Role</th>
                  <th scope="col">Required</th>
                </tr>
              </thead>
              <tbody>
                {tags.data.map((t) => {
                  const pick = chosen.get(t.source_name);
                  return (
                    <tr key={t.id}>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`Use ${t.source_name}`}
                          checked={!!pick}
                          onChange={(e) => toggle(t.source_name, e.target.checked)}
                        />
                      </td>
                      <td className="mono">{t.source_name}</td>
                      <td>{t.description}</td>
                      <td>{t.unit}</td>
                      <td>{t.role ?? <span className="sec">—</span>}</td>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`${t.source_name} required`}
                          checked={!!pick?.required}
                          disabled={!pick}
                          onChange={(e) => require(t.source_name, e.target.checked)}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </>
        ))}
      {taken && (
        <p role="alert">
          {taken.asset_code} already has a model named “{taken.name}”. Choose another name, or{" "}
          <Link to={`/models/${taken.id}/build/1`}>build a new version of it</Link>.
        </p>
      )}
      <StepFooter
        step={1}
        problems={[
          ...stepProblems(1, draft),
          ...(taken ? [`${taken.asset_code} already has a model named “${taken.name}”`] : []),
        ]}
        go={go}
        next={() => go(2)}
      />
    </Panel>
  );
}

// ------------------------------------------------------------------ 2 periods

const DAY_MS = 86_400_000;

function PeriodFields({
  label,
  value,
  onChange,
}: {
  label: string;
  value: DraftPeriod;
  onChange: (value: DraftPeriod) => void;
}) {
  return (
    <div className="fg" style={{ flex: 1 }} role="group" aria-label={label}>
      <label className="fld">
        <span>{label}: from</span>
        <input
          className="in"
          type="datetime-local"
          value={value.start}
          onChange={(e) => onChange({ ...value, start: e.target.value })}
        />
      </label>
      <label className="fld">
        <span>to</span>
        <input
          className="in"
          type="datetime-local"
          value={value.end}
          onChange={(e) => onChange({ ...value, end: e.target.value })}
        />
      </label>
    </div>
  );
}

function PeriodChart({
  draft,
  tagId,
  from,
  to,
}: {
  draft: BuilderDraft;
  tagId: number;
  from: number;
  to: number;
}) {
  const trend = useQuery({
    queryKey: ["tags", tagId, "trend", from, to],
    queryFn: ({ signal }) =>
      fetchTagTrend(tagId, new Date(from).toISOString(), new Date(to).toISOString(), 400, signal),
  });
  const W = 820;
  const H = 230;
  const L = 40;
  const R = 10;
  const T = 10;
  const B = 40;
  const pts = (trend.data?.ts ?? []).map((t, i) => [Date.parse(t), trend.data!.mean[i]!] as const);
  const vals = pts.map(([, v]) => v);
  const lo = vals.length ? Math.min(...vals) : 0;
  const hi = vals.length ? Math.max(...vals) : 1;
  const pad = (hi - lo) * 0.05 || 1;
  const x = (t: number) => L + ((t - from) / Math.max(1, to - from)) * (W - L - R);
  const y = (v: number) => T + (1 - (v - (lo - pad)) / (hi - lo + 2 * pad)) * (H - T - B);
  const span = (p: DraftPeriod) => {
    const s = fromLocalInput(p.start).getTime();
    const e = fromLocalInput(p.end).getTime();
    return Number.isFinite(s) && Number.isFinite(e) && e > s
      ? { x: x(Math.max(from, s)), w: Math.max(0, x(Math.min(to, e)) - x(Math.max(from, s))) }
      : null;
  };
  let d = "";
  let gapStart = 0;
  pts.forEach(([t, v], i) => {
    const jump = i > 0 && t - pts[i - 1]![0] > 3 * ((to - from) / 400 + 3_600_000);
    if (jump) gapStart += 1;
    d += `${i === 0 || jump ? "M" : "L"}${x(t).toFixed(1)},${y(v).toFixed(1)}`;
  });
  const tick = (t: number) =>
    new Date(t).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  const v = span(draft.validation);
  return (
    <>
      <svg
        className="chart"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="The sensor over the stored history, with the training and validation periods marked"
      >
        {draft.training.map((p, i) => {
          const r = span(p);
          return r ? (
            <rect
              key={i}
              x={r.x}
              y={T}
              width={r.w}
              height={H - T - B}
              style={{ fill: "var(--traverse-surface-selected)" }}
            />
          ) : null;
        })}
        {v && (
          <rect
            x={v.x}
            y={T}
            width={v.w}
            height={H - T - B}
            style={{ fill: "var(--traverse-surface-raised)" }}
          />
        )}
        <line
          x1={L}
          x2={W - R}
          y1={H - B}
          y2={H - B}
          style={{ stroke: "var(--traverse-border-strong)" }}
        />
        {vals.length > 0 && (
          <>
            <text
              x={L - 6}
              y={T + 10}
              textAnchor="end"
              style={{ fontSize: 11, fill: "var(--traverse-text-secondary)" }}
            >
              {hi.toFixed(0)}
            </text>
            <text
              x={L - 6}
              y={H - B}
              textAnchor="end"
              style={{ fontSize: 11, fill: "var(--traverse-text-secondary)" }}
            >
              {lo.toFixed(0)}
            </text>
          </>
        )}
        <path
          d={d}
          style={{ fill: "none", stroke: "var(--traverse-chart-series-1)", strokeWidth: 1.5 }}
        />
        {[from, from + (to - from) / 3, from + (2 * (to - from)) / 3, to].map((t, i) => (
          <text
            key={i}
            x={x(t)}
            y={H - B + 18}
            textAnchor={i === 0 ? "start" : i === 3 ? "end" : "middle"}
            style={{ fontSize: 11, fill: "var(--traverse-text-secondary)" }}
          >
            {tick(t)}
          </text>
        ))}
      </svg>
      <div
        className="lg"
        style={{ display: "flex", gap: 16, fontSize: 12, color: "var(--traverse-text-secondary)" }}
      >
        <span>
          <i
            style={{
              display: "inline-block",
              width: 12,
              height: 10,
              marginRight: 6,
              background: "var(--traverse-surface-selected)",
            }}
          />
          Training
        </span>
        <span>
          <i
            style={{
              display: "inline-block",
              width: 12,
              height: 10,
              marginRight: 6,
              background: "var(--traverse-surface-raised)",
              border: "1px solid var(--traverse-border-subtle)",
            }}
          />
          Validation
        </span>
        {gapStart > 0 && <span>Gaps in the line: no data stored</span>}
      </div>
    </>
  );
}

export function StepPeriods({ draft, setDraft, go }: StepProps) {
  const tags = useQuery({
    queryKey: ["tags", "asset", draft.asset],
    queryFn: ({ signal }) => fetchAssetTags(draft.asset, signal),
    enabled: !!draft.asset,
  });
  const coverage = useQuery({
    queryKey: ["tags", "coverage"],
    queryFn: ({ signal }) => fetchCoverage(signal),
  });
  const byName = new Map((tags.data ?? []).map((t) => [t.source_name, t]));
  const cov = new Map((coverage.data ?? []).map((c) => [c.tag_id, c]));
  const used = draft.sensors.map((s) => ({ ...s, tag: byName.get(s.tag) })).filter((s) => s.tag);
  const lead = used.find((s) => s.required) ?? used[0];
  const spans = used.map((s) => cov.get(s.tag!.id)).filter(Boolean) as {
    first_ts: string;
    last_ts: string;
  }[];
  const [now] = useState(() => Date.now());
  const from = spans.length
    ? Math.min(...spans.map((c) => Date.parse(c.first_ts)))
    : now - 180 * DAY_MS;
  const to = spans.length ? Math.max(...spans.map((c) => Date.parse(c.last_ts))) : now;
  const cycles = (p: DraftPeriod) => {
    const ms = fromLocalInput(p.end).getTime() - fromLocalInput(p.start).getTime();
    return Number.isFinite(ms) && ms > 0 ? Math.floor(ms / 1000 / Math.max(1, draft.cycleS)) : 0;
  };
  const trainCycles = draft.training.reduce((a, p) => a + cycles(p), 0);
  const day = (iso: string) =>
    new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  const covers = (c: { first_ts: string; last_ts: string } | undefined) => {
    if (!c) return false;
    const need = [...draft.training, draft.validation].flatMap((p) => [
      fromLocalInput(p.start).getTime(),
      fromLocalInput(p.end).getTime(),
    ]);
    return need.every(
      (t) =>
        !Number.isFinite(t) ||
        (t >= Date.parse(c.first_ts) - 3_600_000 && t <= Date.parse(c.last_ts) + 3_600_000),
    );
  };
  const setTraining = (i: number, value: DraftPeriod) =>
    setDraft({ ...draft, training: draft.training.map((q, j) => (j === i ? value : q)) });
  return (
    <>
      <div className="two">
        <section className="pnl" aria-label="2. Training period">
          <div className="pnlh">
            <span className="pt">2. Training period</span>
            <span className="meta">
              {lead
                ? `${lead.tag!.description || lead.tag!.source_name}, stored history`
                : "Choose sensors first"}
            </span>
          </div>
          {lead && <PeriodChart draft={draft} tagId={lead.tag!.id} from={from} to={to} />}
          {draft.training.map((p, i) => (
            <div key={i} className="fg f4" style={{ marginTop: 12, alignItems: "end" }}>
              <div className="fld">
                <label htmlFor={`tp-s-${i}`}>
                  Training from{draft.training.length > 1 ? ` (${i + 1})` : ""}
                </label>
                <input
                  id={`tp-s-${i}`}
                  className="in"
                  type="datetime-local"
                  value={p.start}
                  onChange={(e) => setTraining(i, { ...p, start: e.target.value })}
                />
              </div>
              <div className="fld">
                <label htmlFor={`tp-e-${i}`}>Training to</label>
                <input
                  id={`tp-e-${i}`}
                  className="in"
                  type="datetime-local"
                  value={p.end}
                  onChange={(e) => setTraining(i, { ...p, end: e.target.value })}
                />
              </div>
              {i === 0 ? (
                <>
                  <div className="fld">
                    <label htmlFor="vp-s">Validation from</label>
                    <input
                      id="vp-s"
                      className="in"
                      type="datetime-local"
                      value={draft.validation.start}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          validation: { ...draft.validation, start: e.target.value },
                        })
                      }
                    />
                  </div>
                  <div className="fld">
                    <label htmlFor="vp-e">Validation to</label>
                    <input
                      id="vp-e"
                      className="in"
                      type="datetime-local"
                      value={draft.validation.end}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          validation: { ...draft.validation, end: e.target.value },
                        })
                      }
                    />
                  </div>
                </>
              ) : (
                <button
                  type="button"
                  className="btn btn-g btn-sm"
                  onClick={() =>
                    setDraft({ ...draft, training: draft.training.filter((_, j) => j !== i) })
                  }
                >
                  Remove period {i + 1}
                </button>
              )}
            </div>
          ))}
          <div style={{ display: "flex", gap: 16, alignItems: "end", marginTop: 8 }}>
            <button
              type="button"
              className="btn btn-g btn-sm"
              onClick={() =>
                setDraft({ ...draft, training: [...draft.training, { start: "", end: "" }] })
              }
            >
              Add another training period
            </button>
            <div className="fld" style={{ width: 160 }}>
              <label htmlFor="tp-c">Scoring cycle (seconds)</label>
              <input
                id="tp-c"
                className="in"
                type="number"
                min={MIN_CYCLE_S}
                step={1}
                value={draft.cycleS}
                onChange={(e) => setDraft({ ...draft, cycleS: Number(e.target.value) })}
              />
            </div>
          </div>
        </section>
        <section className="pnl" aria-label="History available">
          <div className="pnlh">
            <span className="pt">History available</span>
            <Link className="btn btn-s btn-sm" to="/setup/history/upload">
              Upload more
            </Link>
          </div>
          <p className="sec s13" style={{ marginBottom: 8 }}>
            Training uses history uploaded under Historical data. Each sensor needs it for the whole
            period.
          </p>
          <div className="fill">
            {used.map((s) => {
              const c = cov.get(s.tag!.id);
              const ok = covers(c);
              return (
                <div
                  key={s.tag!.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    minHeight: 34,
                    borderBottom: "1px solid var(--traverse-border-subtle)",
                  }}
                >
                  <span className="mono grow">{s.tag!.source_name}</span>
                  <span className="num sec s13">
                    {c ? `${day(c.first_ts)} to ${day(c.last_ts)}` : "No history"}
                  </span>
                  <span className={`pill${ok ? "" : " p-warning"}`}>
                    <span className="d" />
                    {ok ? "Covers" : "Short"}
                  </span>
                </div>
              );
            })}
          </div>
          <p className="s13" style={{ marginTop: 8 }}>
            <b>{trainCycles.toLocaleString()}</b> training cycles,{" "}
            <b>{cycles(draft.validation).toLocaleString()}</b> validation cycles ({draft.cycleS} s)
          </p>
        </section>
      </div>
      <StepFooter step={2} problems={stepProblems(2, draft)} go={go} next={() => go(3)} />
    </>
  );
}

// ------------------------------------------------------------------ 3 cleanse

export function StepCleanse({ draft, setDraft, model, go, saved }: StepProps) {
  const client = useQueryClient();
  const [applied, setApplied] = useState(draft.modeFilters);
  const [sensor, setSensor] = useState<string | null>(null);
  const tags = useQuery({
    queryKey: ["tags", draft.asset],
    queryFn: ({ signal }) => fetchAssetTags(draft.asset, signal),
  });
  const definition = useMemo(
    () => toDefinition({ ...draft, modeFilters: applied }, false),
    [draft, applied],
  );
  const preview = useQuery({
    queryKey: ["training-data", JSON.stringify(definition)],
    queryFn: ({ signal }) => previewTrainingData(definition, 600, signal),
    staleTime: Infinity,
    retry: false,
  });
  const dirty = JSON.stringify(applied) !== JSON.stringify(draft.modeFilters);
  const train = useMutation({
    mutationFn: async () => {
      const withRules = !inService(model);
      const savedModel = await saveModel(toDefinition(draft, withRules));
      const started = await startTraining(savedModel.id);
      return { savedModel, jobId: started.job_id };
    },
    onSuccess: ({ savedModel, jobId }) => {
      void client.invalidateQueries({ queryKey: ["models"] });
      saved(savedModel, { ...draft, jobId }, 4);
    },
  });

  const data = preview.data;
  const removed = data ? data.cycles - data.retained : 0;
  const clusters = clusterSummary(data?.clusters ?? []);
  const exclusions = draft.exclusions ?? [];
  function setExclusions(next: DraftPeriod[]) {
    setDraft({ ...draft, exclusions: next });
  }
  function exclude(from: number, to: number) {
    setExclusions([
      ...exclusions,
      { start: toLocalInput(new Date(from)), end: toLocalInput(new Date(to)) },
    ]);
  }
  const flagged = data?.sensors.filter((s) => s.flagged) ?? [];
  const problems = [
    ...stepProblems(3, draft),
    ...(dirty ? ["Apply the operating-mode filters to see their effect first"] : []),
    ...(data?.blocked ? [data.blocked] : []),
    ...(preview.isError ? problemsOf(preview.error) : []),
  ];

  const shown = data && sensor && sensor in data.values ? sensor : data?.sensors[0]?.source_name;
  const trend = useMemo(() => (data && shown ? trainingTrend(data, shown) : null), [data, shown]);

  return (
    <Panel title="3. Cleanse data">
      <fieldset className="builder-filters">
        <legend>Operating-mode filters</legend>
        <p className="sec s13">
          Only cycles that satisfy every filter are used, for example{" "}
          <code>K101.II1001.PV &gt; 120</code> (motor running). Name tags by their source name.
        </p>
        {draft.modeFilters.map((f, i) => (
          <div key={i} className="builder-row">
            <label className="fld builder-wide">
              <span>Filter {i + 1}</span>
              <input
                className="in mono"
                value={f}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    modeFilters: draft.modeFilters.map((g, j) => (j === i ? e.target.value : g)),
                  })
                }
              />
            </label>
            <button
              type="button"
              className="btn btn-s btn-sm"
              onClick={() =>
                setDraft({ ...draft, modeFilters: draft.modeFilters.filter((_, j) => j !== i) })
              }
            >
              Remove filter {i + 1}
            </button>
          </div>
        ))}
        <div className="builder-row">
          <label className="fld fld-inline">
            <span>Add a filter on</span>
            <select
              className="in"
              value=""
              onChange={(e) =>
                e.target.value &&
                setDraft({ ...draft, modeFilters: [...draft.modeFilters, `${e.target.value} > 0`] })
              }
            >
              <option value="">Choose a tag…</option>
              {(tags.data ?? []).map((t) => (
                <option key={t.id} value={t.source_name}>
                  {t.source_name} {t.description}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn btn-s btn-sm"
            disabled={!dirty}
            onClick={() => setApplied(draft.modeFilters)}
          >
            Apply filters
          </button>
        </div>
      </fieldset>

      {preview.isPending ? (
        <Skeleton rows={6} />
      ) : !data ? null : (
        <div className="builder-cleanse">
          <div>
            <label className="fld fld-inline">
              <span>Training data of</span>
              <select className="in" value={shown} onChange={(e) => setSensor(e.target.value)}>
                {data.sensors.map((s) => (
                  <option key={s.source_name} value={s.source_name}>
                    {s.source_name}
                  </option>
                ))}
              </select>
            </label>
            {trend && (
              <TrendChart
                title={`Training data · ${shown} · shaded = excluded · drag across the trend to exclude a period`}
                group="builder"
                data={{ actual: trend.points, excluded: trend.excluded }}
                settings={{
                  from: trend.from,
                  to: trend.to,
                  unit: tags.data?.find((t) => t.source_name === shown)?.unit ?? "",
                  actualName: shown,
                  selecting: true,
                }}
                onSelect={exclude}
              />
            )}
            <table className="tb">
              <caption>Cleansing rules applied</caption>
              <thead>
                <tr>
                  <th scope="col">Rule</th>
                  <th scope="col">Definition</th>
                  <th scope="col" className="num">
                    Effect
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">Data quality and coverage</th>
                  <td>
                    Bad, stale and flatline samples; at least 70 % of sensors and every required
                    sensor usable
                  </td>
                  <td className="num">{share(data.quality_removed, data.cycles)} removed</td>
                </tr>
                <tr>
                  <th scope="row">Operating mode</th>
                  <td className="mono">{applied.length ? applied.join(" and ") : "None"}</td>
                  <td className="num">{share(data.mode_removed, data.cycles)} removed</td>
                </tr>
                <tr>
                  <th scope="row">Outliers</th>
                  <td>Any sensor more than 4 robust standard deviations from its median</td>
                  <td className="num">{share(data.outlier_removed, data.cycles)} removed</td>
                </tr>
                <tr>
                  <th scope="row">Multivariate outliers</th>
                  <td>Further from every operating cluster than 99.9 % of the data</td>
                  <td className="num">{share(data.multivariate_removed, data.cycles)} removed</td>
                </tr>
                <tr>
                  <th scope="row">Excluded on the trend</th>
                  <td>
                    {exclusions.length
                      ? `${exclusions.length} period${exclusions.length === 1 ? "" : "s"}`
                      : "None"}
                  </td>
                  <td className="num">{share(data.excluded_removed, data.cycles)} removed</td>
                </tr>
              </tbody>
            </table>
            <fieldset className="builder-filters">
              <legend>Excluded periods</legend>
              {exclusions.length === 0 && (
                <p className="sec s13">
                  Drag across the trend over a period that was not normal operation (a trip, a test,
                  a known fault), or add one by its times.
                </p>
              )}
              {exclusions.map((p, i) => (
                <div key={i} className="builder-row">
                  <PeriodFields
                    label={`Excluded period ${i + 1}`}
                    value={p}
                    onChange={(value) =>
                      setExclusions(exclusions.map((q, j) => (j === i ? value : q)))
                    }
                  />
                  <button
                    type="button"
                    className="btn btn-s btn-sm"
                    onClick={() => setExclusions(exclusions.filter((_, j) => j !== i))}
                  >
                    Remove excluded period {i + 1}
                  </button>
                </div>
              ))}
              <button
                type="button"
                className="btn btn-s btn-sm"
                onClick={() => {
                  const first = draft.training[0];
                  if (!first) return;
                  const start = fromLocalInput(first.start).getTime();
                  exclude(start, start + 3_600_000);
                }}
              >
                Add an excluded period
              </button>
            </fieldset>
          </div>
          <table className="tb">
            <caption>Training data summary</caption>
            <tbody>
              <tr>
                <th scope="row">Periods</th>
                <td>
                  {draft.training
                    .map(
                      (p) =>
                        `${formatDateTime(fromLocalInput(p.start))} – ${formatDateTime(fromLocalInput(p.end))}`,
                    )
                    .join("; ")}
                </td>
              </tr>
              <tr>
                <th scope="row">Cycles ({data.cycle_s} s)</th>
                <td className="num">{data.cycles.toLocaleString("en-GB")}</td>
              </tr>
              <tr>
                <th scope="row">Retained</th>
                <td className="num">
                  {share(data.retained, data.cycles)} ({data.retained.toLocaleString("en-GB")};{" "}
                  {removed.toLocaleString("en-GB")} removed)
                </td>
              </tr>
              <tr>
                <th scope="row">Sensors</th>
                <td>
                  {data.sensors.length}
                  {flagged.length > 0 && (
                    <>
                      {" "}
                      ({flagged.length} flagged:{" "}
                      {flagged
                        .map((s) => `${s.source_name} usable ${share(s.usable_share, 1)}`)
                        .join(", ")}
                      )
                    </>
                  )}
                </td>
              </tr>
              <tr>
                <th scope="row">Operating clusters</th>
                <td>
                  {clusters.text}
                  {clusters.small.length > 0 && (
                    <div className="form-warning">
                      ⚠ Cluster{clusters.small.length === 1 ? "" : "s"} {clusters.small.join(", ")}{" "}
                      hold
                      {clusters.small.length === 1 ? "s" : ""} under 5 % of the data: that operating
                      state may be learnt poorly. Extend the training period to include more of it.
                    </div>
                  )}
                </td>
              </tr>
              <tr>
                <th scope="row">Minimum data</th>
                <td>
                  {data.blocked ? (
                    <span className="err">✖ {data.blocked}</span>
                  ) : (
                    "✔ passes (2,000 cycles and 50 % of the period)"
                  )}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
      <StepFooter
        step={3}
        problems={problems}
        go={go}
        next={() => train.mutate()}
        nextLabel="Train model →"
        busy={train.isPending}
        error={train.error}
      />
    </Panel>
  );
}

// ------------------------------------------------------------------ 4 train and validate

function metric(metrics: Record<string, unknown> | null | undefined, key: string): number {
  return Number(metrics?.[key] ?? 0);
}

export function StepTrain({ draft, setDraft, model, go, saved }: StepProps) {
  const client = useQueryClient();
  const latest = model?.versions[model.versions.length - 1];
  const running = latest?.status === "Training";
  const job = useQuery({
    queryKey: ["jobs", draft.jobId],
    queryFn: ({ signal }) => fetchJob(draft.jobId!, signal),
    enabled: draft.jobId !== null && running,
    // The live stream refreshes it at once; polling covers a stream that is down.
    refetchInterval: (q) =>
      q.state.data && ["succeeded", "failed"].includes(q.state.data.status) ? false : 3000,
  });
  const retrain = useMutation({
    mutationFn: async () => {
      const savedModel = await saveModel(toDefinition(draft, !inService(model)));
      const started = await startTraining(savedModel.id);
      return { savedModel, jobId: started.job_id };
    },
    onSuccess: ({ savedModel, jobId }) => {
      void client.invalidateQueries({ queryKey: ["models"] });
      saved(savedModel, { ...draft, jobId }, 4);
    },
  });
  if (!latest) return null;
  const metrics = latest.metrics;
  const report = validationReport(metrics);
  const percent = job.data?.progress ?? null;

  return (
    <Panel title="4. Train and validate">
      <p>
        Version {latest.version} <strong>{latest.status}</strong>
      </p>
      {latest.status === "Draft" && (
        <p>
          The draft is saved but not training.{" "}
          <button type="button" className="btn btn-s btn-sm" onClick={() => retrain.mutate()}>
            Start training
          </button>
        </p>
      )}
      {running && (
        <div className="builder-progress">
          <label className="fld">
            <span>
              Training{percent !== null ? `: ${Math.round(percent)} %` : "…"}
              {job.data?.status === "queued" ? " (waiting for the worker)" : ""}
            </span>
            <progress max={100} value={percent ?? undefined} />
          </label>
          <p className="sec s13">
            Training runs in the background. You can leave this page; this step shows the result
            when you come back.
          </p>
        </div>
      )}
      {latest.status === "Failed" && (
        <div role="alert">
          <p className="err">Training failed: {latest.error}</p>
          <p>
            Change the definition in the earlier steps, or{" "}
            <button
              type="button"
              className="btn btn-s btn-sm"
              disabled={retrain.isPending}
              onClick={() => retrain.mutate()}
            >
              train again
            </button>
          </p>
        </div>
      )}
      {latest.status === "Validated" && (
        <div className="half">
          <table className="tb" style={{ alignSelf: "start" }}>
            <caption className="cap" style={{ textAlign: "left", paddingBottom: 6 }}>
              Training and validation
            </caption>
            <tbody>
              <tr>
                <th scope="row">Training cycles retained</th>
                <td className="num">
                  {metric(metrics, "training_retained").toLocaleString("en-GB")} of{" "}
                  {metric(metrics, "training_cycles").toLocaleString("en-GB")} (
                  {share(metric(metrics, "training_retained"), metric(metrics, "training_cycles"))})
                </td>
              </tr>
              <tr>
                <th scope="row">Validation cycles retained</th>
                <td className="num">
                  {metric(metrics, "validation_retained").toLocaleString("en-GB")} of{" "}
                  {metric(metrics, "validation_cycles").toLocaleString("en-GB")}
                </td>
              </tr>
              <tr>
                <th scope="row">Sensors at their scale floor</th>
                <td>
                  {((metrics?.floored_sensors as string[] | undefined) ?? []).join(", ") || "None"}
                </td>
              </tr>
              <tr>
                <th scope="row">Details</th>
                <td>
                  <Link to={`/models/${model.id}/versions/${latest.version}`}>
                    Version {latest.version} in full
                  </Link>
                </td>
              </tr>
            </tbody>
          </table>
          {report && <ValidationReportTable report={report} />}
        </div>
      )}
      {retrain.error !== null && (
        <ul role="alert" className="err">
          {problemsOf(retrain.error).map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      <StepFooter
        step={4}
        problems={latest.status === "Validated" ? [] : ["Wait until the version is Validated"]}
        go={go}
        next={() => {
          setDraft(withProposedLimits({ ...draft, jobId: null }, latest.id, report));
          go(5);
        }}
      />
    </Panel>
  );
}

// ------------------------------------------------------------------ 5 alert limits

function NumberCell({
  label,
  value,
  onChange,
  step = 0.5,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  step?: number;
}) {
  return (
    <input
      className="in builder-number"
      type="number"
      aria-label={label}
      step={step}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
    />
  );
}

/** How the Deviation Index was spread over the validation period, against the limits. */
function DiHistogram({
  histogram,
  warning,
  alert,
  perWeek,
}: {
  histogram: { top: number; counts: number[] } | null;
  warning: number;
  alert: number;
  perWeek: number | null;
}) {
  const counts = histogram?.counts ?? [];
  const total = counts.reduce((n, c) => n + c, 0);
  const top = histogram?.top ?? Math.max(alert * 1.3, 10);
  const bins = Math.max(1, counts.length);
  const peak = Math.max(1, ...counts);
  const L = 20;
  const W = 390;
  const base = 190;
  const axis = Math.max(top, alert * 1.15, warning * 1.15);
  const x = (v: number) => L + (Math.min(v, axis) / axis) * (W - L);
  const bw = (x(top) - L) / bins;
  const label = (v: number) =>
    x(v) > W - 40
      ? { x: x(v) - 4, anchor: "end" as const }
      : { x: x(v) + 4, anchor: "start" as const };
  return (
    <section className="pnl" aria-label="Deviation on the validation period">
      <div className="pnlh">
        <span className="pt">Deviation on the validation period</span>
        {perWeek !== null && (
          <span className={`pill${perWeek > 1 ? " p-warning" : ""}`}>
            <span className="d" />
            {perWeek.toLocaleString("en-GB")} false alerts a week (proposed limits)
          </span>
        )}
      </div>
      {!histogram ? (
        <p className="sec s13">Retrain this version to see the distribution.</p>
      ) : (
        <svg
          className="chart"
          viewBox="0 0 400 230"
          role="img"
          aria-label="Distribution of the Deviation Index with the warning and alert limits"
        >
          {counts.map((c, i) => (
            <rect
              key={i}
              x={L + i * bw + 1}
              y={base - (c / peak) * 170}
              width={bw - 2}
              height={(c / peak) * 170}
              style={{ fill: "var(--traverse-chart-series-1)", opacity: 0.8 }}
            />
          ))}
          <line
            x1={L}
            x2={W}
            y1={base}
            y2={base}
            style={{ stroke: "var(--traverse-border-strong)" }}
          />
          <line
            x1={x(warning)}
            x2={x(warning)}
            y1={10}
            y2={base}
            style={{ stroke: "var(--traverse-status-warning-fg)", strokeDasharray: "4 3" }}
          />
          <text
            x={label(warning).x}
            textAnchor={label(warning).anchor}
            y={22}
            style={{ fontSize: 11, fill: "var(--traverse-status-warning-fg)" }}
          >
            W {warning}
          </text>
          <line
            x1={x(alert)}
            x2={x(alert)}
            y1={10}
            y2={base}
            style={{ stroke: "var(--traverse-status-danger-fg)", strokeDasharray: "4 3" }}
          />
          <text
            x={label(alert).x}
            textAnchor={label(alert).anchor}
            y={40}
            style={{ fontSize: 11, fill: "var(--traverse-status-danger-fg)" }}
          >
            A {alert}
          </text>
          <text x={L} y={210} style={{ fontSize: 11, fill: "var(--traverse-text-secondary)" }}>
            0 %
          </text>
          <text
            x={W}
            y={210}
            textAnchor="end"
            style={{ fontSize: 11, fill: "var(--traverse-text-secondary)" }}
          >
            {axis.toFixed(0)} %
          </text>
        </svg>
      )}
      <p className="s13" style={{ marginTop: 8 }}>
        {total.toLocaleString()} validation cycles. Cycles to the right of a line would count toward
        that alert.
      </p>
    </section>
  );
}

export function StepLimits({ draft, setDraft, model, go }: StepProps) {
  const client = useQueryClient();
  const live = inService(model);
  const save = useMutation({
    mutationFn: () => saveAlertRules(model!.id, alertRules(draft)),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["models"] });
      go(6);
    },
  });
  const rules = new Map(draft.sensorRules.map((r) => [r.tag, r]));
  const di = draft.di;
  const validated = model?.versions.findLast((v) => v.status === "Validated");
  const report = validationReport(validated?.metrics);

  function setRule(tag: string, change: Partial<{ warning: number; alert: number }> | null) {
    const others = draft.sensorRules.filter((r) => r.tag !== tag);
    const current = rules.get(tag) ?? { tag, ...DEFAULT_SENSOR };
    setDraft({
      ...draft,
      sensorRules: change === null ? others : [...others, { ...current, ...change }],
    });
  }

  return (
    <>
      <div className="two">
        <Panel title="5. Alert limits">
          <p className="sec">
            {report
              ? `The limits start at those proposed from the validation period (DI warning 1.2 × P99 = ${report.proposed.di_warning} %, alert 1.5 × P99.9, at least 10 % = ${report.proposed.di_alert} %; sensor |z| 3 and 5), with about ${report.alerts_per_week.toLocaleString("en-GB")} false alerts a week expected. You can change them.`
              : "The limits start at the defaults (Deviation Index warning 15 % and alert 25 %; sensor |z| 3 and 5)."}
            {live &&
              ` Version ${live.version} keeps its current limits until this version is deployed.`}
          </p>
          {report?.warning && (
            <p className="form-warning" role="status">
              ⚠ {report.warning}
            </p>
          )}
          {report && di.warning < report.proposed.di_warning && (
            <p className="form-warning" role="status">
              ⚠ The DI warning is below the proposed {report.proposed.di_warning} %: expect more
              false alerts than estimated.
            </p>
          )}
          <span className="cap">Deviation Index rule</span>
          <div className="fg f4" style={{ margin: "6px 0 16px" }}>
            <div className="fld">
              <span aria-hidden="true">Warning (%)</span>
              <NumberCell
                label="DI warning (%)"
                value={di.warning}
                onChange={(warning) => setDraft({ ...draft, di: { ...di, warning } })}
              />
            </div>
            <div className="fld">
              <span aria-hidden="true">Alert (%)</span>
              <NumberCell
                label="DI alert (%)"
                value={di.alert}
                onChange={(alert) => setDraft({ ...draft, di: { ...di, alert } })}
              />
            </div>
            <div className="fld">
              <span aria-hidden="true">Persistence: n cycles</span>
              <NumberCell
                label="Persistence n"
                step={1}
                value={di.n}
                onChange={(n) => setDraft({ ...draft, di: { ...di, n } })}
              />
            </div>
            <div className="fld">
              <span aria-hidden="true">of the last m</span>
              <NumberCell
                label="Persistence m"
                step={1}
                value={di.m}
                onChange={(m) => setDraft({ ...draft, di: { ...di, m } })}
              />
            </div>
          </div>
          <table className="tb">
            <caption>Sensor |z| rules</caption>
            <thead>
              <tr>
                <th scope="col">Rule</th>
                <th scope="col">Sensor</th>
                <th scope="col">Warning |z|</th>
                <th scope="col">Alert |z|</th>
              </tr>
            </thead>
            <tbody>
              {draft.sensors.map((s) => {
                const rule = rules.get(s.tag);
                return (
                  <tr key={s.tag}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`|z| rule on ${s.tag}`}
                        checked={!!rule}
                        onChange={(e) => setRule(s.tag, e.target.checked ? {} : null)}
                      />
                    </td>
                    <td className="mono">
                      {s.tag}
                      {s.required && <span className="sec"> · required</span>}
                    </td>
                    <td>
                      {rule && (
                        <NumberCell
                          label={`${s.tag} warning |z|`}
                          value={rule.warning}
                          onChange={(warning) => setRule(s.tag, { warning })}
                        />
                      )}
                    </td>
                    <td>
                      {rule && (
                        <NumberCell
                          label={`${s.tag} alert |z|`}
                          value={rule.alert}
                          onChange={(alert) => setRule(s.tag, { alert })}
                        />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Panel>
        {model && validated && (
          <DiHistogram
            histogram={report?.histogram ?? null}
            warning={di.warning}
            alert={di.alert}
            perWeek={report?.alerts_per_week ?? null}
          />
        )}
      </div>
      <StepFooter
        step={5}
        problems={stepProblems(5, draft)}
        go={go}
        next={() => (live ? go(6) : save.mutate())}
        busy={save.isPending}
        error={save.error}
      />
    </>
  );
}

// ------------------------------------------------------------------ 6 deploy

export function StepDeploy({ draft, model, go, done }: StepProps) {
  const client = useQueryClient();
  const announce = useAnnounce();
  const [confirming, setConfirming] = useState(false);
  const latest = model?.versions[model.versions.length - 1];
  const live = inService(model);
  if (!model || !latest) return null;
  const metrics = latest.metrics;

  async function deploy() {
    if (live) await saveAlertRules(model!.id, alertRules(draft));
    await changeVersion(latest!.id, "deploy");
    announce(`${model!.asset_code} / ${model!.name} version ${latest!.version} deployed`);
    await client.invalidateQueries({
      predicate: (q) =>
        ["models", "assets", "fleet", "alerts", "scores"].includes(String(q.queryKey[0])),
    });
    done(latest!.version);
  }

  const rules = alertRules(draft);
  return (
    <Panel title="6. Deploy">
      <table className="tb">
        <caption>
          {model.asset_code} / {model.name} version {latest.version}
        </caption>
        <tbody>
          <tr>
            <th scope="row">Status</th>
            <td>
              <strong>{latest.status}</strong>
            </td>
          </tr>
          <tr>
            <th scope="row">Sensors</th>
            <td>
              {draft.sensors.length} ({draft.sensors.filter((s) => s.required).length} required)
            </td>
          </tr>
          <tr>
            <th scope="row">Training retained</th>
            <td>
              {share(metric(metrics, "training_retained"), metric(metrics, "training_cycles"))}
            </td>
          </tr>
          <tr>
            <th scope="row">Operating mode</th>
            <td className="mono">{draft.modeFilters.join(" and ") || "None"}</td>
          </tr>
          <tr>
            <th scope="row">DI limits</th>
            <td>
              warning {rules.di.warning} %, alert {rules.di.alert} %, {rules.di.persistence_n} of{" "}
              {rules.di.persistence_m} cycles
            </td>
          </tr>
          <tr>
            <th scope="row">Sensor |z| rules</th>
            <td>
              {rules.sensors.length
                ? rules.sensors.map((r) => `${r.tag} ${r.warning}/${r.alert}`).join(", ")
                : "None"}
            </td>
          </tr>
          <tr>
            <th scope="row">In service now</th>
            <td>{live ? `Version ${live.version} (${live.status})` : "None"}</td>
          </tr>
        </tbody>
      </table>
      {latest.status !== "Validated" ? (
        <p role="alert">Only a Validated version can be deployed; this one is {latest.status}.</p>
      ) : (
        <div className="builder-buttons">
          <button type="button" className="btn btn-s" onClick={() => go(5)}>
            ← Back
          </button>
          <button type="button" className="btn btn-p" onClick={() => setConfirming(true)}>
            Deploy version {latest.version}
          </button>
        </div>
      )}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={`Deploy ${model.asset_code} / ${model.name} version ${latest.version}?`}
        consequence={
          live
            ? `Version ${latest.version} scores from the next cycle with these limits; version ${live.version} is superseded and stops scoring; open alerts carry on.`
            : `Version ${latest.version} scores from the next cycle with these limits, and its alerts appear on the alert list.`
        }
        confirmLabel="Deploy"
        onConfirm={deploy}
      />
    </Panel>
  );
}
