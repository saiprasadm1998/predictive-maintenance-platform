import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { fetchAllAssets } from "../../api/assets";
import { errorMessages } from "../../api/client";
import {
  type EventName,
  type Subscription,
  type SubscriptionIn,
  createSubscription,
  deleteSubscription,
  fetchEvents,
  fetchPreferences,
  fetchSubscriptions,
  savePreferences,
  sendTestEmail,
  updateSubscription,
} from "../../api/notifications";
import { useMe } from "../../app/session";
import {
  Badge,
  Dialog,
  HowTo,
  Loading,
  PageHeader,
  Panel,
  Pill,
  Problems,
  Tabs,
} from "../../components/ui";
import { NotificationLogTab } from "../admin/NotificationLogTab";
import { isAdministrator } from "../admin/adminModel";
import { eventsFor } from "../admin/notificationModel";

type Tab = "mine" | "log";
const PRIORITIES = ["P1", "P2", "P3", "P4"] as const;
const hour = (h: number) => `${String(h).padStart(2, "0")}:00`;

function SubscriptionDialog({
  existing,
  onClose,
}: {
  existing: Subscription | null;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const me = useMe();
  const events = useQuery({
    queryKey: ["notifications", "events"],
    queryFn: ({ signal }) => fetchEvents(signal),
  });
  const assets = useQuery({
    queryKey: ["assets", "all"],
    queryFn: ({ signal }) => fetchAllAssets(signal),
  });
  const [scope, setScope] = useState<number | null>(existing?.scope_asset_id ?? null);
  const [priority, setPriority] = useState<Subscription["min_priority"]>(
    existing?.min_priority ?? "P2",
  );
  const [chosen, setChosen] = useState<Set<EventName>>(
    new Set(existing?.events ?? ["alert_raised", "alert_escalated"]),
  );
  const [delivery, setDelivery] = useState<Subscription["delivery"]>(
    existing?.delivery ?? "immediate",
  );
  const body = (): SubscriptionIn => ({
    scope_asset_id: scope,
    min_priority: priority,
    events: [...chosen],
    enabled: existing?.enabled ?? true,
    delivery,
  });
  const save = useMutation({
    mutationFn: () =>
      existing ? updateSubscription(existing.id, body()) : createSubscription(body()),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["notifications"] });
      onClose();
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteSubscription(existing!.id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["notifications"] });
      onClose();
    },
  });
  const choices = eventsFor(events.data ?? [], me.data);
  const toggle = (e: EventName) => {
    const next = new Set(chosen);
    if (next.has(e)) next.delete(e);
    else next.add(e);
    setChosen(next);
  };
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={existing ? "Edit the subscription" : "Add a subscription"}
      footer={
        <>
          {existing && (
            <button
              className="btn btn-g"
              type="button"
              style={{ marginRight: "auto" }}
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
            >
              Delete
            </button>
          )}
          <button className="btn btn-s" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-p"
            type="button"
            disabled={chosen.size === 0 || save.isPending}
            onClick={() => save.mutate()}
          >
            {existing ? "Save" : "Add subscription"}
          </button>
        </>
      }
    >
      <div className="fg">
        <div className="fld">
          <label htmlFor="ns-s">Scope</label>
          <select
            id="ns-s"
            className="sl"
            value={scope ?? ""}
            onChange={(e) => setScope(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">Everything I can see</option>
            {(assets.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.level === "equipment" ? `${a.code} ${a.name}` : a.name}
              </option>
            ))}
          </select>
        </div>
        <div className="fld">
          <label htmlFor="ns-p">Lowest priority</label>
          <select
            id="ns-p"
            className="sl"
            value={priority}
            onChange={(e) => setPriority(e.target.value as Subscription["min_priority"])}
          >
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p === "P1" ? "P1 only" : `${p} and above`}
              </option>
            ))}
          </select>
        </div>
        <fieldset className="fld span2" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="lb" style={{ fontSize: 12, color: "var(--traverse-text-secondary)" }}>
            Events
          </legend>
          {choices.map((e) => (
            <label key={e.value} className="chk" style={{ minHeight: 32 }}>
              <input
                type="checkbox"
                checked={chosen.has(e.value)}
                onChange={() => toggle(e.value)}
              />
              {e.label}
            </label>
          ))}
        </fieldset>
        <div className="fld span2">
          <label htmlFor="ns-d">Delivery</label>
          <select
            id="ns-d"
            className="sl"
            value={delivery}
            onChange={(e) => setDelivery(e.target.value as Subscription["delivery"])}
          >
            <option value="immediate">Immediately, throttled per alert</option>
            <option value="daily">Daily digest</option>
          </select>
        </div>
      </div>
      <Problems
        messages={
          save.isError
            ? errorMessages(save.error)
            : remove.isError
              ? errorMessages(remove.error)
              : []
        }
      />
    </Dialog>
  );
}

