import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { fetchAllAssets, fetchAssetTags } from "../../api/assets";
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
  MIN_CYCLE_S,
  alertRules,
  applyTemplate,
  fromLocalInput,
  inService,
  newDraft,
  share,
  stepProblems,
  toDefinition,
  trainingTrend,
} from "./builderModel";

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
        <ul role="alert" className="form-error builder-problems">
          {shown.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      <div className="builder-buttons">
        {step > 1 && (
          <button type="button" className="button" onClick={() => go(step - 1)}>
            ← Back
          </button>
        )}
        {next && (
          <button
            type="button"
            className="button button-primary"
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
    <section className="panel" aria-label={title}>
      <h2 className="panel-title">{title}</h2>
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
    <Panel title="1 Asset and sensors">
      <div className="builder-fields">
        {model ? (
          <p>
            Asset <strong>{model.asset_code}</strong>, model <strong>{model.name}</strong>
          </p>
        ) : (
          <>
            <label className="field">
              <span>Asset</span>
              <select
                className="control"
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
            <label className="field">
              <span>Model name</span>
              <input
                className="control"
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
            </label>
          </>
        )}
        <label className="field builder-wide">
          <span>Description</span>
          <input
            className="control"
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
              <p className="muted">
                {draft.sensors.length} of {tags.data.length} tags selected. A required sensor must
                be usable for the model to score (UCS §6.1).
              </p>
              <button
                type="button"
                className="button button-small"
                disabled={!mapped}
                onClick={() => setDraft(applyTemplate(draft, tags.data))}
              >
                Apply asset-type template ({mapped} tags)
              </button>
            </div>
            <table className="tree-table">
              <caption className="visually-hidden">Tags of {draft.asset}</caption>
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
                      <td>{t.role ?? <span className="muted">—</span>}</td>
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

function PeriodFields({
  label,
  value,
  onChange,
}: {
  label: string;
  value: { start: string; end: string };
  onChange: (value: { start: string; end: string }) => void;
}) {
  return (
    <fieldset className="builder-period">
      <legend>{label}</legend>
      <label className="field">
        <span>From</span>
        <input
          className="control"
          type="datetime-local"
          value={value.start}
          onChange={(e) => onChange({ ...value, start: e.target.value })}
        />
      </label>
      <label className="field">
        <span>To</span>
        <input
          className="control"
          type="datetime-local"
          value={value.end}
          onChange={(e) => onChange({ ...value, end: e.target.value })}
        />
      </label>
    </fieldset>
  );
}

export function StepPeriods({ draft, setDraft, go }: StepProps) {
  return (
    <Panel title="2 Training and validation periods">
      <p className="muted">
        The model learns normal behaviour from the training periods and is played back over the
        validation period, which may not overlap them (UC-05). Times are in this browser's time
        zone.
      </p>
      {draft.training.map((p, i) => (
        <div key={i} className="builder-row">
          <PeriodFields
            label={`Training period ${i + 1}`}
            value={p}
            onChange={(value) =>
              setDraft({
                ...draft,
                training: draft.training.map((q, j) => (j === i ? value : q)),
              })
            }
          />
          {draft.training.length > 1 && (
            <button
              type="button"
              className="button button-small"
              onClick={() =>
                setDraft({ ...draft, training: draft.training.filter((_, j) => j !== i) })
              }
            >
              Remove period {i + 1}
            </button>
          )}
        </div>
      ))}
      <button
        type="button"
        className="button button-small"
        onClick={() =>
          setDraft({
            ...draft,
            training: [...draft.training, { start: "", end: "" }],
          })
        }
      >
        Add a training period
      </button>
      <PeriodFields
        label="Validation period (hold-out)"
        value={draft.validation}
        onChange={(validation) => setDraft({ ...draft, validation })}
      />
      <label className="field builder-narrow">
        <span>Scoring cycle (seconds)</span>
        <input
          className="control"
          type="number"
          min={MIN_CYCLE_S}
          step={1}
          value={draft.cycleS}
          onChange={(e) => setDraft({ ...draft, cycleS: Number(e.target.value) })}
        />
      </label>
      <StepFooter step={2} problems={stepProblems(2, draft)} go={go} next={() => go(3)} />
    </Panel>
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
    <Panel title="3 Cleanse data">
      <fieldset className="builder-filters">
        <legend>Operating-mode filters</legend>
        <p className="muted small">
          Only cycles that satisfy every filter are used, for example{" "}
          <code>K101.II1001.PV &gt; 120</code> (motor running). Name tags by their source name.
        </p>
        {draft.modeFilters.map((f, i) => (
          <div key={i} className="builder-row">
            <label className="field builder-wide">
              <span>Filter {i + 1}</span>
              <input
                className="control mono"
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
              className="button button-small"
              onClick={() =>
                setDraft({ ...draft, modeFilters: draft.modeFilters.filter((_, j) => j !== i) })
              }
            >
              Remove filter {i + 1}
            </button>
          </div>
        ))}
        <div className="builder-row">
          <label className="field-inline">
            <span>Add a filter on</span>
            <select
              className="control"
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
            className="button button-small"
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
            <label className="field-inline">
              <span>Training data of</span>
              <select className="control" value={shown} onChange={(e) => setSensor(e.target.value)}>
                {data.sensors.map((s) => (
                  <option key={s.source_name} value={s.source_name}>
                    {s.source_name}
                  </option>
                ))}
              </select>
            </label>
            {trend && (
              <TrendChart
                title={`Training data · ${shown} · shaded = excluded`}
                group="builder"
                data={{ actual: trend.points, excluded: trend.excluded }}
                settings={{
                  from: trend.from,
                  to: trend.to,
                  unit: tags.data?.find((t) => t.source_name === shown)?.unit ?? "",
                  actualName: shown,
                }}
              />
            )}
            <table className="summary-table">
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
                  <th scope="row">Operating mode</th>
                  <td className="mono">{applied.length ? applied.join(" and ") : "None"}</td>
                  <td className="num">{share(data.mode_removed, data.cycles)} removed</td>
                </tr>
                <tr>
                  <th scope="row">Data quality and coverage</th>
                  <td>
                    Bad, stale and flatline samples; at least 70 % of sensors and every required
                    sensor usable
                  </td>
                  <td className="num">{share(data.quality_removed, data.cycles)} removed</td>
                </tr>
              </tbody>
            </table>
            <p className="muted small">
              Outlier removal, periods excluded on the trend and operating clusters arrive with AAKR
              training.
            </p>
          </div>
          <table className="summary-table">
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
                <th scope="row">Minimum data</th>
                <td>
                  {data.blocked ? (
                    <span className="form-error">✖ {data.blocked}</span>
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
  const percent = job.data?.progress ?? null;

  return (
    <Panel title="4 Train and validate">
      <p>
        Version {latest.version} <strong>{latest.status}</strong>
      </p>
      {latest.status === "Draft" && (
        <p>
          The draft is saved but not training.{" "}
          <button type="button" className="button button-small" onClick={() => retrain.mutate()}>
            Start training
          </button>
        </p>
      )}
      {running && (
        <div className="builder-progress">
          <label className="field">
            <span>
              Training{percent !== null ? `: ${Math.round(percent)} %` : "…"}
              {job.data?.status === "queued" ? " (waiting for the worker)" : ""}
            </span>
            <progress max={100} value={percent ?? undefined} />
          </label>
          <p className="muted small">
            Training runs in the background. You can leave this page; this step shows the result
            when you come back.
          </p>
        </div>
      )}
      {latest.status === "Failed" && (
        <div role="alert">
          <p className="form-error">Training failed: {latest.error}</p>
          <p>
            Change the definition in the earlier steps, or{" "}
            <button
              type="button"
              className="button button-small"
              disabled={retrain.isPending}
              onClick={() => retrain.mutate()}
            >
              train again
            </button>
          </p>
        </div>
      )}
      {latest.status === "Validated" && (
        <table className="summary-table">
          <caption>Training and validation</caption>
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
      )}
      {retrain.error !== null && (
        <ul role="alert" className="form-error">
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
          setDraft({ ...draft, jobId: null });
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
      className="control builder-number"
      type="number"
      aria-label={label}
      step={step}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
    />
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

  function setRule(tag: string, change: Partial<{ warning: number; alert: number }> | null) {
    const others = draft.sensorRules.filter((r) => r.tag !== tag);
    const current = rules.get(tag) ?? { tag, ...DEFAULT_SENSOR };
    setDraft({
      ...draft,
      sensorRules: change === null ? others : [...others, { ...current, ...change }],
    });
  }

  return (
    <Panel title="5 Alert limits">
      <p className="muted">
        The limits start at the defaults (Deviation Index warning 15 % and alert 25 %; sensor |z| 3
        and 5). Limits proposed from the validation period, with the estimated alert rate, arrive
        with AAKR training.
        {live &&
          ` Version ${live.version} keeps its current limits until this version is deployed.`}
      </p>
      <fieldset className="builder-period">
        <legend>Deviation Index (DI) rule</legend>
        <div className="field">
          <span aria-hidden="true">Warning (%)</span>
          <NumberCell
            label="DI warning (%)"
            value={di.warning}
            onChange={(warning) => setDraft({ ...draft, di: { ...di, warning } })}
          />
        </div>
        <div className="field">
          <span aria-hidden="true">Alert (%)</span>
          <NumberCell
            label="DI alert (%)"
            value={di.alert}
            onChange={(alert) => setDraft({ ...draft, di: { ...di, alert } })}
          />
        </div>
        <div className="field">
          <span aria-hidden="true">Persistence: n cycles</span>
          <NumberCell
            label="Persistence n"
            step={1}
            value={di.n}
            onChange={(n) => setDraft({ ...draft, di: { ...di, n } })}
          />
        </div>
        <div className="field">
          <span aria-hidden="true">of the last m</span>
          <NumberCell
            label="Persistence m"
            step={1}
            value={di.m}
            onChange={(m) => setDraft({ ...draft, di: { ...di, m } })}
          />
        </div>
      </fieldset>
      <table className="tree-table">
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
                  {s.required && <span className="muted"> · required</span>}
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
      <StepFooter
        step={5}
        problems={stepProblems(5, draft)}
        go={go}
        next={() => (live ? go(6) : save.mutate())}
        busy={save.isPending}
        error={save.error}
      />
    </Panel>
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
    <Panel title="6 Deploy">
      <table className="summary-table">
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
          <button type="button" className="button" onClick={() => go(5)}>
            ← Back
          </button>
          <button
            type="button"
            className="button button-primary"
            onClick={() => setConfirming(true)}
          >
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
            ? `Version ${latest.version} scores from the next cycle with these limits; version ${live.version} is superseded and stops scoring.`
            : `Version ${latest.version} scores from the next cycle with these limits, and its alerts appear on the alert list.`
        }
        confirmLabel="Deploy"
        onConfirm={deploy}
      />
    </Panel>
  );
}
