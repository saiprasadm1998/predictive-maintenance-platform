import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { fetchAsset } from "../../api/assets";
import {
  type CaseDetail,
  type CaseSnapshot,
  type Outcome,
  addAction,
  addAttachment,
  addComment,
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
import { useBreadcrumbs } from "../../app/breadcrumbs";
import { formatDateTime, formatIso } from "../../app/format";
import { useMe } from "../../app/session";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { TrendChart } from "../../components/TrendChart";
import { Skeleton } from "../fleet/FleetPage";
import { intervalText, medianText } from "../diagnostics/forecastModel";
import {
  CLOSABLE,
  MANUAL_TRANSITIONS,
  OUTCOMES,
  STEPS,
  activityText,
  canWorkOn,
  dueText,
  isOpen,
  outcomeLabel,
  statusClass,
  transitionLabel,
} from "./caseModel";

/**
 * SCR-05 Case detail (PDS §4.5, wireframe 05; UC-12, UC-13): header with priority,
 * assignee and due date, the status stepper of UCS Figure 7 with the allowed state changes,
 * the activity log with comments, actions and attachments, the linked alerts, the snapshot
 * taken at creation (immutable) and the closure form with its mandatory outcome.
 */
export function CasePage() {
  const id = Number(useParams().caseId);
  const client = useQueryClient();
  const me = useMe();
  const detail = useQuery({
    queryKey: ["cases", "detail", id],
    queryFn: ({ signal }) => fetchCase(id, signal),
    enabled: Number.isFinite(id),
  });
  const c = detail.data;
  const people = useQuery({
    queryKey: ["cases", "people", id],
    queryFn: ({ signal }) => fetchCasePeople(id, signal),
    enabled: !!c && isOpen(c.status),
  });
  useBreadcrumbs(c ? [{ label: "Cases", to: "/cases?open_only=true" }, { label: c.number }] : null);
  const change = useMutation({
    mutationFn: (action: () => Promise<CaseDetail>) => action(),
    onSuccess: (updated) => {
      client.setQueryData(["cases", "detail", id], updated);
      void client.invalidateQueries({
        predicate: (q) =>
          ["alerts", "fleet"].includes(String(q.queryKey[0])) ||
          (q.queryKey[0] === "cases" && q.queryKey[1] === "list"),
      });
    },
  });
  const [cancelling, setCancelling] = useState(false);

  if (detail.isPending) return <Skeleton rows={8} />;
  if (detail.isError)
    return <p role="alert">The case could not be loaded: {detail.error.message}</p>;
  if (!c) return null;
  const may = canWorkOn(me.data, c) && isOpen(c.status);

  return (
    <div className="case">
      <section className="panel case-head" aria-labelledby="case-title">
        <h2 id="case-title" className="case-title">
          {c.number} · {c.title}
        </h2>
        <div className="case-fields">
          <label className="field-inline">
            <span>Priority</span>
            <select
              className="control"
              value={c.priority}
              disabled={!may || change.isPending}
              onChange={(e) => {
                const priority = e.target.value;
                change.mutate(() => updateCase(id, { priority }));
              }}
            >
              {["P1", "P2", "P3", "P4"].map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
          <label className="field-inline">
            <span>Assignee</span>
            <select
              className="control"
              value={c.assignee_id ?? ""}
              disabled={!may || change.isPending}
              onChange={(e) => {
                const chosen = e.target.value ? Number(e.target.value) : null; // read now
                change.mutate(() => updateCase(id, { assignee_id: chosen }));
              }}
            >
              <option value="" disabled={c.status !== "Open"}>
                Unassigned
              </option>
              {c.assignee_id && !people.data?.some((p) => p.id === c.assignee_id) && (
                <option value={c.assignee_id}>{c.assignee}</option>
              )}
              {(people.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name}
                </option>
              ))}
            </select>
          </label>
          <label className="field-inline">
            <span>Due</span>
            <input
              className="control"
              type="date"
              value={c.due ?? ""}
              disabled={!may || change.isPending}
              onChange={(e) => {
                const due = e.target.value || null;
                change.mutate(() => updateCase(id, { due }));
              }}
            />
          </label>
          {c.overdue && <b className="overdue">Overdue</b>}
          <span className="filter-spacer" />
          {may &&
            MANUAL_TRANSITIONS[c.status].map((target) =>
              target === "Cancelled" ? (
                <button
                  key={target}
                  type="button"
                  className="button"
                  onClick={() => setCancelling(true)}
                >
                  {transitionLabel(target, c.status)}
                </button>
              ) : (
                <button
                  key={target}
                  type="button"
                  className="button"
                  disabled={change.isPending || (target === "Investigating" && !c.assignee_id)}
                  title={
                    target === "Investigating" && !c.assignee_id
                      ? "Assign the case first"
                      : undefined
                  }
                  onClick={() => change.mutate(() => transitionCase(id, target))}
                >
                  {transitionLabel(target, c.status)}
                </button>
              ),
            )}
        </div>
        <Stepper detail={c} />
        {change.isError && (
          <p role="alert" className="form-error">
            {errorMessages(change.error).join(" ")}
          </p>
        )}
        {c.status === "Cancelled" && (
          <p className="banner banner-watch" role="status">
            Cancelled: {c.cancel_reason}
          </p>
        )}
      </section>

      <div className="case-grid">
        <section className="panel" aria-labelledby="log-title">
          <h2 id="log-title" className="panel-title">
            Activity log
          </h2>
          <ol className="activity-log">
            {c.activities.map((a) => (
              <li key={a.id} className={`activity activity-${a.type}`}>
                <div className="activity-meta">
                  <time dateTime={a.ts} title={formatIso(new Date(a.ts))}>
                    {formatDateTime(new Date(a.ts))}
                  </time>{" "}
                  <span className="muted">{a.author ?? "PMP"}</span>
                </div>
                <div>
                  {activityText(a)}
                  {a.attachment_id && (
                    <>
                      {" "}
                      <a href={attachmentUrl(c.id, a.attachment_id)} download>
                        Download
                      </a>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ol>
          {may && (
            <AddActivity
              detail={c}
              people={people.data ?? []}
              busy={change.isPending}
              onRun={(action) => change.mutateAsync(action)}
            />
          )}
        </section>

        <div className="case-side">
          <section className="panel" aria-labelledby="actions-title">
            <h2 id="actions-title" className="panel-title">
              Actions
            </h2>
            {c.actions.length === 0 ? (
              <p className="muted">No action defined yet.</p>
            ) : (
              <ul className="task-list">
                {c.actions.map((a) => (
                  <li key={a.id}>
                    <span aria-hidden="true">{a.status === "done" ? "☑ " : "☐ "}</span>
                    {a.description}
                    <span className="muted small">
                      {a.owner ? ` · ${a.owner}` : ""}
                      {a.due ? ` · due ${dueText({ due: a.due, overdue: false })}` : ""}
                      {a.status === "done" && a.done_at
                        ? ` · done ${formatDateTime(new Date(a.done_at))}`
                        : ""}
                    </span>
                    {may && a.status === "open" && (
                      <button
                        type="button"
                        className="link-button"
                        disabled={change.isPending}
                        onClick={() => change.mutate(() => completeAction(id, a.id))}
                      >
                        Mark done
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="panel" aria-labelledby="linked-title">
            <h2 id="linked-title" className="panel-title">
              Linked alerts
            </h2>
            <ul className="case-list">
              {c.alert_ids.map((alertId) => {
                const was = c.snapshot.alerts.find((a) => a.id === alertId);
                return (
                  <li key={alertId}>
                    <Link to={`/assets/${c.asset_id}?alert=${alertId}`}>Alert {alertId}</Link>{" "}
                    <span className="muted">
                      {c.asset_code}
                      {was
                        ? ` · ${was.kind === "di" ? "DI" : (was.tag ?? "sensor")} ${was.severity.toLowerCase()} · ${was.priority ?? "—"} at creation`
                        : " · added later"}
                    </span>
                  </li>
                );
              })}
            </ul>
          </section>

          <Snapshot snapshot={c.snapshot} />

          <Closure detail={c} may={may} onClose={(closure) => change.mutateAsync(closure)} />
        </div>
      </div>

      <ConfirmDialog
        open={cancelling}
        onOpenChange={setCancelling}
        title={`Cancel ${c.number}`}
        consequence="A cancelled case is closed for good and its alerts can join another case."
        confirmLabel="Cancel case"
        danger
        reasonLabel="Reason (duplicate or invalid)"
        onConfirm={async (reason) => {
          await change.mutateAsync(() => transitionCase(id, "Cancelled", reason));
        }}
      />
    </div>
  );
}

function Stepper({ detail: c }: { detail: CaseDetail }) {
  const at = STEPS.indexOf(c.status);
  return (
    <ol className="case-stepper" aria-label="Case status">
      {STEPS.map((s, i) => (
        <li
          key={s}
          className={`step${i < at ? " step-done" : ""}${i === at ? " step-current" : ""}`}
          aria-current={i === at ? "step" : undefined}
        >
          <span className={`case-status case-status-${statusClass(s)}`}>{s}</span>
        </li>
      ))}
    </ol>
  );
}

type Kind = "comment" | "action" | "attachment";

function AddActivity({
  detail: c,
  people,
  busy,
  onRun,
}: {
  detail: CaseDetail;
  people: { id: number; display_name: string }[];
  busy: boolean;
  onRun: (action: () => Promise<CaseDetail>) => Promise<CaseDetail>;
}) {
  const [kind, setKind] = useState<Kind>("comment");
  const [text, setText] = useState("");
  const [owner, setOwner] = useState("");
  const [due, setDue] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const tooBig = !!file && file.size > 20 * 1024 * 1024;
  const ready = kind === "attachment" ? !!file && !tooBig : text.trim().length > 0;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    setError(null);
    try {
      if (kind === "comment") await onRun(() => addComment(c.id, text.trim()));
      if (kind === "action")
        await onRun(() => addAction(c.id, text.trim(), owner ? Number(owner) : null, due || null));
      if (kind === "attachment" && file) await onRun(() => addAttachment(c.id, file, text.trim()));
      setText("");
      setOwner("");
      setDue("");
      setFile(null);
    } catch (caught) {
      setError(errorMessages(caught).join(" "));
    }
  }

  return (
    <form className="add-activity" onSubmit={submit} aria-label="Add activity">
      <fieldset className="segmented">
        <legend className="visually-hidden">Activity type</legend>
        {(
          [
            ["comment", "Comment"],
            ["action", "Action"],
            ["attachment", "Attachment"],
          ] as const
        ).map(([value, label]) => (
          <label key={value}>
            <input
              type="radio"
              name="activity-type"
              value={value}
              checked={kind === value}
              onChange={() => setKind(value)}
            />
            {label}
          </label>
        ))}
      </fieldset>
      {kind === "attachment" && (
        <label className="field">
          <span>File (up to 20 MB)</span>
          <input
            type="file"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            aria-invalid={tooBig}
          />
          {tooBig && <span className="form-error">The file is larger than 20 MB.</span>}
        </label>
      )}
      <label className="field">
        <span>
          {kind === "action" ? "What to do" : kind === "attachment" ? "Note (optional)" : "Comment"}
        </span>
        <textarea className="control" value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      {kind === "action" && (
        <div className="field-row">
          <label className="field-inline">
            <span>Owner</span>
            <select className="control" value={owner} onChange={(e) => setOwner(e.target.value)}>
              <option value="">Nobody yet</option>
              {people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name}
                </option>
              ))}
            </select>
          </label>
          <label className="field-inline">
            <span>Due</span>
            <input
              className="control"
              type="date"
              value={due}
              onChange={(e) => setDue(e.target.value)}
            />
          </label>
        </div>
      )}
      {kind === "action" && (c.status === "Investigating" || c.status === "Monitoring") && (
        <p className="muted small">Adding an action makes the case Action required.</p>
      )}
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      <button type="submit" className="button button-primary" disabled={!ready || busy}>
        Add {kind}
      </button>
    </form>
  );
}

function Snapshot({ snapshot }: { snapshot: CaseSnapshot }) {
  return (
    <section className="panel" aria-labelledby="snapshot-title">
      <h2 id="snapshot-title" className="panel-title">
        Snapshot at creation
      </h2>
      <p className="muted small">
        Taken {formatDateTime(new Date(snapshot.taken_at))}; it does not change as new data arrives.
      </p>
      {snapshot.models.map((m) => {
        const ts = m.trend?.ts.map((t) => Date.parse(t)) ?? [];
        const sensors = m.sensors ?? [];
        const notGood = sensors.filter((s) => s.dq_status !== "Good");
        const forecast = m.forecast;
        return (
          <div key={m.model_id} className="snapshot-model">
            <h3 className="snapshot-head">
              {m.asset_code} / {m.model} v{m.version}
            </h3>
            {m.trend && ts.length > 0 && (
              <TrendChart
                title={`DI trend (snapshot) · ${m.asset_code}`}
                data={{
                  actual: ts.map((t, i) => [t, m.trend!.di[i] ?? null]),
                  limits: m.limits
                    ? { warning: [m.limits.warning], alert: [m.limits.alert] }
                    : undefined,
                }}
                settings={{
                  unit: "%",
                  from: ts[0]!,
                  to: ts.at(-1)!,
                  actualName: "Deviation Index",
                }}
                group={`snapshot-${m.model_id}`}
                height={160}
              />
            )}
            <h4 className="snapshot-sub">Contributors</h4>
            {sensors.length ? (
              <ul className="case-list">
                {sensors.slice(0, 5).map((s) => (
                  <li key={s.tag_id}>
                    {s.source_name ?? `tag ${s.tag_id}`}{" "}
                    <span className="muted">
                      {s.contribution === null ? "—" : `${Math.round(s.contribution)} %`}
                      {s.z === null ? "" : ` · z ${s.z > 0 ? "+" : ""}${s.z.toFixed(1)}`}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">Not scored at creation.</p>
            )}
            <h4 className="snapshot-sub">Failure-mode match</h4>
            {m.diagnosis?.length ? (
              <ul className="case-list">
                {m.diagnosis.map((d) => (
                  <li key={d.code}>
                    {d.name}{" "}
                    <span className="muted">
                      {d.insufficient_evidence || d.score === null
                        ? "insufficient evidence"
                        : `${Math.round(d.score)} %`}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No failure modes in the library for this asset type.</p>
            )}
            <h4 className="snapshot-sub">Forecast</h4>
            <p>
              {!forecast
                ? "No forecast had been run."
                : forecast.valid && forecast.median_h !== null && forecast.lower_h !== null
                  ? `${forecast.urgency} · ${intervalText(forecast.lower_h, forecast.upper_h)} (median ${medianText(forecast.median_h)}) to ${forecast.threshold}`
                  : "No trend to threshold"}
            </p>
            <h4 className="snapshot-sub">Data quality</h4>
            <p>
              {notGood.length === 0
                ? "Every sensor Good."
                : notGood
                    .map(
                      (s) =>
                        `${s.source_name ?? s.tag_id}: ${s.dq_status}${s.dq_rule ? ` (${s.dq_rule})` : ""}`,
                    )
                    .join("; ")}
            </p>
          </div>
        );
      })}
    </section>
  );
}

function Closure({
  detail: c,
  may,
  onClose,
}: {
  detail: CaseDetail;
  may: boolean;
  onClose: (action: () => Promise<CaseDetail>) => Promise<CaseDetail>;
}) {
  const [outcome, setOutcome] = useState<Outcome | "">("");
  const [mode, setMode] = useState("");
  const [value, setValue] = useState("");
  const [lessons, setLessons] = useState("");
  const [error, setError] = useState<string | null>(null);
  const asset = useQuery({
    queryKey: ["assets", "detail", c.asset_id],
    queryFn: ({ signal }) => fetchAsset(c.asset_id, signal),
    enabled: may,
  });
  const type = asset.data?.asset_type ?? null;
  const library = useQuery({
    queryKey: ["library", type, false],
    queryFn: ({ signal }) => fetchLibrary(type, false, signal),
    enabled: may && !!type,
  });

  if (c.status === "Closed") {
    return (
      <section className="panel" aria-labelledby="closure-title">
        <h2 id="closure-title" className="panel-title">
          Closure
        </h2>
        <dl className="closure-summary">
          <dt>Outcome</dt>
          <dd>{outcomeLabel(c.outcome)}</dd>
          {c.confirmed_mode_id && (
            <>
              <dt>Confirmed mode</dt>
              <dd>
                <Link to="/library">Failure mode {c.confirmed_mode_id}</Link>
              </dd>
            </>
          )}
          {c.value_estimate !== null && (
            <>
              <dt>Value estimate</dt>
              <dd>{c.value_estimate}</dd>
            </>
          )}
          <dt>Lessons learned</dt>
          <dd>{c.lessons ?? "—"}</dd>
        </dl>
        {c.review_requested && (
          <p className="muted small">
            Closed as a false alert: the model engineer is asked to review the limits or retrain.
          </p>
        )}
      </section>
    );
  }
  if (!may) return null;
  const closable = CLOSABLE.includes(c.status);
  const number = value.trim() === "" ? null : Number(value);
  const ready =
    closable &&
    outcome !== "" &&
    (outcome !== "true_finding" || mode !== "") &&
    (number === null || (Number.isFinite(number) && number >= 0));

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    setError(null);
    try {
      await onClose(() =>
        closeCase(c.id, {
          outcome,
          confirmed_mode_id: mode ? Number(mode) : null,
          value_estimate: number,
          lessons: lessons.trim() || null,
        }),
      );
    } catch (caught) {
      setError(errorMessages(caught).join(" "));
    }
  }

  return (
    <section className="panel" aria-labelledby="closure-title">
      <h2 id="closure-title" className="panel-title">
        Closure (required to close)
      </h2>
      {!closable && (
        <p className="muted small">A case is closed from Action required or Monitoring (UC-13).</p>
      )}
      <form className="closure-form" onSubmit={submit} aria-label="Close case">
        <label className="field">
          <span>Outcome</span>
          <select
            className="control"
            value={outcome}
            required
            onChange={(e) => setOutcome(e.target.value as Outcome | "")}
          >
            <option value="">Choose…</option>
            {OUTCOMES.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Confirmed mode{outcome === "true_finding" ? " (required)" : " (optional)"}</span>
          <select className="control" value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="">{type ? "Select from library…" : "No library for this asset"}</option>
            {(library.data ?? []).map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Value estimate (optional)</span>
          <input
            className="control"
            inputMode="decimal"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </label>
        <label className="field">
          <span>Lessons learned (optional)</span>
          <textarea
            className="control"
            value={lessons}
            onChange={(e) => setLessons(e.target.value)}
          />
        </label>
        {outcome === "false_alert" && (
          <p className="muted small">
            The model engineer will be asked to review the alert limits or retrain the model.
          </p>
        )}
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        <button type="submit" className="button button-primary" disabled={!ready}>
          Close case
        </button>
      </form>
    </section>
  );
}
