import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  type Direction,
  type FailureMode,
  type FailureModeIn,
  fetchLibrary,
  fetchModeVersions,
  retireMode,
  saveMode,
} from "../../api/diagnostics";
import { type AssetType, fetchAssetTypes } from "../../api/registry";
import { useBreadcrumbs } from "../../app/breadcrumbs";
import { formatDateTime } from "../../app/format";
import { useAnnounce } from "../../app/liveContext";
import { useMe } from "../../app/session";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { UnsavedChanges } from "../../components/UnsavedChanges";
import { ARROW, canEditLibrary, codeFrom } from "../diagnostics/diagnosticsModel";
import { Skeleton } from "../fleet/FleetPage";
import { Field, Problems } from "../registry/common";

type Editing = { kind: "new" } | { kind: "edit"; mode: FailureMode } | null;

/**
 * SCR-12 Failure-mode library (PDS §4.8, UC-16, FR-DIA-02, FR-ADV-01): asset types › modes
 * › symptoms and tasks, with each mode's version history. Model engineers add, edit (a new
 * version when something changed) and retire modes; diagnostics use the current version
 * from the next evaluation. Proposals from cases arrive in Release 3.
 */
export function LibraryPage() {
  useBreadcrumbs([{ label: "Failure-mode library" }]);
  const [params, setParams] = useSearchParams();
  const me = useMe();
  const may = canEditLibrary(me.data);
  const types = useQuery({
    queryKey: ["asset-types"],
    queryFn: ({ signal }) => fetchAssetTypes(signal),
  });
  const typeCode = params.get("type") ?? types.data?.[0]?.code ?? null;
  const showRetired = params.get("retired") === "true";
  const modes = useQuery({
    queryKey: ["library", typeCode, showRetired],
    queryFn: ({ signal }) => fetchLibrary(typeCode, showRetired, signal),
    enabled: typeCode !== null,
  });
  const [editing, setEditing] = useState<Editing>(null);
  const type = types.data?.find((t) => t.code === typeCode);

  function set(key: string, value: string | null) {
    setParams((current) => {
      const p = new URLSearchParams(current);
      if (value) p.set(key, value);
      else p.delete(key);
      return p;
    });
    setEditing(null);
  }

  if (types.isPending) return <Skeleton rows={6} />;
  if (types.isError)
    return <p role="alert">The asset types could not be loaded: {types.error.message}</p>;

  return (
    <div className="registry-split">
      <section className="pnl" aria-labelledby="library-title">
        <div className="pnlh">
          <h2 id="library-title" className="pt">
            Failure modes
          </h2>
          {may && type && (
            <button
              type="button"
              className="btn btn-s btn-sm"
              onClick={() => setEditing({ kind: "new" })}
            >
              Add a failure mode
            </button>
          )}
        </div>
        <div className="filter-bar">
          <label className="fld fld-inline">
            <span>Asset type</span>
            <select
              className="in"
              value={typeCode ?? ""}
              onChange={(e) => set("type", e.target.value)}
            >
              {types.data.map((t) => (
                <option key={t.code} value={t.code}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
          <label className="fld fld-inline">
            <input
              type="checkbox"
              checked={showRetired}
              onChange={(e) => set("retired", e.target.checked ? "true" : null)}
            />
            Show retired
          </label>
        </div>
        {modes.isPending ? (
          <Skeleton rows={4} />
        ) : modes.isError ? (
          <p role="alert">The library could not be loaded: {modes.error.message}</p>
        ) : modes.data.length === 0 ? (
          <p className="sec">No failure modes for this asset type yet.</p>
        ) : (
          <ul className="library-list">
            {modes.data.map((m) => (
              <li key={m.id}>
                <ModeCard
                  mode={m}
                  type={type}
                  may={may}
                  onEdit={() => setEditing({ kind: "edit", mode: m })}
                />
              </li>
            ))}
          </ul>
        )}
      </section>
      {editing && type && (
        <ModeForm
          key={editing.kind === "edit" ? editing.mode.id : "new"}
          type={type}
          mode={editing.kind === "edit" ? editing.mode : null}
          onDone={() => setEditing(null)}
        />
      )}
    </div>
  );
}

function ModeCard({
  mode: m,
  type,
  may,
  onEdit,
}: {
  mode: FailureMode;
  type: AssetType | undefined;
  may: boolean;
  onEdit: () => void;
}) {
  const client = useQueryClient();
  const announce = useAnnounce();
  const [retiring, setRetiring] = useState(false);
  const [history, setHistory] = useState(false);
  const versions = useQuery({
    queryKey: ["library", "versions", m.id],
    queryFn: ({ signal }) => fetchModeVersions(m.id, signal),
    enabled: history,
  });
  const role = (code: string) => type?.roles.find((r) => r.code === code)?.name ?? code;
  return (
    <article className="mode-card" aria-labelledby={`mode-${m.id}`}>
      <div className="pnlh">
        <h3 id={`mode-${m.id}`} className="pt">
          {m.name}
          {m.iso_code && <span className="sec s13"> · ISO 14224 {m.iso_code}</span>}
          <span className="sec s13"> · v{m.version}</span>
          {m.retired_at && <span className="sec s13"> · retired</span>}
        </h3>
        {may && (
          <span className="lifecycle">
            <button type="button" className="btn btn-s btn-sm" onClick={onEdit}>
              Edit
            </button>
            {!m.retired_at && (
              <button type="button" className="btn btn-d btn-sm" onClick={() => setRetiring(true)}>
                Retire
              </button>
            )}
          </span>
        )}
      </div>
      {m.description && <p className="sec">{m.description}</p>}
      <table className="tb">
        <caption className="sr">Symptoms of {m.name}</caption>
        <thead>
          <tr>
            <th scope="col">Symptom (role)</th>
            <th scope="col">Expected</th>
            <th scope="col" className="num">
              Weight
            </th>
          </tr>
        </thead>
        <tbody>
          {m.symptoms.map((s) => (
            <tr key={s.role}>
              <td>{role(s.role)}</td>
              <td>{ARROW[s.direction]}</td>
              <td className="num">{s.weight}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {m.tasks.length > 0 && (
        <>
          <h4 className="s13">Recommended tasks</h4>
          <ul className="task-list">
            {m.tasks.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </>
      )}
      <details onToggle={(e) => setHistory((e.target as HTMLDetailsElement).open)}>
        <summary>Version history</summary>
        {versions.isPending && history ? (
          <Skeleton rows={2} />
        ) : (
          <ol className="history">
            {(versions.data ?? []).map((v) => (
              <li key={v.version}>
                <b>v{v.version}</b> {formatDateTime(new Date(v.updated_at))}
                {v.comment ? ` · “${v.comment}”` : ""} · {v.symptoms.length} symptoms,{" "}
                {v.tasks.length} tasks
              </li>
            ))}
          </ol>
        )}
      </details>
      <ConfirmDialog
        open={retiring}
        onOpenChange={setRetiring}
        title={`Retire ${m.name}?`}
        consequence="Diagnostics stop showing this failure mode from the next evaluation. Its versions stay, and saving it again brings it back."
        confirmLabel="Retire"
        danger
        onConfirm={async () => {
          await retireMode(m.id);
          announce(`${m.name} retired`);
          await client.invalidateQueries({ queryKey: ["library"] });
        }}
      />
    </article>
  );
}

interface SymptomRow {
  role: string;
  direction: Direction;
  weight: string;
}

export function ModeForm({
  type,
  mode,
  onDone,
}: {
  type: AssetType;
  mode: FailureMode | null;
  onDone: () => void;
}) {
  const client = useQueryClient();
  const announce = useAnnounce();
  const [name, setName] = useState(mode?.name ?? "");
  const [iso, setIso] = useState(mode?.iso_code ?? "");
  const [description, setDescription] = useState(mode?.description ?? "");
  const [symptoms, setSymptoms] = useState<SymptomRow[]>(
    mode?.symptoms.map((s) => ({ ...s, weight: String(s.weight) })) ?? [
      { role: type.roles[0]?.code ?? "", direction: "up", weight: "1" },
    ],
  );
  const [tasks, setTasks] = useState(mode?.tasks.join("\n") ?? "");
  const [comment, setComment] = useState("");
  const [tried, setTried] = useState(false);
  const [initial] = useState(() => JSON.stringify({ name, iso, description, symptoms, tasks }));
  const body = (): FailureModeIn => ({
    asset_type: type.code,
    code: mode?.code ?? codeFrom(name),
    name: name.trim(),
    iso_code: iso.trim() || null,
    description: description.trim(),
    symptoms: symptoms.map((s) => ({
      role: s.role,
      direction: s.direction,
      weight: Number(s.weight),
    })),
    tasks: tasks
      .split("\n")
      .map((t) => t.trim())
      .filter(Boolean),
    comment: comment.trim(),
  });
  const save = useMutation({
    mutationFn: () => saveMode(body()),
    onSuccess: (saved) => {
      announce(`${saved.name} saved as version ${saved.version}`);
      void client.invalidateQueries({ queryKey: ["library"] });
      onDone();
    },
  });
  const roles = new Set(symptoms.map((s) => s.role));
  const problems = [
    ...(!name.trim() ? ["The name is required"] : []),
    ...(!mode && !codeFrom(name) ? ["The name needs letters or digits"] : []),
    ...(symptoms.length === 0 ? ["Give at least one symptom"] : []),
    ...(roles.size !== symptoms.length ? ["Each role may be used once"] : []),
    ...symptoms.flatMap((s, i) =>
      Number(s.weight) > 0 ? [] : [`Symptom ${i + 1}: the weight must be above 0`],
    ),
  ];
  const dirty =
    !save.isSuccess && JSON.stringify({ name, iso, description, symptoms, tasks }) !== initial;

  return (
    <section className="pnl registry-form" aria-labelledby="mode-form-title">
      <UnsavedChanges dirty={dirty} />
      <h2 id="mode-form-title" className="pt">
        {mode
          ? `Edit ${mode.name} (saves version ${mode.version + 1})`
          : `New failure mode · ${type.name}`}
      </h2>
      <form
        className="fg"
        onSubmit={(e) => {
          e.preventDefault();
          setTried(true);
          if (!problems.length) save.mutate();
        }}
      >
        <Field label="Name">
          <input className="in" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="ISO 14224 code">
          <input
            className="in"
            value={iso}
            placeholder="e.g. BRD, VIB, OHE"
            onChange={(e) => setIso(e.target.value)}
          />
        </Field>
        <Field label="Description">
          <input
            className="in"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        <fieldset className="builder-wide builder-filters">
          <legend>Symptoms</legend>
          {symptoms.map((s, i) => (
            <div key={i} className="builder-row">
              <label className="fld fld-inline">
                <span>Role {i + 1}</span>
                <select
                  className="in"
                  value={s.role}
                  onChange={(e) =>
                    setSymptoms(
                      symptoms.map((x, j) => (j === i ? { ...x, role: e.target.value } : x)),
                    )
                  }
                >
                  {type.roles.map((r) => (
                    <option key={r.code} value={r.code}>
                      {r.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="fld fld-inline">
                <span>Expected</span>
                <select
                  className="in"
                  aria-label={`Expected direction of symptom ${i + 1}`}
                  value={s.direction}
                  onChange={(e) =>
                    setSymptoms(
                      symptoms.map((x, j) =>
                        j === i ? { ...x, direction: e.target.value as Direction } : x,
                      ),
                    )
                  }
                >
                  <option value="up">↑ up</option>
                  <option value="down">↓ down</option>
                  <option value="any">any</option>
                </select>
              </label>
              <label className="fld fld-inline">
                <span>Weight</span>
                <input
                  className="in control-narrow"
                  aria-label={`Weight of symptom ${i + 1}`}
                  inputMode="decimal"
                  value={s.weight}
                  onChange={(e) =>
                    setSymptoms(
                      symptoms.map((x, j) => (j === i ? { ...x, weight: e.target.value } : x)),
                    )
                  }
                />
              </label>
              <button
                type="button"
                className="btn btn-s btn-sm"
                onClick={() => setSymptoms(symptoms.filter((_, j) => j !== i))}
              >
                Remove symptom {i + 1}
              </button>
            </div>
          ))}
          <button
            type="button"
            className="btn btn-s btn-sm"
            onClick={() =>
              setSymptoms([
                ...symptoms,
                {
                  role: type.roles.find((r) => !roles.has(r.code))?.code ?? type.roles[0]!.code,
                  direction: "up",
                  weight: "1",
                },
              ])
            }
          >
            Add a symptom
          </button>
        </fieldset>
        <Field label="Recommended tasks (one per line)">
          <textarea
            className="in"
            rows={4}
            value={tasks}
            onChange={(e) => setTasks(e.target.value)}
          />
        </Field>
        <Field label="Comment (kept with the version)">
          <input className="in" value={comment} onChange={(e) => setComment(e.target.value)} />
        </Field>
        <div className="builder-wide">
          <Problems problems={tried ? problems : []} error={save.error} />
          <div className="builder-buttons">
            <button type="button" className="btn btn-s" onClick={onDone}>
              Cancel
            </button>
            <button type="submit" className="btn btn-p" disabled={save.isPending}>
              Save
            </button>
          </div>
        </div>
      </form>
    </section>
  );
}
