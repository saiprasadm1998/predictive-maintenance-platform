import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { fetchAsset } from "../../api/assets";
import {
  type CaseDetail,
  type CaseStatus,
  type Outcome,
  addAction,
  addAttachment,
  addComment,
  addModeTasks,
  attachmentUrl,
  closeCase,
  completeAction,
  fetchCase,
  fetchCasePeople,
  transitionCase,
  updateCase,
} from "../../api/cases";
import { errorMessages } from "../../api/client";
import { fetchLibrary } from "../../api/diagnostics";
import { formatDateTime } from "../../app/format";
import { caseStatusTone, OUTCOME_LABEL, alertState, shortTag } from "../../app/words";
import { Chart } from "../../components/Chart";
import {
  Dialog,
  Empty,
  IdChip,
  PageHeader,
  Panel,
  Pill,
  Problems,
  Tabs,
} from "../../components/ui";

const FLOW: CaseStatus[] = ["Open", "Investigating", "Action required", "Monitoring", "Closed"];
const KIND: Record<string, string> = {
  created: "Created",
  comment: "Comment",
  attachment: "Attachment",
  action: "Action",
  state_change: "Status",
  assignment: "Assignment",
  update: "Update",
  link: "Link",
  closure: "Closed",
};

function day(d: string | null): string {
  return d ? formatDateTime(new Date(`${d}T12:00:00`)).slice(0, 6) : "no date";
}