function MyNotifications({
  admin,
  adding,
  onAdded,
}: {
  admin: boolean;
  adding: boolean;
  onAdded: () => void;
}) {
  const client = useQueryClient();
  const me = useMe();
  const subs = useQuery({
    queryKey: ["notifications", "subscriptions"],
    queryFn: ({ signal }) => fetchSubscriptions(signal),
  });
  const events = useQuery({
    queryKey: ["notifications", "events"],
    queryFn: ({ signal }) => fetchEvents(signal),
  });
  const prefs = useQuery({
    queryKey: ["notifications", "preferences"],
    queryFn: ({ signal }) => fetchPreferences(signal),
  });
  const [editing, setEditing] = useState<Subscription | null>(null);
  const [testTo, setTestTo] = useState("");
  const pause = useMutation({
    mutationFn: (s: Subscription) =>
      updateSubscription(s.id, {
        scope_asset_id: s.scope_asset_id,
        min_priority: s.min_priority,
        events: s.events,
        enabled: !s.enabled,
        delivery: s.delivery,
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const quiet = useMutation({
    mutationFn: (value: string) => {
      const [a, b] = value ? value.split("-").map(Number) : [null, null];
      return savePreferences(a ?? null, b ?? null);
    },
    onSuccess: () => void client.invalidateQueries({ queryKey: ["notifications", "preferences"] }),
  });
  const test = useMutation({
    mutationFn: () => sendTestEmail(testTo.trim() || me.data?.email || ""),
  });
  if (subs.isPending) return <Loading what="your subscriptions" />;
  const labels = new Map((events.data ?? []).map((e) => [e.value, e.label]));
  const p = prefs.data;
  const quietValue =
    p && p.quiet_start !== null && p.quiet_end !== null ? `${p.quiet_start}-${p.quiet_end}` : "";
  const QUIET = [
    ["", "None"],
    ["22-6", "22:00 to 06:00"],
    ["20-7", "20:00 to 07:00"],
    ["18-8", "18:00 to 08:00"],
  ];
  if (quietValue && !QUIET.some(([v]) => v === quietValue))
    QUIET.push([quietValue, `${hour(p!.quiet_start!)} to ${hour(p!.quiet_end!)}`]);
  return (
    <>
      <Panel
        title="My subscriptions"
        actions={
          <span className="meta">
            Sent to {me.data?.email ?? "no e-mail address: ask an administrator to add one"}
          </span>
        }
      >
        {(subs.data ?? []).length === 0 ? (
          <p className="sec s13">
            No subscriptions. Add one to get e-mail when an alert or case changes.
          </p>
        ) : (
          <div className="tw">
            <table className="tb">
              <thead>
                <tr>
                  <th>Scope</th>
                  <th>Lowest priority</th>
                  <th>Events</th>
                  <th>Delivery</th>
                  <th>State</th>
                  <th style={{ textAlign: "right" }}>Change</th>
                </tr>
              </thead>
              <tbody>
                {(subs.data ?? []).map((s) => (
                  <tr key={s.id}>
                    <td>{s.scope_code ?? "Everything I can see"}</td>
                    <td>
                      <Badge>{s.min_priority}</Badge>
                    </td>
                    <td className="sec">{s.events.map((e) => labels.get(e) ?? e).join(", ")}</td>
                    <td>
                      {s.delivery === "daily"
                        ? `Daily digest at ${hour(p?.digest_hour ?? 7)}`
                        : `Immediately, at most 1 per alert every ${p?.per_alert_minutes ?? 30} min`}
                    </td>
                    <td>
                      {s.enabled ? <Pill tone="info">On</Pill> : <Pill tone="unknown">Paused</Pill>}
                    </td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      <button
                        className="btn btn-s btn-sm"
                        type="button"
                        onClick={() => setEditing(s)}
                      >
                        Edit
                      </button>{" "}
                      <button
                        className="btn btn-g btn-sm"
                        type="button"
                        onClick={() => pause.mutate(s)}
                      >
                        {s.enabled ? "Pause" : "Resume"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Problems messages={pause.isError ? errorMessages(pause.error) : []} />
      </Panel>
      <Panel title="Throttling and test" className="fill">
        <div className="filters" style={{ justifyContent: "space-between" }}>
          <div className="filters">
            <div className="fld" style={{ width: 200 }}>
              <label htmlFor="nt-t">At most one e-mail per alert every</label>
              <select id="nt-t" className="sl" disabled value="x">
                <option value="x">{p?.per_alert_minutes ?? 30} minutes</option>
              </select>
            </div>
            <div className="fld" style={{ width: 200 }}>
              <label htmlFor="nt-q">Quiet hours ({p?.time_zone ?? "plant time"})</label>
              <select
                id="nt-q"
                className="sl"
                value={quietValue}
                disabled={quiet.isPending}
                onChange={(e) => quiet.mutate(e.target.value)}
              >
                {QUIET.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {admin && (
            <div className="filters">
              <div className="fld" style={{ width: 220 }}>
                <label htmlFor="nt-e">Send a test to</label>
                <input
                  id="nt-e"
                  className="in"
                  type="email"
                  placeholder={me.data?.email ?? "name@plant.example"}
                  value={testTo}
                  onChange={(e) => setTestTo(e.target.value)}
                />
              </div>
              <button
                className="btn btn-s"
                type="button"
                disabled={test.isPending}
                onClick={() => test.mutate()}
              >
                Send a test e-mail
              </button>
            </div>
          )}
        </div>
        <p className="meta" style={{ marginTop: 8 }}>
          The throttle is set by the administrator for everyone. Messages held during quiet hours go
          out in the next summary.
        </p>
        {test.isSuccess && <p className="notice">Test e-mail sent.</p>}
        <Problems
          messages={[
            ...(test.isError ? errorMessages(test.error) : []),
            ...(quiet.isError ? errorMessages(quiet.error) : []),
          ]}
        />
      </Panel>
      {(adding || editing) && (
        <SubscriptionDialog
          existing={editing}
          onClose={() => {
            setEditing(null);
            onAdded();
          }}
        />
      )}
    </>
  );
}

export function NotificationsPage() {
  const me = useMe();
  const admin = isAdministrator(me.data);
  const [params, setParams] = useSearchParams();
  const [adding, setAdding] = useState(false);
  const tab: Tab = admin && params.get("tab") === "log" ? "log" : "mine";
  const setTab = (t: Tab) => {
    params.set("tab", t);
    setParams(params, { replace: true });
  };
  return (
    <>
      <PageHeader
        title="Notifications"
        sub="E-mail when an alert or case you follow changes"
        actions={
          <>
            <HowTo title="Notifications">
              Choose the equipment, the lowest priority and the events you want e-mail for. Repeated
              e-mails about the same alert are held back by the throttle; a daily digest collects
              everything into one e-mail.
            </HowTo>
            <button className="btn btn-p" type="button" onClick={() => setAdding(true)}>
              Add a subscription
            </button>
          </>
        }
      />
      {admin && (
        <Tabs
          label="Notifications"
          value={tab}
          onChange={setTab}
          tabs={[
            { value: "mine", label: "My notifications" },
            { value: "log", label: "Notification log (admin)" },
          ]}
        />
      )}
      {tab === "log" ? (
        <Panel className="fill">
          <div className="legacy">
            <NotificationLogTab />
          </div>
        </Panel>
      ) : (
        <MyNotifications admin={admin} adding={adding} onAdded={() => setAdding(false)} />
      )}
    </>
  );
}
