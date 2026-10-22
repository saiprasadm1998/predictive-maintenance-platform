import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { type Asset, fetchAllAssets } from "../../api/assets";
import {
  type AssetIn,
  CRITICALITIES,
  type Level,
  changeAsset,
  createAsset,
  fetchAssetTypes,
} from "../../api/registry";
import { useAnnounce } from "../../app/liveContext";
import { Skeleton } from "../fleet/FleetPage";
import { Field, Problems } from "./common";
import { childLevel, hierarchyRows, levelsBelow, parentChoices } from "./registryModel";

type Editing = { kind: "edit"; asset: Asset } | { kind: "add"; parent: Asset | null } | null;

/** FR-REG-01: the asset hierarchy, with edit, move and add. */
export function HierarchyTab({ editable }: { editable: boolean }) {
  const assets = useQuery({
    queryKey: ["assets", "all"],
    queryFn: ({ signal }) => fetchAllAssets(signal),
  });
  const [editing, setEditing] = useState<Editing>(null);
  if (assets.isPending) return <Skeleton rows={8} />;
  if (assets.isError)
    return <p role="alert">The hierarchy could not be loaded: {assets.error.message}</p>;
  const rows = hierarchyRows(assets.data);

  return (
    <div className="registry-split">
      <section className="panel" aria-labelledby="hierarchy-title">
        <div className="panel-head">
          <h2 id="hierarchy-title" className="panel-title">
            Hierarchy ({assets.data.length} assets)
          </h2>
          {editable && (
            <button
              type="button"
              className="button button-small"
              onClick={() => setEditing({ kind: "add", parent: null })}
            >
              Add a top-level asset
            </button>
          )}
        </div>
        <table className="tree-table">
          <caption className="visually-hidden">Assets in hierarchy order</caption>
          <thead>
            <tr>
              <th scope="col">Asset</th>
              <th scope="col">Level</th>
              <th scope="col">Type</th>
              <th scope="col">Criticality</th>
              {editable && <th scope="col">Change</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ asset, depth }) => (
              <tr
                key={asset.id}
                className={
                  editing?.kind === "edit" && editing.asset.id === asset.id ? "row-selected" : ""
                }
              >
                <td>
                  <span style={{ paddingLeft: depth * 18 }}>
                    <strong>{asset.code}</strong> {asset.name}
                  </span>
                </td>
                <td>{asset.level}</td>
                <td>{asset.asset_type ?? <span className="muted">—</span>}</td>
                <td>{asset.criticality ?? <span className="muted">—</span>}</td>
                {editable && (
                  <td>
                    <span className="lifecycle">
                      <button
                        type="button"
                        className="button button-small"
                        aria-label={`Edit ${asset.code}`}
                        onClick={() => setEditing({ kind: "edit", asset })}
                      >
                        Edit
                      </button>
                      {childLevel(asset.level) && (
                        <button
                          type="button"
                          className="button button-small"
                          aria-label={`Add under ${asset.code}`}
                          onClick={() => setEditing({ kind: "add", parent: asset })}
                        >
                          Add below
                        </button>
                      )}
                    </span>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {editing && (
        <AssetForm
          key={editing.kind === "edit" ? `e${editing.asset.id}` : `a${editing.parent?.id ?? 0}`}
          editing={editing}
          assets={assets.data}
          onDone={() => setEditing(null)}
        />
      )}
    </div>
  );
}

function AssetForm({
  editing,
  assets,
  onDone,
}: {
  editing: NonNullable<Editing>;
  assets: Asset[];
  onDone: () => void;
}) {
  const client = useQueryClient();
  const announce = useAnnounce();
  const types = useQuery({
    queryKey: ["asset-types"],
    queryFn: ({ signal }) => fetchAssetTypes(signal),
  });
  const current = editing.kind === "edit" ? editing.asset : null;
  const parentOf = (a: Asset) => assets.find((p) => p.id === a.parent_id)?.code ?? null;
  const [form, setForm] = useState<AssetIn>(
    current
      ? {
          code: current.code,
          name: current.name,
          level: current.level as Level,
          parent: parentOf(current),
          criticality: current.criticality,
          asset_type: current.asset_type,
          description: current.description,
        }
      : {
          code: "",
          name: "",
          level:
            editing.kind === "add" && editing.parent
              ? childLevel(editing.parent.level)!
              : "enterprise",
          parent: editing.kind === "add" ? (editing.parent?.code ?? null) : null,
          criticality: null,
          asset_type: null,
          description: "",
        },
  );
  const save = useMutation({
    mutationFn: () =>
      current
        ? changeAsset(current.id, {
            name: form.name,
            parent: form.parent,
            criticality: form.criticality,
            asset_type: form.asset_type,
            description: form.description,
          })
        : createAsset(form),
    onSuccess: (saved) => {
      announce(`${saved.code} saved`);
      void client.invalidateQueries({ queryKey: ["assets"] });
      onDone();
    },
  });
  const problems = [
    ...(!current && !form.code.trim() ? ["Code is required"] : []),
    ...(!form.name.trim() ? ["Name is required"] : []),
  ];
  const [tried, setTried] = useState(false);
  const equipment = form.level === "equipment";

  return (
    <section className="panel registry-form" aria-labelledby="asset-form-title">
      <h2 id="asset-form-title" className="panel-title">
        {current
          ? `Edit ${current.code}`
          : `New ${form.level}${form.parent ? ` under ${form.parent}` : ""}`}
      </h2>
      <form
        className="form-grid"
        onSubmit={(e) => {
          e.preventDefault();
          setTried(true);
          if (!problems.length) save.mutate();
        }}
      >
        {!current && (
          <Field label="Code">
            <input
              className="control"
              value={form.code}
              onChange={(e) => setForm({ ...form, code: e.target.value.trim() })}
            />
          </Field>
        )}
        {!current && (
          <Field label="Level">
            <select
              className="control"
              value={form.level}
              onChange={(e) => setForm({ ...form, level: e.target.value as Level })}
            >
              {levelsBelow(editing.kind === "add" ? (editing.parent?.level ?? null) : null).map(
                (l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ),
              )}
            </select>
          </Field>
        )}
        <Field label="Name">
          <input
            className="control"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </Field>
        {current && current.level !== "enterprise" && (
          <Field label="Parent (move)">
            <select
              className="control"
              value={form.parent ?? ""}
              onChange={(e) => setForm({ ...form, parent: e.target.value })}
            >
              {parentChoices(assets, current).map((a) => (
                <option key={a.id} value={a.code}>
                  {a.code} {a.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        {equipment && (
          <>
            <Field label="Asset type">
              <select
                className="control"
                value={form.asset_type ?? ""}
                onChange={(e) => setForm({ ...form, asset_type: e.target.value || null })}
              >
                <option value="">None</option>
                {(types.data ?? []).map((t) => (
                  <option key={t.code} value={t.code}>
                    {t.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Criticality">
              <select
                className="control"
                value={form.criticality ?? ""}
                onChange={(e) => setForm({ ...form, criticality: e.target.value || null })}
              >
                <option value="">Not set</option>
                {CRITICALITIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </Field>
          </>
        )}
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
              {current ? "Save" : "Add"}
            </button>
          </div>
        </div>
      </form>
    </section>
  );
}
