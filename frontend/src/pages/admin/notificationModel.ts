import type { User } from "../../api/auth";
import type { EventName, NotificationEvent, Subscription } from "../../api/notifications";

/** The events a user can usefully choose: the model review is for model engineers, the
 * stale-source warning for administrators (UCS §6.10). */
export function eventsFor(
  events: NotificationEvent[],
  user: User | null | undefined,
): NotificationEvent[] {
  const roles = new Set(user?.roles.map((r) => r.role) ?? []);
  return events.filter(
    (e) =>
      (e.value !== "model_review" || roles.has("model_engineer")) &&
      (e.value !== "source_stale" || roles.has("administrator")),
  );
}

/** "P2 and above · K-101 · Alert raised, Case assigned to me" (off: "(off)"). */
export function subscriptionText(s: Subscription, labels: Map<EventName, string>): string {
  const priority = s.min_priority === "P1" ? "P1 only" : `${s.min_priority} and above`;
  const scope = s.scope_code ?? "everything I can see";
  const events = s.events.map((e) => labels.get(e) ?? e).join(", ");
  return `${priority} · ${scope} · ${events}${s.enabled ? "" : " (off)"}`;
}
