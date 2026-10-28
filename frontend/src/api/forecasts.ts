import { api } from "./client";

export type ForecastTarget = "di" | "actual" | "residual";
export type ThresholdKind = "warning" | "alert" | "custom";
export type Urgency = "Immediate" | "High" | "Medium" | "Low" | "None";

/** A time-to-threshold forecast (UC-11, UCS §6.8), as stored with its alert. */
export interface Forecast {
  id: number;
  model_id: number;
  version_id: number;
  alert_id: number | null;
  target: ForecastTarget;
  tag_id: number | null;
  tag: string | null;
  threshold_kind: ThresholdKind;
  threshold: number;
  direction: "up" | "down";
  window_days: number;
  at: string; // crossing times count from here
  fit: {
    method: "linear" | "exponential" | null;
    params: Record<string, number>; // linear a, b; exponential c, a, b; t in days from `at`
    r2: number | null;
  };
  points: number;
  valid: boolean;
  reason: string | null;
  median_h: number | null;
  lower_h: number | null;
  upper_h: number | null; // null: beyond reach
  crossing_at: string | null;
  urgency: Urgency;
  summary: string;
  series: { ts: string; value: number }[];
  created_at: string;
  created_by: number | null;
}

export interface ForecastIn {
  model_id: number;
  target: ForecastTarget;
  tag_id?: number | null;
  threshold_kind: ThresholdKind;
  threshold?: number | null;
  direction?: "up" | "down" | null;
  window_days: number;
  alert_id?: number | null;
}

export function runForecast(body: ForecastIn): Promise<Forecast> {
  return api<Forecast>("/forecasts", { method: "POST", body });
}

/** A model's forecasts, newest first. */
export function fetchForecasts(
  modelId: number,
  limit: number,
  signal?: AbortSignal,
): Promise<Forecast[]> {
  return api<Forecast[]>("/forecasts", { query: { model_id: modelId, limit }, signal });
}
