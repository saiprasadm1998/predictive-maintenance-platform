import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { type Asset, fetchAllAssets } from "../../api/assets";
import {
  type TagIn,
  changeTag,
  createTag,
  fetchAllTags,
  fetchAssetTypes,
  promoteUnmapped,
} from "../../api/registry";
import type { Tag } from "../../api/types";
import { useAnnounce } from "../../app/liveContext";
import { Skeleton } from "../fleet/FleetPage";
import { Field, Problems } from "./common";
import { emptyTag, tagProblems } from "./registryModel";
import { UnsavedChanges } from "../../components/UnsavedChanges";
import { useRowKeys } from "../../components/tableKeys";

const SHOWN = 500;

/** FR-REG-02: every registered tag, filtered by asset or text, with edit and register. */
export function TagsTab({ editable }: { editable: boolean }) {
  const rowKeys = useRowKeys();
  const tags = useQuery({
    queryKey: ["tags", "all"],
    queryFn: ({ signal }) => fetchAllTags(signal),
  });
  const assets = useQuery({
    queryKey: ["assets", "all"],
    queryFn: ({ signal }) => fetchAllAssets(signal),
  });
  const [asset, setAsset] = useState("");
  const [text, setText] = useState("");
  const [editing, setEditing] = useState<Tag | "new" | null>(null);
  const rows = useMemo(() => {
    const needle = text.trim().toLowerCase();
    return (tags.data ?? []).filter(
      (t) =>
        (!asset || t.asset_code === asset) &&
        (!needle ||
          t.source_name.toLowerCase().includes(needle) ||
          t.description.toLowerCase().includes(needle)),
    );
  }, [tags.data, asset, text]);

  if (tags.isPending || assets.isPending) return <Skeleton rows={8} />;
  if (tags.isError) return <p role="alert">The tags could not be loaded: {tags.error.message}</p>;
  const equipment = (assets.data ?? []).filter((a) => a.level === "equipment");

  return (
    <div className="registry-split">
      <section className="panel" aria-labelledby="tags-title">
        <div className="panel-head">
          <h2 id="tags-title" className="panel-title">
            Tags ({rows.length} of {tags.data.length})
          </h2>
          <div className="field-inline">
            <label className="field-inline">
              <span>Asset</span>
              <select className="control" value={asset} onChange={(e) => setAsset(e.target.value)}>
                <option value="">All</option>
                {equipment.map((a) => (
                  <option key={a.id} value={a.code}>
                    {a.code}
                  </option>
                ))}
              </select>
            </label>
            <label className="field-inline">
              <span>Search</span>
              <input
                className="control"
                type="search"
                value={text}
                onChange={(e) => setText(e.target.value)}
              />
            </label>
            {editable && (
              <button
                type="button"
                className="button button-small"
                onClick={() => setEditing("new")}
              >
                Register a tag
              </button>
            )}
          </div>
        </div>
        <table ref={rowKeys} className="tree-table">
          <caption className="visually-hidden">Registered tags</caption>
          <thead>
            <tr>
              <th scope="col">Tag</th>
              <th scope="col">Source</th>
              <th scope="col">Asset</th>
              <th scope="col">Description</th>
              <th scope="col">Unit</th>
              <th scope="col" className="num">
                Range
              </th>
              <th scope="col" className="num">
                Interval
              </th>
              <th scope="col">Role</th>
              {editable && <th scope="col">Change</th>}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, SHOWN).map((t) => (
              <tr key={t.id}>
                <td className="mono">{t.source_name}</td>
                <td>{t.source}</td>
                <td>{t.asset_code}</td>
                <td>{t.description}</td>
                <td>{t.unit}</td>
                <td className="num">
                  {t.range_lo} – {t.range_hi}
                </td>
                <td className="num">{t.interval_s} s</td>
                <td>{t.role ?? <span className="muted">—</span>}</td>
                {editable && (
                  <td>
                    <button
                      type="button"
                      className="button button-small"
                      aria-label={`Edit ${t.source_name}`}
                      onClick={() => setEditing(t)}
                    >
                      Edit
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length > SHOWN && (
          <p className="muted small">
            Showing the first {SHOWN} of {rows.length}; narrow the list by asset or search.
          </p>
        )}
      </section>
      {editing && (
        <TagForm
          key={editing === "new" ? "new" : editing.id}
          tag={editing === "new" ? null : editing}
          initial={editing === "new" ? emptyTag(tags.data[0]?.source ?? "", "", asset) : undefined}
          assets={equipment}
          onDone={() => setEditing(null)}
        />
      )}
    </div>
  );
}

/** Register (or, for an unmapped tag, promote) a tag, or change one. */
export function TagForm({
  tag,
  initial,
  assets,
  promote = false,
  onDone,
}: {
  tag: Tag | null;
  initial?: TagIn;
  assets: Asset[];
  promote?: boolean;
  onDone: () => void;
}) {
  const client = useQueryClient();
  const announce = useAnnounce();
  const types = useQuery({
    queryKey: ["asset-types"],
    queryFn: ({ signal }) => fetchAssetTypes(signal),
  });
  const [form, setForm] = useState<TagIn>(
    tag
      ? {
          source: tag.source,
          source_name: tag.source_name,
          asset: tag.asset_code,
          unit: tag.unit,
          range_lo: tag.range_lo,
          range_hi: tag.range_hi,
          interval_s: tag.interval_s,
          description: tag.description,
          role: tag.role,
        }
      : (initial ?? emptyTag()),
  );
  const [tried, setTried] = useState(false);
  const typeCode = assets.find((a) => a.code === form.asset)?.asset_type;
  const roles = types.data?.find((t) => t.code === typeCode)?.roles ?? [];
  const save = useMutation({
    mutationFn: () => {
      if (tag) {
        return changeTag(tag.id, {
          asset: form.asset,
          unit: form.unit,
          range_lo: form.range_lo,
          range_hi: form.range_hi,
          interval_s: form.interval_s,
          description: form.description,
          role: form.role,
        });
      }
      return promote ? promoteUnmapped(form) : createTag(form);
    },
    onSuccess: (saved) => {
      announce(`${saved.source_name} saved`);
      void client.invalidateQueries({
        predicate: (q) => ["tags", "unmapped"].includes(String(q.queryKey[0])),
      });
      onDone();
    },
  });
  const [snapshot] = useState(() => JSON.stringify(form));
  const dirty = !save.isSuccess && JSON.stringify(form) !== snapshot;
  const problems = tagProblems(form);
  const number = (key: "range_lo" | "range_hi" | "interval_s") => ({
    value: Number.isFinite(form[key]) ? form[key] : "",
    onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm({ ...form, [key]: e.target.value === "" ? Number.NaN : Number(e.target.value) }),
  });

  return (
    <section className="panel registry-form" aria-labelledby="tag-form-title">
      <h2 id="tag-form-title" className="panel-title">
        {tag ? `Edit ${tag.source_name}` : promote ? "Register an unmapped tag" : "Register a tag"}
      </h2>
      <UnsavedChanges dirty={dirty} />
      <form
        className="form-grid"
        onSubmit={(e) => {
          e.preventDefault();
          setTried(true);
          if (!problems.length) save.mutate();
        }}
      >
        <Field label="Source">
          <input
            className="control"
            value={form.source}
            disabled={!!tag || promote}
            onChange={(e) => setForm({ ...form, source: e.target.value })}
          />
        </Field>
        <Field label="Source name">
          <input
            className="control mono"
            value={form.source_name}
            disabled={!!tag || promote}
            onChange={(e) => setForm({ ...form, source_name: e.target.value })}
          />
        </Field>
        <Field label="Asset">
          <select
            className="control"
            value={form.asset}
            onChange={(e) => setForm({ ...form, asset: e.target.value, role: null })}
          >
            <option value="">Choose…</option>
            {assets.map((a) => (
              <option key={a.id} value={a.code}>
                {a.code} {a.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Role">
          <select
            className="control"
            value={form.role ?? ""}
            onChange={(e) => setForm({ ...form, role: e.target.value || null })}
          >
            <option value="">None</option>
            {roles.map((r) => (
              <option key={r.code} value={r.code}>
                {r.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Unit">
          <input
            className="control"
            value={form.unit}
            onChange={(e) => setForm({ ...form, unit: e.target.value })}
          />
        </Field>
        <Field label="Interval (s)">
          <input className="control" type="number" step={1} min={1} {...number("interval_s")} />
        </Field>
        <Field label="Range low">
          <input className="control" type="number" step="any" {...number("range_lo")} />
        </Field>
        <Field label="Range high">
          <input className="control" type="number" step="any" {...number("range_hi")} />
        </Field>
        <Field label="Description" wide>
          <input
            className="control"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </Field>
        <div className="builder-wide">
          <Problems problems={tried ? problems : []} error={save.error} />
          <div className="builder-buttons">
            <button type="button" className="button" onClick={onDone}>
              Cancel
            </button>
            <button type="submit" className="button button-primary" disabled={save.isPending}>
              {tag ? "Save" : "Register"}
            </button>
          </div>
        </div>
      </form>
    </section>
  );
}
