import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { fetchAllAssets } from "../../api/assets";
import {
  type EventName,
  type Subscription,
  type SubscriptionIn,
  createSubscription,
  deleteSubscription,
  fetchEvents,
  fetchSubscriptions,
  updateSubscription,
} from "../../api/notifications";
import { useAnnounce } from "../../app/liveContext";
import { useMe } from "../../app/session";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Skeleton } from "../fleet/FleetPage";
import { Field, Problems } from "../registry/common";
import { eventsFor, subscriptionText } from "./notificationModel";

const PRIORITIES = ["P1", "P2", "P3", "P4"] as const;

/**
 * My notifications (UC-15, UCS §6.10; ARC §9.2 "own notification subscriptions", every
 * role): e-mail for the chosen events on a part of the hierarchy at or above a priority.
 * At most one e-mail per alert per 30 minutes and 20 an hour, then a summary.
 */
export function NotificationsTab() {
  const me = useMe();
  const subs = useQuery({
    queryKey: ["notifications", "subscriptions"],
    queryFn: ({ signal }) => fetchSubscriptions(signal),
  });
  const events = useQuery({
    queryKey: ["notifications", "events"],
    queryFn: ({ signal }) => fetchEvents(signal),
    staleTime: Infinity,
  });
  const assets = useQuery({
    queryKey: ["assets", "all"],
    queryFn: ({ signal }) => fetchAllAssets(signal),
  });
  const [editing, setEditing] = useState<Subscription | "new" | null>(null);
  const [removing, setRemoving] = useState<Subscription | null>(null);
  const client = useQueryClient();
  const announce = useAnnounce();

  if (subs.isPending || events.isPending) return <Skeleton rows={3} />;
  if (subs.isError)
    return <p role="alert">Your subscriptions could not be loaded: {subs.error.message}</p>;
  const choices = eventsFor(events.data ?? [], me.data);
  const labels = new Map((events.data ?? []).map((e) => [e.value, e.label]));

  return (
    <section className="panel" aria-labelledby="notifications-title">
      <div className="panel-head">
        <h2 id="notifications-title" className="panel-title">
          My notifications
        </h2>
        {editing === null && (
          <button type="button" className="button" onClick={() => setEditing("new")}>
            Add a subscription
          </button>
        )}
      </div>
      <p className="muted small">
        E-mails go to {me.data?.email ?? "your e-mail address"}
        {me.data?.email ? "" : " (none is set: ask an administrator to add one)"}. At most one per
        alert every 30 minutes and 20 an hour, then one summary. Shelved alerts and models out of
        service are not notified.
      </p>
      {subs.data.length === 0 && editing === null && (
        <p className="muted">You have no subscriptions, so you receive no e-mail.</p>
      )}
      <ul className="subscription-list">
        {subs.data.map((s) =>
          editing !== "new" && editing?.id === s.id ? (
            <li key={s.id}>
              <SubscriptionForm
                current={s}
                choices={choices}
                assets={assets.data ?? []}
                onDone={() => setEditing(null)}
              />
            </li>
          ) : (
            <li key={s.id} className="subscription">
              <span>{subscriptionText(s, labels)}</span>
              <span className="subscription-actions">
                <button type="button" className="link-button" onClick={() => setEditing(s)}>
                  Change
                </button>
                <button type="button" className="link-button" onClick={() => setRemoving(s)}>
                  Remove
                </button>
              </span>
            </li>
          ),
        )}
      </ul>
      {editing === "new" && (
        <SubscriptionForm
          current={null}
          choices={choices}
          assets={assets.data ?? []}
          onDone={() => setEditing(null)}
        />
      )}
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title="Remove this subscription"
        consequence="You stop receiving these e-mails."
        confirmLabel="Remove"
        danger
        onConfirm={async () => {
          if (!removing) return;
          await deleteSubscription(removing.id);
          await client.invalidateQueries({ queryKey: ["notifications", "subscriptions"] });
          announce("Subscription removed");
        }}
      />
    </section>
  );
}

function SubscriptionForm({
  current,
  choices,
  assets,
  onDone,
}: {
  current: Subscription | null;
  choices: { value: EventName; label: string }[];
  assets: { id: number; code: string; name: string }[];
  onDone: () => void;
}) {
  const client = useQueryClient();
  const announce = useAnnounce();
  const [scope, setScope] = useState(current?.scope_asset_id ? String(current.scope_asset_id) : "");
  const [priority, setPriority] = useState<SubscriptionIn["min_priority"]>(
    current?.min_priority ?? "P2",
  );
  const [chosen, setChosen] = useState<Set<EventName>>(
    new Set(current?.events ?? ["alert_raised", "alert_escalated"]),
  );
  const [enabled, setEnabled] = useState(current?.enabled ?? true);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const problems = chosen.size ? [] : ["Choose at least one event"];

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (problems.length) return;
    const body: SubscriptionIn = {
      scope_asset_id: scope ? Number(scope) : null,
      min_priority: priority,
      events: choices.map((c) => c.value).filter((v) => chosen.has(v)),
      enabled,
    };
    setBusy(true);
    setError(null);
    try {
      if (current) await updateSubscription(current.id, body);
      else await createSubscription(body);
      await client.invalidateQueries({ queryKey: ["notifications", "subscriptions"] });
      announce("Subscription saved");
      onDone();
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="form-grid subscription-form"
      onSubmit={save}
      aria-label={current ? "Change subscription" : "New subscription"}
    >
      <Field label="Scope">
        <select className="control" value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="">Everything I can see</option>
          {assets.map((a) => (
            <option key={a.id} value={a.id}>
              {a.code} · {a.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Minimum priority">
        <select
          className="control"
          value={priority}
          onChange={(e) => setPriority(e.target.value as SubscriptionIn["min_priority"])}
        >
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {p === "P1" ? "P1 only" : `${p} and above`}
            </option>
          ))}
        </select>
      </Field>
      <fieldset className="builder-wide event-choices">
        <legend>Events</legend>
        {choices.map((c) => (
          <label key={c.value} className="field-inline">
            <input
              type="checkbox"
              checked={chosen.has(c.value)}
              onChange={(e) => {
                const next = new Set(chosen);
                if (e.target.checked) next.add(c.value);
                else next.delete(c.value);
                setChosen(next);
              }}
            />
            {c.label}
          </label>
        ))}
      </fieldset>
      <label className="field-inline">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        On
      </label>
      <Problems problems={problems} error={error} />
      <div className="form-actions builder-wide">
        <button type="button" className="button" onClick={onDone} disabled={busy}>
          Cancel
        </button>
        <button
          type="submit"
          className="button button-primary"
          disabled={busy || problems.length > 0}
        >
          Save
        </button>
      </div>
    </form>
  );
}