export function CasePage() {
  const { caseId } = useParams();
  const id = Number(caseId);
  const client = useQueryClient();
  const detail = useQuery({
    queryKey: ["cases", id],
    queryFn: ({ signal }) => fetchCase(id, signal),
  });
  const people = useQuery({
    queryKey: ["cases", id, "people"],
    queryFn: ({ signal }) => fetchCasePeople(id, signal),
  });
  const [closing, setClosing] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const act = useMutation({
    mutationFn: (run: () => Promise<CaseDetail>) => run(),
    onSuccess: (c) => {
      client.setQueryData(["cases", id], c);
      void client.invalidateQueries({ queryKey: ["cases"] });
      void client.invalidateQueries({ queryKey: ["alerts"] });
      void client.invalidateQueries({ queryKey: ["fleet"] });
    },
  });

  const c = detail.data;
  if (detail.isError) return <Problems messages={errorMessages(detail.error)} />;
  if (!c) return <p className="sec s13">Loading…</p>;
  const open = c.status !== "Closed" && c.status !== "Cancelled";
  const created = c.activities.find((a) => a.type === "created");
  const step = c.status === "Cancelled" ? -1 : FLOW.indexOf(c.status);
  const move = (to: Exclude<CaseStatus, "Open" | "Closed">) =>
    act.mutate(() => transitionCase(id, to));

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Cases", to: "/cases" }, { label: c.number }]}
        title={`${c.number} ${c.title}`}
        sub={
          <span className="chips" style={{ alignItems: "center" }}>
            <Pill tone={caseStatusTone(c.status, c.outcome)}>{c.status}</Pill>
            <IdChip to={`/assets/${c.asset_id}`}>{c.asset_code}</IdChip>
            <span>
              Opened {formatDateTime(new Date(c.created_at))}
              {created?.author ? ` by ${created.author}` : ""}
              {c.alert_ids.length
                ? ` from alert ${c.alert_ids.map((a) => `A-${a}`).join(", ")}`
                : ""}
            </span>
          </span>
        }
        actions={
          open ? (
            <>
              {c.status !== "Open" && (
                <button className="btn btn-g" type="button" onClick={() => setCancelling(true)}>
                  Cancel case
                </button>
              )}
              {c.status === "Investigating" && (
                <button
                  className="btn btn-s"
                  type="button"
                  disabled={act.isPending}
                  onClick={() => move("Action required")}
                >
                  Action required
                </button>
              )}
              {(c.status === "Investigating" || c.status === "Action required") && (
                <button
                  className="btn btn-s"
                  type="button"
                  disabled={act.isPending}
                  onClick={() => move("Monitoring")}
                >
                  Monitor
                </button>
              )}
              {c.status === "Monitoring" && (
                <button
                  className="btn btn-s"
                  type="button"
                  disabled={act.isPending}
                  onClick={() => move("Investigating")}
                >
                  Back to investigating
                </button>
              )}
              <button className="btn btn-p" type="button" onClick={() => setClosing(true)}>
                Close case
              </button>
            </>
          ) : undefined
        }
      />
      <Fields
        key={`${c.id}-${c.updated_at}`}
        c={c}
        people={people.data ?? []}
        onSave={(patch) => act.mutate(() => updateCase(id, patch))}
        saving={act.isPending}
      />
      <Problems messages={act.isError ? errorMessages(act.error) : []} />
      <div
        className="steps"
        style={{ ["--n" as string]: "5" }}
        role="list"
        aria-label="Case status"
      >
        {FLOW.map((s, i) => (
          <div
            key={s}
            role="listitem"
            className={`stp${i === step ? " on" : i < step ? " done" : ""}`}
            aria-current={i === step ? "step" : undefined}
          >
            <span className="n">{i < step ? "✓" : i + 1}</span>
            {s}
          </div>
        ))}
      </div>
      {c.status === "Cancelled" && <div className="notice warn">Cancelled: {c.cancel_reason}</div>}
      {c.status === "Closed" && (
        <div className="notice ok">
          Closed {c.closed_at ? formatDateTime(new Date(c.closed_at)) : ""} as{" "}
          {c.outcome ? OUTCOME_LABEL[c.outcome]?.toLowerCase() : "—"}
          {c.lessons ? `. Lessons: ${c.lessons}` : ""}
          {c.value_estimate ? `. Value ${c.value_estimate.toLocaleString()}` : ""}
        </div>
      )}
      <div className="two">
        <ActivityPanel
          c={c}
          open={open}
          people={people.data ?? []}
          onRun={(run) => act.mutate(run)}
          busy={act.isPending}
        />
        <div className="col">
          <ActionsPanel c={c} open={open} onRun={(run) => act.mutate(run)} />
          <Panel title={`Linked alert${c.snapshot.alerts.length === 1 ? "" : "s"}`}>
            {c.snapshot.alerts.map((a) => (
              <div key={a.id} className="li">
                <Pill>{a.priority ?? "—"}</Pill>
                <Link className="mono" to={`/alerts?alert=${a.id}`}>
                  A-{a.id}
                </Link>
                <span className="grow s13">
                  {a.kind === "di" ? "Deviation Index" : `${shortTag(a.tag ?? "")} residual`},{" "}
                  {a.severity.toLowerCase()}
                </span>
                <Pill tone={alertState(a.state).tone}>{alertState(a.state).label}</Pill>
              </div>
            ))}
          </Panel>
          <Snapshot c={c} />
        </div>
      </div>
      {closing && (
        <CloseDialog
          c={c}
          onClose={() => setClosing(false)}
          onDone={(updated) => client.setQueryData(["cases", id], updated)}
        />
      )}
      {cancelling && (
        <CancelDialog
          c={c}
          onClose={() => setCancelling(false)}
          onDone={(updated) => client.setQueryData(["cases", id], updated)}
        />
      )}
    </>
  );
}

