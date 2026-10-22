import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { type AssetType, createAssetType, fetchAssetTypes, saveRole } from "../../api/registry";
import { useAnnounce } from "../../app/liveContext";
import { Skeleton } from "../fleet/FleetPage";
import { Field, Problems } from "./common";

const TYPE_CODE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,49}$/;
const ROLE_CODE = /^[a-z][a-z0-9_]{0,49}$/;

/** FR-REG-03: asset types and the roles their tags map to (used by templates and diagnostics). */
export function TypesTab({ editable }: { editable: boolean }) {
  const types = useQuery({
    queryKey: ["asset-types"],
    queryFn: ({ signal }) => fetchAssetTypes(signal),
  });
  const [adding, setAdding] = useState(false);
  if (types.isPending) return <Skeleton rows={6} />;
  if (types.isError)
    return <p role="alert">The asset types could not be loaded: {types.error.message}</p>;

  return (
    <div className="registry-types">
      <div className="builder-row">
        <p className="muted">
          A tag mapped to a role can be found by meaning (for example “drive-end bearing
          temperature”) on every asset of the type.
        </p>
        {editable && !adding && (
          <button type="button" className="button button-small" onClick={() => setAdding(true)}>
            Add an asset type
          </button>
        )}
      </div>
      {adding && <TypeForm onDone={() => setAdding(false)} />}
      {types.data.map((t) => (
        <TypePanel key={t.id} type={t} editable={editable} />
      ))}
    </div>
  );
}

function TypePanel({ type, editable }: { type: AssetType; editable: boolean }) {
  const [adding, setAdding] = useState(false);
  return (
    <section className="panel" aria-labelledby={`type-${type.id}`}>
      <div className="panel-head">
        <h2 id={`type-${type.id}`} className="panel-title">
          {type.name} <span className="mono muted">{type.code}</span>
        </h2>
        {editable && (
          <button type="button" className="button button-small" onClick={() => setAdding(true)}>
            Add a role to {type.name}
          </button>
        )}
      </div>
      {type.description && <p className="muted small">{type.description}</p>}
      <table className="summary-table">
        <caption className="visually-hidden">Roles of {type.name}</caption>
        <thead>
          <tr>
            <th scope="col">Role</th>
            <th scope="col">Code</th>
            <th scope="col">Unit</th>
          </tr>
        </thead>
        <tbody>
          {type.roles.map((r) => (
            <tr key={r.code}>
              <td>{r.name}</td>
              <td className="mono">{r.code}</td>
              <td>{r.unit || <span className="muted">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {adding && <RoleForm type={type} onDone={() => setAdding(false)} />}
    </section>
  );
}

function TypeForm({ onDone }: { onDone: () => void }) {
  const client = useQueryClient();
  const announce = useAnnounce();
  const [form, setForm] = useState({ code: "", name: "", description: "" });
  const [tried, setTried] = useState(false);
  const save = useMutation({
    mutationFn: () => createAssetType(form),
    onSuccess: (saved) => {
      announce(`Asset type ${saved.name} added`);
      void client.invalidateQueries({ queryKey: ["asset-types"] });
      onDone();
    },
  });
  const problems = [
    ...(TYPE_CODE.test(form.code) ? [] : ["Code: letters, digits, '.', '_' or '-'"]),
    ...(form.name.trim() ? [] : ["Name is required"]),
  ];
  return (
    <section className="panel" aria-label="New asset type">
      <form
        className="form-grid"
        onSubmit={(e) => {
          e.preventDefault();
          setTried(true);
          if (!problems.length) save.mutate();
        }}
      >
        <Field label="Type code">
          <input
            className="control mono"
            value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value.trim() })}
          />
        </Field>
        <Field label="Type name">
          <input
            className="control"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </Field>
        <Field label="Description" wide>
          <input
            className="control"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </Field>
        <FormButtons
          problems={tried ? problems : []}
          error={save.error}
          busy={save.isPending}
          onCancel={onDone}
          label="Add type"
        />
      </form>
    </section>
  );
}

function RoleForm({ type, onDone }: { type: AssetType; onDone: () => void }) {
  const client = useQueryClient();
  const announce = useAnnounce();
  const [form, setForm] = useState({ code: "", name: "", unit: "" });
  const [tried, setTried] = useState(false);
  const save = useMutation({
    mutationFn: () => saveRole(type.id, form),
    onSuccess: () => {
      announce(`Role ${form.name} added to ${type.name}`);
      void client.invalidateQueries({ queryKey: ["asset-types"] });
      onDone();
    },
  });
  const problems = [
    ...(ROLE_CODE.test(form.code)
      ? []
      : ["Code: lower-case letters, digits and _, starting with a letter"]),
    ...(form.name.trim() ? [] : ["Name is required"]),
  ];
  return (
    <form
      className="form-grid registry-inline-form"
      aria-label={`New role of ${type.name}`}
      onSubmit={(e) => {
        e.preventDefault();
        setTried(true);
        if (!problems.length) save.mutate();
      }}
    >
      <Field label="Role code">
        <input
          className="control mono"
          value={form.code}
          onChange={(e) => setForm({ ...form, code: e.target.value.trim() })}
        />
      </Field>
      <Field label="Role name">
        <input
          className="control"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
      </Field>
      <Field label="Unit">
        <input
          className="control"
          value={form.unit}
          onChange={(e) => setForm({ ...form, unit: e.target.value })}
        />
      </Field>
      <FormButtons
        problems={tried ? problems : []}
        error={save.error}
        busy={save.isPending}
        onCancel={onDone}
        label="Add role"
      />
    </form>
  );
}

function FormButtons({
  problems,
  error,
  busy,
  onCancel,
  label,
}: {
  problems: string[];
  error: unknown;
  busy: boolean;
  onCancel: () => void;
  label: string;
}) {
  return (
    <div className="builder-wide">
      <Problems problems={problems} error={error} />
      <div className="builder-buttons">
        <button type="button" className="button" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="button button-primary" disabled={busy}>
          {label}
        </button>
      </div>
    </div>
  );
}
