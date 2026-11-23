import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { acknowledgeAlerts, fetchAlertSettings, shelveAlerts } from "../../api/alerts";
import { addModeTasks, createCase, fetchAssetPeople, updateCase } from "../../api/cases";
import { errorMessages } from "../../api/client";
import { fetchDiagnosis } from "../../api/diagnostics";
import type { Alert } from "../../api/types";
import { formatDateTime } from "../../app/format";
import { Dialog, Pill, Problems } from "../../components/ui";
import { modelText, shelveChoices } from "./alertsModel";

function useRefresh() {
  const client = useQueryClient();
  return () =>
    Promise.all(
      ["alerts", "fleet", "assets", "cases", "models"].map((k) =>
        client.invalidateQueries({ queryKey: [k] }),
      ),
    );
}

function Selected({ alerts }: { alerts: readonly Alert[] }) {
  return (
    <div>
      {alerts.map((a) => (
        <div key={a.id} className="li">
          <Pill>{a.priority ?? "—"}</Pill>
          <span className="mono">A-{a.id}</span>
          <span className="grow s13">{modelText(a)}</span>
        </div>
      ))}
    </div>
  );
}

export function AckDialog({
  alerts,
  onClose,
}: {
  alerts: readonly Alert[];
  onClose: (done: boolean) => void;
}) {
  const [comment, setComment] = useState("");
  const refresh = useRefresh();
  const ack = useMutation({
    mutationFn: () =>
      acknowledgeAlerts(
        alerts.map((a) => a.id),
        comment.trim() || null,
      ),
    onSuccess: async () => {
      await refresh();
      onClose(true);
    },
  });
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose(false)}
      title={`Acknowledge ${alerts.length} alert${alerts.length === 1 ? "" : "s"}`}
      footer={
        <>
          <button className="btn btn-s" type="button" onClick={() => onClose(false)}>
            Cancel
          </button>
          <button
            className="btn btn-p"
            type="button"
            disabled={ack.isPending}
            onClick={() => ack.mutate()}
          >
            Acknowledge
          </button>
        </>
      }
    >
      <Selected alerts={alerts} />
      <div className="fld">
        <label htmlFor="ack-c">Comment (optional, kept in the history)</label>
        <textarea
          id="ack-c"
          className="ta"
          placeholder="What you checked or plan to do"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
      </div>
      <p className="sec s13">
        Acknowledging records that you have seen the alert. It stays open until the condition
        clears.
      </p>
      <Problems messages={ack.isError ? errorMessages(ack.error) : []} />
    </Dialog>
  );
}

export function ShelveDialog({
  alerts,
  onClose,
}: {
  alerts: readonly Alert[];
  onClose: (done: boolean) => void;
}) {
  const settings = useQuery({
    queryKey: ["alerts", "settings"],
    queryFn: ({ signal }) => fetchAlertSettings(signal),
  });
  const choices = shelveChoices(settings.data?.max_shelve_days ?? 7);
  const [reason, setReason] = useState("");
  const [minutes, setMinutes] = useState(8 * 60);
  const [tried, setTried] = useState(false);
  const refresh = useRefresh();
  const shelve = useMutation({
    mutationFn: () =>
      shelveAlerts(
        alerts.map((a) => a.id),
        reason.trim(),
        minutes,
      ),
    onSuccess: async () => {
      await refresh();
      onClose(true);
    },
  });
  const [now] = useState(() => Date.now());
  const ends = new Date(now + minutes * 60_000);
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose(false)}
      title={`Shelve ${alerts.length} alert${alerts.length === 1 ? "" : "s"}`}
      footer={
        <>
          <button className="btn btn-s" type="button" onClick={() => onClose(false)}>
            Cancel
          </button>
          <button
            className="btn btn-p"
            type="button"
            disabled={shelve.isPending}
            onClick={() => {
              setTried(true);
              if (reason.trim()) shelve.mutate();
            }}
          >
            Shelve
          </button>
        </>
      }
    >
      <p className="sec s13">
        Shelved alerts stop showing as active and stop notifying until the shelf ends; then they
        return to whatever their condition is.
      </p>
      <div className="fld">
        <label htmlFor="sh-r">Reason (required)</label>
        <textarea
          id="sh-r"
          className="ta"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="For example blade cleaning scheduled, work order 44812"
        />
        {tried && !reason.trim() && <span className="err">Enter a reason to shelve.</span>}
      </div>
      <div className="fg">
        <div className="fld">
          <label htmlFor="sh-d">For</label>
          <select
            id="sh-d"
            className="sl"
            value={minutes}
            onChange={(e) => setMinutes(Number(e.target.value))}
          >
            {choices
              .filter(([m]) => m <= (settings.data?.max_shelve_days ?? 7) * 1440)
              .map(([m, label]) => (
                <option key={m} value={m}>
                  {label}
                </option>
              ))}
          </select>
        </div>
        <div className="fld">
          <label htmlFor="sh-e">Ends</label>
          <input id="sh-e" className="in" value={formatDateTime(ends)} disabled />
        </div>
      </div>
      <Problems messages={shelve.isError ? errorMessages(shelve.error) : []} />
    </Dialog>
  );
}