function Fields({
  c,
  people,
  onSave,
  saving,
}: {
  c: CaseDetail;
  people: { id: number; username: string; display_name: string }[];
  onSave: (patch: {
    priority?: string;
    assignee_id?: number | null;
    due?: string | null;
    work_order?: string | null;
  }) => void;
  saving: boolean;
}) {
  const [priority, setPriority] = useState(c.priority);
  const [assignee, setAssignee] = useState<number | null>(c.assignee_id);
  const [due, setDue] = useState(c.due ?? "");
  const [wo, setWo] = useState(c.work_order ?? "");
  const open = c.status !== "Closed" && c.status !== "Cancelled";
  const changed =
    priority !== c.priority ||
    assignee !== c.assignee_id ||
    due !== (c.due ?? "") ||
    wo !== (c.work_order ?? "");
  return (
    <section className="pnl" aria-label="Case fields" style={{ padding: "12px 16px" }}>
      <div className="filters" style={{ alignItems: "flex-end" }}>
        <div className="fld">
          <label htmlFor="cs-p">Priority</label>
          <select
            id="cs-p"
            className="sl"
            style={{ width: 120 }}
            value={priority}
            disabled={!open}
            onChange={(e) => setPriority(e.target.value)}
          >
            {["P1", "P2", "P3", "P4"].map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </div>
        <div className="fld">
          <label htmlFor="cs-a">Assignee</label>
          <select
            id="cs-a"
            className="sl"
            style={{ width: 220 }}
            value={assignee ?? ""}
            disabled={!open}
            onChange={(e) => setAssignee(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">Unassigned</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name || p.username}
              </option>
            ))}
          </select>
        </div>
        <div className="fld">
          <label htmlFor="cs-d">Due</label>
          <input
            id="cs-d"
            className="in"
            type="date"
            style={{ width: 170 }}
            value={due}
            disabled={!open}
            onChange={(e) => setDue(e.target.value)}
          />
        </div>
        <div className="fld">
          <label htmlFor="cs-w">Work order</label>
          <input
            id="cs-w"
            className="in mono"
            style={{ width: 160 }}
            value={wo}
            maxLength={40}
            disabled={!open}
            placeholder="WO-"
            onChange={(e) => setWo(e.target.value)}
          />
        </div>
        <span className="grow" />
        {c.overdue && (
          <span className="pill p-danger" style={{ marginBottom: 10 }}>
            <span className="d" />
            Overdue
          </span>
        )}
        {open && (
          <button
            className="btn btn-s"
            type="button"
            disabled={!changed || saving}
            onClick={() => {
              const patch: {
                priority?: string;
                assignee_id?: number | null;
                due?: string | null;
                work_order?: string | null;
              } = {};
              if (priority !== c.priority) patch.priority = priority;
              if (assignee !== c.assignee_id) patch.assignee_id = assignee;
              if (due !== (c.due ?? "")) patch.due = due || null;
              if (wo !== (c.work_order ?? "")) patch.work_order = wo || null;
              onSave(patch);
            }}
          >
            Save fields
          </button>
        )}
      </div>
    </section>
  );
}

