import { api } from "./client";

export type EventName =
  | "alert_raised"
  | "alert_escalated"
  | "case_assigned"
  | "case_overdue"
  | "model_review"
  | "source_stale";

export interface NotificationEvent {
  value: EventName;
  label: string;
}

/** One of my subscriptions (UC-15): scope, minimum priority and events, by e-mail. */
export interface Subscription {
  id: number;
  scope_asset_id: number | null;
  scope_code: string | null;
  min_priority: "P1" | "P2" | "P3" | "P4";
  events: EventName[];
  channel: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface SubscriptionIn {
  scope_asset_id: number | null;
  min_priority: Subscription["min_priority"];
  events: EventName[];
  enabled: boolean;
}

/** One row of the delivery log (administrators). */
export interface Delivery {
  id: number;
  user_id: number;
  event: string;
  alert_id: number | null;
  case_id: number | null;
  recipient: string;
  subject: string;
  status: "pending" | "sent" | "failed" | "held" | "summarised";
  attempts: number;
  next_attempt_at: string | null;
  last_error: string | null;
  summary_id: number | null;
  created_at: string;
  sent_at: string | null;
}

export function fetchEvents(signal?: AbortSignal): Promise<NotificationEvent[]> {
  return api<NotificationEvent[]>("/notifications/events", { signal });
}

export function fetchSubscriptions(signal?: AbortSignal): Promise<Subscription[]> {
  return api<Subscription[]>("/notifications/subscriptions", { signal });
}

export function createSubscription(body: SubscriptionIn): Promise<Subscription> {
  return api<Subscription>("/notifications/subscriptions", { method: "POST", body });
}

export function updateSubscription(id: number, body: SubscriptionIn): Promise<Subscription> {
  return api<Subscription>(`/notifications/subscriptions/${id}`, { method: "PUT", body });
}

export function deleteSubscription(id: number): Promise<void> {
  return api<void>(`/notifications/subscriptions/${id}`, { method: "DELETE" });
}

export function fetchDeliveries(
  status: Delivery["status"] | null,
  signal?: AbortSignal,
): Promise<Delivery[]> {
  return api<Delivery[]>("/notifications/log", { query: { status, limit: 200 }, signal });
}

export function sendTestEmail(to: string): Promise<void> {
  return api<void>("/notifications/test", { method: "POST", body: { to } });
}