function dueIn(days: number): string {
  const d = new Date(Date.now() + days * 86_400_000);
  return d.toISOString().slice(0, 10);
}

/** Create a case from alerts of one equipment: title, priority, assignee, due date and the
 * recommended tasks of the best-matching failure mode. */
export function CaseDialog({
  alerts,
  assetId,
  assetLabel,
  onClose,
}: {
  alerts: readonly Alert[];
  assetId: number;
  assetLabel: string;
  onClose: (done: boolean) => void;
}) {
  const navigate = useNavigate();
  const refresh = useRefresh();
  const first = alerts[0];
  const prio = [...alerts].map((a) => a.priority ?? "P4").sort()[0] ?? "P4";
  const diag = useQuery({
    queryKey: ["models", first?.model_id, "diagnosis", "now"],
    queryFn: ({ signal }) => fetchDiagnosis(first!.model_id, null, signal),
    enabled: !!first,
  });
  const top = diag.data?.modes.find((m) => !m.insufficient_evidence && (m.score ?? 0) > 0);
  const people = useQuery({
    queryKey: ["people", assetId],
    queryFn: ({ signal }) => fetchAssetPeople(assetId, signal),
  });
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState(prio);
  const [assignee, setAssignee] = useState<number | null>(null);
  const [due, setDue] = useState(dueIn(prio === "P1" ? 3 : prio === "P2" ? 7 : 14));
  const [tasks, setTasks] = useState(true);
  const shownTitle =
    title || (top ? `${assetLabel.split(" ")[0]} ${top.mode.name.toLowerCase()} suspected` : "");
  const create = useMutation({
    mutationFn: async () => {
      const made = await createCase(
        alerts.map((a) => a.id),
        shownTitle.trim() || null,
      );
      const patch: { priority?: string; assignee_id?: number; due?: string } = {};
      if (priority !== made.priority) patch.priority = priority;
      if (assignee !== null) patch.assignee_id = assignee;
      if (due) patch.due = due;
      if (Object.keys(patch).length) await updateCase(made.id, patch);
      if (tasks && top) await addModeTasks(made.id, top.mode.id);
      return made;
    },
    onSuccess: async (made) => {
      await refresh();
      onClose(true);
      void navigate(`/cases/${made.id}`);
    },
  });
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose(false)}
      title="Create case"
      footer={
        <>
          <button className="btn btn-s" type="button" onClick={() => onClose(false)}>
            Cancel
          </button>
          <button
            className="btn btn-p"
            type="button"
            disabled={create.isPending}
            onClick={() => create.mutate()}
          >
            Create case
          </button>
        </>
      }
    >
      <div className="fld">
        <label htmlFor="ca-t">Title</label>
        <input
          id="ca-t"
          className="in"
          value={shownTitle}
          placeholder={`${assetLabel}: describe the problem`}
          onChange={(e) => setTitle(e.target.value)}
        />
      </div>
      <div className="fg">
        <div className="fld">
          <label htmlFor="ca-e">Equipment</label>
          <input id="ca-e" className="in" value={assetLabel} disabled />
        </div>
        <div className="fld">
          <label htmlFor="ca-p">Priority</label>
          <select
            id="ca-p"
            className="sl"
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
          >
            {["P1", "P2", "P3", "P4"].map((p) => (
              <option key={p} value={p}>
                {p === prio ? `${p}, from the alert` : p}
              </option>
            ))}
          </select>
        </div>
        <div className="fld">
          <label htmlFor="ca-a">Assign to</label>
          <select
            id="ca-a"
            className="sl"
            value={assignee ?? ""}
            onChange={(e) => setAssignee(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">Unassigned</option>
            {(people.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name || p.username}
              </option>
            ))}
          </select>
        </div>
        <div className="fld">
          <label htmlFor="ca-d">Due</label>
          <input
            id="ca-d"
            className="in"
            type="date"
            value={due}
            onChange={(e) => setDue(e.target.value)}
          />
        </div>
      </div>
      {top && (
        <label className="chk">
          <input type="checkbox" checked={tasks} onChange={(e) => setTasks(e.target.checked)} />
          Add the recommended tasks of {top.mode.name.toLowerCase()}
        </label>
      )}
      <div className="notice">
        A frozen snapshot of the trends, contributors, failure-mode match and forecast is attached.
        Linked alerts: {alerts.map((a) => `A-${a.id}`).join(", ")}. Assigning moves the case to
        Investigating.
      </div>
      <Problems messages={create.isError ? errorMessages(create.error) : []} />
    </Dialog>
  );
}