function ActivityPanel({
  c,
  open,
  people,
  onRun,
  busy,
}: {
  c: CaseDetail;
  open: boolean;
  people: { id: number; username: string; display_name: string }[];
  onRun: (run: () => Promise<CaseDetail>) => void;
  busy: boolean;
}) {
  const [kind, setKind] = useState<"comment" | "action" | "attachment">("comment");
  const [draft, setDraft] = useState("");
  const [owner, setOwner] = useState<number | null>(null);
  const [due, setDue] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const add = () => {
    const text = draft.trim();
    if (kind === "comment" && text) onRun(() => addComment(c.id, text));
    else if (kind === "action" && text) onRun(() => addAction(c.id, text, owner, due || null));
    else if (kind === "attachment" && file) onRun(() => addAttachment(c.id, file, text));
    else return;
    setDraft("");
    setFile(null);
  };
  const log = [...c.activities].reverse();
  return (
    <Panel title="Activity" id="lg-h" actions={<span className="meta">Newest first</span>}>
      {open && (
        <>
          <div style={{ marginBottom: 12 }}>
            <Tabs
              label="Entry type"
              value={kind}
              onChange={setKind}
              tabs={[
                { value: "comment", label: "Comment" },
                { value: "action", label: "Action" },
                { value: "attachment", label: "Attachment" },
              ]}
            />
          </div>
          <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
            {kind === "attachment" && (
              <input
                className="in"
                type="file"
                aria-label="File"
                style={{ paddingTop: 7 }}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            )}
            <input
              className="in"
              style={{ flex: 1, minWidth: 200 }}
              placeholder={
                kind === "comment"
                  ? "Add a comment"
                  : kind === "action"
                    ? "Describe the action"
                    : "What the file shows (optional)"
              }
              aria-label="New entry"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && add()}
            />
            {kind === "action" && (
              <>
                <select
                  className="sl"
                  aria-label="Owner"
                  style={{ width: 180 }}
                  value={owner ?? ""}
                  onChange={(e) => setOwner(e.target.value ? Number(e.target.value) : null)}
                >
                  <option value="">Owner</option>
                  {people.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.display_name || p.username}
                    </option>
                  ))}
                </select>
                <input
                  className="in"
                  type="date"
                  aria-label="Due"
                  style={{ width: 160 }}
                  value={due}
                  onChange={(e) => setDue(e.target.value)}
                />
              </>
            )}
            <button className="btn btn-s" type="button" disabled={busy} onClick={add}>
              Add
            </button>
          </div>
        </>
      )}
      <div className="fill">
        {log.map((e) => (
          <div key={e.id} className="li" style={{ alignItems: "flex-start" }}>
            <span className="meta num" style={{ width: 96, flex: "none", paddingTop: 2 }}>
              {formatDateTime(new Date(e.ts))}
            </span>
            <span className="grow">
              <b>{e.author ?? "System"}</b> <span className="bdg">{KIND[e.type] ?? e.type}</span>
              <br />
              <span className="s13">
                {e.type === "attachment" && e.attachment_id ? (
                  <a href={attachmentUrl(c.id, e.attachment_id)}>{e.body || "Attachment"}</a>
                ) : (
                  e.body
                )}
              </span>
            </span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function ActionsPanel({
  c,
  open,
  onRun,
}: {
  c: CaseDetail;
  open: boolean;
  onRun: (run: () => Promise<CaseDetail>) => void;
}) {
  const done = c.actions.filter((a) => a.status === "done").length;
  const modes = (c.snapshot.models[0]?.diagnosis ?? [])
    .filter((d) => d.mode_id && !d.insufficient_evidence)
    .slice(0, 2);
  return (
    <Panel
      title="Actions"
      id="ac-h"
      actions={
        <span className="meta">
          {done} of {c.actions.length} done
        </span>
      }
    >
      {c.actions.length === 0 && <p className="sec s13">No actions yet.</p>}
      {c.actions.map((a) => (
        <div key={a.id} className="li">
          <span className="grow s13">
            {a.description}
            <br />
            <span className="meta">
              {a.owner ?? "No owner"}, due {day(a.due)}
            </span>
          </span>
          {a.status === "done" ? (
            <span className="pill p-success">
              <span className="d" />
              Done {a.done_at ? formatDateTime(new Date(a.done_at)).slice(0, 6) : ""}
            </span>
          ) : open ? (
            <button
              className="btn btn-s btn-sm"
              type="button"
              onClick={() => onRun(() => completeAction(c.id, a.id))}
            >
              Mark done
            </button>
          ) : null}
        </div>
      ))}
      {open && modes.length > 0 && (
        <div className="filters" style={{ marginTop: 8 }}>
          {modes.map((m) => (
            <button
              key={m.mode_id}
              className="btn btn-s btn-sm"
              type="button"
              onClick={() => onRun(() => addModeTasks(c.id, m.mode_id!))}
            >
              Add tasks of {m.name}
            </button>
          ))}
        </div>
      )}
    </Panel>
  );
}

function Snapshot({ c }: { c: CaseDetail }) {
  const m = c.snapshot.models[0];
  if (!m) return null;
  const pts = (m.trend?.ts ?? []).map(
    (t, i) => [Date.parse(t), m.trend?.di[i] ?? null] as [number, number | null],
  );
  const health = m.trend?.health.filter((h) => h !== null).at(-1);
  const di = m.trend?.di.filter((h) => h !== null).at(-1);
  const top = [...(m.sensors ?? [])]
    .filter((s) => (s.contribution ?? 0) > 0)
    .sort((a, b) => (b.contribution ?? 0) - (a.contribution ?? 0))
    .slice(0, 3);
  const mode = m.diagnosis?.find((d) => !d.insufficient_evidence);
  return (
    <Panel
      title="Snapshot at creation"
      className="fill"
      actions={
        <span className="meta">{formatDateTime(new Date(c.snapshot.taken_at))}, frozen</span>
      }
    >
      {pts.length ? (
        <Chart
          from={pts[0]![0]}
          to={pts.at(-1)![0]}
          width={400}
          height={160}
          yMin={0}
          label="Deviation trend at case creation"
          series={[{ points: pts, cls: "pv" }]}
          limits={
            m.limits
              ? [
                  { value: m.limits.warning, cls: "lw" },
                  { value: m.limits.alert, cls: "la" },
                ]
              : []
          }
        />
      ) : (
        <Empty>No trend was stored.</Empty>
      )}
      <dl className="kvs" style={{ marginTop: 8 }}>
        <dt>Health</dt>
        <dd>
          {health === undefined || health === null ? "n/a" : Math.round(health)}
          {di !== undefined && di !== null ? `, deviation ${di.toFixed(1)} %` : ""}
        </dd>
        <dt>Contributors</dt>
        <dd>
          {top.length
            ? top
                .map(
                  (s) =>
                    `${shortTag(s.source_name ?? "")} ${Math.round((s.contribution ?? 0) * 100)} %`,
                )
                .join(", ")
            : "—"}
        </dd>
        <dt>Top mode</dt>
        <dd>{mode ? `${mode.name}, ${Math.round(mode.score ?? 0)} %` : "No clear match"}</dd>
        {m.forecast && (
          <>
            <dt>Forecast</dt>
            <dd>
              {m.forecast.valid
                ? `${m.forecast.urgency}, ${Math.round(m.forecast.lower_h ?? 0)} to ${m.forecast.upper_h === null ? "more" : Math.round(m.forecast.upper_h)} h`
                : "No trend to the limit"}
            </dd>
          </>
        )}
      </dl>
    </Panel>
  );
}

const BASIS = [
  "Avoided unplanned downtime",
  "Avoided secondary damage",
  "Planned instead of emergency repair",
  "None claimed",
];

function CloseDialog({
  c,
  onClose,
  onDone,
}: {
  c: CaseDetail;
  onClose: () => void;
  onDone: (c: CaseDetail) => void;
}) {
  const client = useQueryClient();
  const asset = useQuery({
    queryKey: ["assets", c.asset_id],
    queryFn: ({ signal }) => fetchAsset(c.asset_id, signal),
  });
  const modes = useQuery({
    queryKey: ["library", asset.data?.asset_type ?? null],
    queryFn: ({ signal }) => fetchLibrary(asset.data?.asset_type ?? null, false, signal),
    enabled: asset.isSuccess,
  });
  const [outcome, setOutcome] = useState<Outcome | "">("");
  const [mode, setMode] = useState("");
  const [value, setValue] = useState("");
  const [basis, setBasis] = useState(BASIS[0]!);
  const [lessons, setLessons] = useState("");
  const [tried, setTried] = useState(false);
  const close = useMutation({
    mutationFn: () =>
      closeCase(c.id, {
        outcome: outcome as Outcome,
        confirmed_mode_id: outcome === "true_finding" ? Number(mode) : null,
        value_estimate: value.trim() ? Number(value.replace(/[^\d.]/g, "")) : null,
        lessons:
          [lessons.trim(), value.trim() && basis !== "None claimed" ? `Value basis: ${basis}.` : ""]
            .filter(Boolean)
            .join(" ") || null,
      }),
    onSuccess: (updated) => {
      onDone(updated);
      void client.invalidateQueries({ queryKey: ["cases"] });
      void client.invalidateQueries({ queryKey: ["alerts"] });
      onClose();
    },
  });
  const valid = outcome !== "" && (outcome !== "true_finding" || mode !== "");
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Close case ${c.number}`}
      footer={
        <>
          <button className="btn btn-s" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-p"
            type="button"
            disabled={close.isPending}
            onClick={() => {
              setTried(true);
              if (valid) close.mutate();
            }}
          >
            Close case
          </button>
        </>
      }
    >
      <div className="fld">
        <label htmlFor="cl-o">Outcome (required)</label>
        <select
          id="cl-o"
          className="sl"
          value={outcome}
          onChange={(e) => setOutcome(e.target.value as Outcome | "")}
        >
          <option value="">Select an outcome</option>
          {Object.entries(OUTCOME_LABEL).map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        {tried && !outcome && (
          <span className="err">Select an outcome. A case cannot close without one.</span>
        )}
      </div>
      <div className="fld">
        <label htmlFor="cl-m">
          Confirmed failure mode{outcome === "true_finding" ? " (required)" : ""}
        </label>
        <select
          id="cl-m"
          className="sl"
          value={mode}
          disabled={outcome !== "true_finding"}
          onChange={(e) => setMode(e.target.value)}
        >
          <option value="">Select a failure mode</option>
          {(modes.data ?? []).map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
        {tried && outcome === "true_finding" && !mode && (
          <span className="err">A true finding needs the confirmed failure mode.</span>
        )}
      </div>
      <div className="fg">
        <div className="fld">
          <label htmlFor="cl-v">Estimated value of the finding</label>
          <input
            id="cl-v"
            className="in"
            inputMode="decimal"
            placeholder="For example 42000"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </div>
        <div className="fld">
          <label htmlFor="cl-b">Basis of the estimate</label>
          <select id="cl-b" className="sl" value={basis} onChange={(e) => setBasis(e.target.value)}>
            {BASIS.map((b) => (
              <option key={b}>{b}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="fld">
        <label htmlFor="cl-l">Lessons learned</label>
        <textarea
          id="cl-l"
          className="ta"
          placeholder="What did the data show, and how early?"
          value={lessons}
          onChange={(e) => setLessons(e.target.value)}
        />
      </div>
      {outcome === "false_alert" && (
        <div className="notice">
          A false alert asks the model engineer to review the {c.asset_code} limits.
        </div>
      )}
      {outcome === "known_condition" && (
        <div className="notice">
          A known condition is a reason to add that operating period to the training data and
          retrain the model.
        </div>
      )}
      <Problems messages={close.isError ? errorMessages(close.error) : []} />
    </Dialog>
  );
}

function CancelDialog({
  c,
  onClose,
  onDone,
}: {
  c: CaseDetail;
  onClose: () => void;
  onDone: (c: CaseDetail) => void;
}) {
  const client = useQueryClient();
  const [reason, setReason] = useState("");
  const cancel = useMutation({
    mutationFn: () => transitionCase(c.id, "Cancelled", reason.trim()),
    onSuccess: (updated) => {
      onDone(updated);
      void client.invalidateQueries({ queryKey: ["cases"] });
      onClose();
    },
  });
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Cancel case ${c.number}`}
      footer={
        <>
          <button className="btn btn-s" type="button" onClick={onClose}>
            Keep the case
          </button>
          <button
            className="btn btn-d"
            type="button"
            disabled={!reason.trim() || cancel.isPending}
            onClick={() => cancel.mutate()}
          >
            Cancel case
          </button>
        </>
      }
    >
      <p className="sec s13">
        A cancelled case keeps its record but has no outcome. Use it for duplicates or cases opened
        by mistake.
      </p>
      <div className="fld">
        <label htmlFor="cn-r">Reason (required)</label>
        <textarea
          id="cn-r"
          className="ta"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </div>
      <Problems messages={cancel.isError ? errorMessages(cancel.error) : []} />
    </Dialog>
  );
}
