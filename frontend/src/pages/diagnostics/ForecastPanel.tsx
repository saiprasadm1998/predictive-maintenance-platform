import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { errorMessages } from "../../api/client";
import {
  type Forecast,
  type ForecastIn,
  type ThresholdKind,
  fetchForecasts,
  runForecast,
} from "../../api/forecasts";
import type { AlertRule, SensorNow } from "../../api/types";
import { formatDateTime, formatIso } from "../../app/format";
import { useMe } from "../../app/session";
import { TrendChart } from "../../components/TrendChart";
import {
  WINDOW_CHOICES,
  canRunForecast,
  forecastChart,
  intervalText,
  medianText,
  methodText,
  targetText,
  thresholdText,
} from "./forecastModel";

/**
 * The time-to-threshold forecast of SCR-04 (UC-11, UCS §6.8, PDS §4.4): the newest forecast
 * of the model, its urgency, median and 80 % interval, method, window and R², and the
 * forecast chart; analysts and model engineers choose the target (DI, or a sensor's actual
 * or residual), the threshold and the fit window and run it again. The result is stored
 * with the model's open alert on that target, so the alert list shows its urgency.
 */
export function ForecastPanel({
  modelId,
  sensors,
  diRule,
}: {
  modelId: number;
  sensors: SensorNow[];
  diRule: AlertRule | undefined;
}) {
  const client = useQueryClient();
  const me = useMe();
  const canRun = canRunForecast(me.data);
  const forecasts = useQuery({
    queryKey: ["forecasts", modelId],
    queryFn: ({ signal }) => fetchForecasts(modelId, 1, signal),
  });
  const [target, setTarget] = useState("di");
  const [kind, setKind] = useState<ThresholdKind>("alert");
  const [value, setValue] = useState("");
  const [days, setDays] = useState(7);
  const run = useMutation({
    mutationFn: (body: ForecastIn) => runForecast(body),
    onSuccess: (made) => {
      client.setQueryData(["forecasts", modelId], [made]);
      void client.invalidateQueries({ queryKey: ["alerts"] });
    },
  });

  const [targetKind, tag] = target.split(":") as ["di" | "actual" | "residual", string?];
  const sensorTarget = targetKind !== "di";
  const thresholdKind: ThresholdKind = sensorTarget ? "custom" : kind;
  const custom = Number(value);
  const ready = thresholdKind !== "custom" || (value.trim() !== "" && Number.isFinite(custom));

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!ready) return;
    run.mutate({
      model_id: modelId,
      target: targetKind,
      tag_id: sensorTarget ? Number(tag) : null,
      threshold_kind: thresholdKind,
      threshold: thresholdKind === "custom" ? custom : null,
      window_days: days,
    });
  }

  const shown = forecasts.data?.[0];
  const unit = (f: Forecast) =>
    f.target === "di" ? "%" : (sensors.find((s) => s.tag_id === f.tag_id)?.unit ?? "");

  return (
    <section className="panel" aria-labelledby="forecast-title">
      <h2 id="forecast-title" className="panel-title">
        Time-to-threshold forecast
        {shown ? ` · ${targetText(shown)} → ${thresholdText(shown)} ${unit(shown)}`.trimEnd() : ""}
      </h2>
      {forecasts.isError && (
        <p role="alert">Forecasts could not be loaded: {forecasts.error.message}</p>
      )}
      {shown ? (
        <ForecastResult forecast={shown} unit={unit(shown)} />
      ) : forecasts.isSuccess ? (
        <p className="muted">No forecast has been run for this model yet.</p>
      ) : null}

      {canRun ? (
        <form className="forecast-form" onSubmit={submit} aria-label="Run a forecast">
          <label className="field-inline">
            <span>Target</span>
            <select className="control" value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="di">Deviation Index</option>
              {sensors.map((s) => (
                <option key={`a${s.tag_id}`} value={`actual:${s.tag_id}`}>
                  {s.source_name} actual
                </option>
              ))}
              {sensors.map((s) => (
                <option key={`r${s.tag_id}`} value={`residual:${s.tag_id}`}>
                  {s.source_name} residual
                </option>
              ))}
            </select>
          </label>
          {!sensorTarget && (
            <label className="field-inline">
              <span>Threshold</span>
              <select
                className="control"
                value={kind}
                onChange={(e) => setKind(e.target.value as ThresholdKind)}
              >
                <option value="alert" disabled={!diRule}>
                  Alert limit{diRule ? ` (${diRule.alert})` : ""}
                </option>
                <option value="warning" disabled={!diRule}>
                  Warning limit{diRule ? ` (${diRule.warning})` : ""}
                </option>
                <option value="custom">Custom value</option>
              </select>
            </label>
          )}
          {thresholdKind === "custom" && (
            <label className="field-inline">
              <span>{sensorTarget ? "Threshold" : "Value"}</span>
              <input
                className="control control-narrow"
                inputMode="decimal"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                aria-describedby="threshold-hint"
              />
            </label>
          )}
          <label className="field-inline">
            <span>Fit window</span>
            <select
              className="control"
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
            >
              {WINDOW_CHOICES.map((d) => (
                <option key={d} value={d}>
                  {d} {d === 1 ? "day" : "days"}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="button" disabled={!ready || run.isPending}>
            {run.isPending ? "Forecasting…" : "Run forecast"}
          </button>
          {sensorTarget && (
            <p id="threshold-hint" className="muted small">
              In the sensor&apos;s units: the registry holds no alarm or trip limits.
            </p>
          )}
          {run.isError && (
            <p role="alert" className="form-error">
              {errorMessages(run.error).join(" ")}
            </p>
          )}
        </form>
      ) : (
        <p className="muted small">Analysts and model engineers run forecasts.</p>
      )}
    </section>
  );
}

function ForecastResult({ forecast: f, unit }: { forecast: Forecast; unit: string }) {
  const chart = forecastChart(f);
  return (
    <>
      <p className="forecast-line">
        <span className={`urgency urgency-${f.urgency.toLowerCase()}`}>
          Urgency: {f.urgency.toUpperCase()}
        </span>
        {f.valid && f.median_h !== null && f.lower_h !== null ? (
          <>
            {" "}
            · median {medianText(f.median_h)} · 80 % interval {intervalText(f.lower_h, f.upper_h)}
          </>
        ) : null}{" "}
        · {methodText(f)}
      </p>
      <p>{f.summary}</p>
      <p className="muted small">
        Run{" "}
        <time dateTime={f.created_at} title={formatIso(new Date(f.created_at))}>
          {formatDateTime(new Date(f.created_at))}
        </time>{" "}
        on data up to {formatDateTime(new Date(f.at))}
        {f.alert_id ? `, stored with alert ${f.alert_id}` : ""}.
      </p>
      <TrendChart
        title={`Forecast of ${targetText(f)}`}
        data={chart.data}
        settings={{
          unit,
          from: chart.from,
          to: chart.to,
          actualName: "15-minute mean",
          predictedName: "Projection",
          bandName: "80 % interval",
        }}
        group="forecast"
        height={200}
      />
    </>
  );
}
