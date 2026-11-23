import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { type Asset, fetchAllAssets } from "../../api/assets";
import { errorMessages } from "../../api/client";
import { CRITICALITIES, type Level, changeAsset, createAsset } from "../../api/registry";
import { useMe } from "../../app/session";
import { Badge, Dialog, HowTo, Loading, PageHeader, Panel, Problems } from "../../components/ui";
import { ImportTab } from "../registry/ImportTab";
import { canEditRegistry, levelsBelow, parentChoices } from "../registry/registryModel";
import { useTypes } from "./setupModel";

const LEVEL_LABEL: Record<string, string> = {
  enterprise: "Enterprise",
  site: "Site",
  area: "Area",
  unit: "Unit",
  equipment: "Equipment",
};

function useAssets() {
  return useQuery({ queryKey: ["assets", "all"], queryFn: ({ signal }) => fetchAllAssets(signal) });
}

/** Add a level (or equipment) below a parent, or at the top. */
function AddDialog({ parent, onClose }: { parent: Asset | null; onClose: () => void }) {
  const client = useQueryClient();
  const types = useTypes();
  const levels = levelsBelow(parent?.level ?? null);
  const [level, setLevel] = useState<Level>(levels[0]!);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState("");
  const [crit, setCrit] = useState("B");
  const equipment = level === "equipment";
  const save = useMutation({
    mutationFn: () =>
      createAsset({
        code: code.trim(),
        name: name.trim(),
        level,
        parent: parent?.code ?? null,
        criticality: equipment ? crit : null,
        asset_type: equipment ? type || null : null,
        description: "",
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["assets"] });
      onClose();
    },
  });
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={parent ? `Add below ${parent.name}` : "Add a top level"}
      footer={
        <>
          <button className="btn btn-s" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-p"
            type="button"
            disabled={!code.trim() || !name.trim() || save.isPending}
            onClick={() => save.mutate()}
          >
            Add {LEVEL_LABEL[level]?.toLowerCase()}
          </button>
        </>
      }
    >
      <div className="fg">
        <div className="fld">
          <label htmlFor="ha-l">Level</label>
          <select
            id="ha-l"
            className="sl"
            value={level}
            onChange={(e) => setLevel(e.target.value as Level)}
          >
            {levels.map((l) => (
              <option key={l} value={l}>
                {LEVEL_LABEL[l]}
              </option>
            ))}
          </select>
        </div>
        <div className="fld">
          <label htmlFor="ha-c">Code</label>
          <input
            id="ha-c"
            className="in mono"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder={equipment ? "P-104C" : "SA-AMM"}
          />
        </div>
        <div className="fld span2">
          <label htmlFor="ha-n">Name</label>
          <input id="ha-n" className="in" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        {equipment && (
          <>
            <div className="fld">
              <label htmlFor="ha-t">Equipment type</label>
              <select
                id="ha-t"
                className="sl"
                value={type}
                onChange={(e) => setType(e.target.value)}
              >
                <option value="">Choose a type</option>
                {(types.data ?? []).map((t) => (
                  <option key={t.code} value={t.code}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="fld">
              <label htmlFor="ha-k">Criticality</label>
              <select
                id="ha-k"
                className="sl"
                value={crit}
                onChange={(e) => setCrit(e.target.value)}
              >
                {CRITICALITIES.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </div>
          </>
        )}
      </div>
      <Problems messages={save.isError ? errorMessages(save.error) : []} />
    </Dialog>
  );
}

/** The selected node: rename, re-type, move. */
function NodeEditor({
  node,
  assets,
  editable,
}: {
  node: Asset;
  assets: Asset[];
  editable: boolean;
}) {
  const client = useQueryClient();
  const types = useTypes();
  const [name, setName] = useState(node.name);
  const [parent, setParent] = useState(assets.find((a) => a.id === node.parent_id)?.code ?? "");
  const [type, setType] = useState(node.asset_type ?? "");
  const [crit, setCrit] = useState(node.criticality ?? "");
  const [moving, setMoving] = useState(false);
  const equipment = node.level === "equipment";
  const save = useMutation({
    mutationFn: () =>
      changeAsset(node.id, {
        name: name.trim(),
        parent: parent || null,
        ...(equipment ? { asset_type: type || null, criticality: crit || null } : {}),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["assets"] });
      setMoving(false);
    },
  });
  const parentName = assets.find((a) => a.code === parent)?.name ?? "None";
  return (
    <Panel
      title={node.name}
      actions={
        editable && (
          <>
            <button
              className="btn btn-s btn-sm"
              type="button"
              aria-pressed={moving}
              onClick={() => setMoving(!moving)}
            >
              Move
            </button>
            <button
              className="btn btn-s btn-sm"
              type="button"
              disabled={save.isPending}
              onClick={() => save.mutate()}
            >
              Save changes
            </button>
          </>
        )
      }
    >
      <div className="fg f4">
        <div className="fld">
          <label htmlFor="hn-n">Name</label>
          <input
            id="hn-n"
            className="in"
            value={name}
            disabled={!editable}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="fld">
          <label htmlFor="hn-c">Code</label>
          <input id="hn-c" className="in mono" value={node.code} disabled />
        </div>
        <div className="fld">
          <label htmlFor="hn-l">Level</label>
          <input id="hn-l" className="in" value={LEVEL_LABEL[node.level] ?? node.level} disabled />
        </div>
        <div className="fld">
          <label htmlFor="hn-p">Parent</label>
          {moving ? (
            <select
              id="hn-p"
              className="sl"
              value={parent}
              onChange={(e) => setParent(e.target.value)}
            >
              {parentChoices(assets, node).map((a) => (
                <option key={a.code} value={a.code}>
                  {a.name} ({LEVEL_LABEL[a.level]})
                </option>
              ))}
            </select>
          ) : (
            <input id="hn-p" className="in" value={parentName} disabled />
          )}
        </div>
        {equipment && (
          <>
            <div className="fld span2">
              <label htmlFor="hn-t">Equipment type</label>
              <select
                id="hn-t"
                className="sl"
                value={type}
                disabled={!editable}
                onChange={(e) => setType(e.target.value)}
              >
                <option value="">Not set</option>
                {(types.data ?? []).map((t) => (
                  <option key={t.code} value={t.code}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="fld">
              <label htmlFor="hn-k">Criticality</label>
              <select
                id="hn-k"
                className="sl"
                value={crit}
                disabled={!editable}
                onChange={(e) => setCrit(e.target.value)}
              >
                <option value="">Not set</option>
                {CRITICALITIES.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </div>
          </>
        )}
      </div>
      <Problems messages={save.isError ? errorMessages(save.error) : []} />
    </Panel>
  );
}

export function HierarchyPage() {
  const me = useMe();
  const editable = canEditRegistry(me.data);
  const [params, setParams] = useSearchParams();
  const assets = useAssets();
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState<{ parent: Asset | null } | null>(null);
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const importing = params.get("import") === "1";
  if (assets.isPending) return <Loading what="the plant hierarchy" />;

  const all = assets.data ?? [];
  const children = (id: number | null) => all.filter((a) => a.parent_id === id);
  const selected =
    all.find((a) => String(a.id) === params.get("node")) ??
    all.find((a) => a.level === "unit") ??
    all[0];
  const pick = (id: number) => {
    params.set("node", String(id));
    setParams(params, { replace: true });
  };
  const setImport = (on: boolean) => {
    if (on) params.set("import", "1");
    else params.delete("import");
    setParams(params, { replace: true });
  };
  const needle = q.trim().toLowerCase();
  const matches = (a: Asset): boolean =>
    !needle ||
    a.name.toLowerCase().includes(needle) ||
    a.code.toLowerCase().includes(needle) ||
    children(a.id).some(matches);
  const equipmentUnder = (a: Asset): number =>
    (a.level === "equipment" ? 1 : 0) + children(a.id).reduce((n, c) => n + equipmentUnder(c), 0);

  const renderTree = (parentId: number | null, depth: number): ReactNode =>
    children(parentId)
      .filter(matches)
      .map((a) => {
        const kids = children(a.id);
        const open = !collapsed.has(a.id) || !!needle;
        const on = a.id === selected?.id;
        return (
          <div key={a.id}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: `4px 8px 4px ${8 + depth * 14}px`,
                borderLeft: `3px solid ${on ? "var(--traverse-action-primary)" : "transparent"}`,
                borderRadius: 6,
                background: on ? "var(--traverse-surface-selected)" : undefined,
              }}
            >
              {kids.length > 0 ? (
                <button
                  type="button"
                  aria-label={open ? `Collapse ${a.name}` : `Expand ${a.name}`}
                  aria-expanded={open}
                  onClick={() => {
                    const next = new Set(collapsed);
                    if (open) next.add(a.id);
                    else next.delete(a.id);
                    setCollapsed(next);
                  }}
                  style={{
                    border: 0,
                    background: "transparent",
                    cursor: "pointer",
                    width: 16,
                    padding: 0,
                    color: "var(--traverse-text-secondary)",
                  }}
                >
                  {open ? "▾" : "▸"}
                </button>
              ) : (
                <span style={{ width: 16 }} />
              )}
              <button
                type="button"
                onClick={() => pick(a.id)}
                aria-current={on ? "true" : undefined}
                style={{
                  flex: 1,
                  minWidth: 0,
                  border: 0,
                  background: "transparent",
                  font: "inherit",
                  textAlign: "left",
                  cursor: "pointer",
                  color: on ? "var(--traverse-action-primary)" : "var(--traverse-text-primary)",
                  fontWeight: on ? 700 : 400,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {a.level === "equipment" ? `${a.code} ${a.name}` : a.name}
              </button>
              <span className="meta">{LEVEL_LABEL[a.level]}</span>
            </div>
            {open && renderTree(a.id, depth + 1)}
          </div>
        );
      });

  const below = selected ? children(selected.id) : [];
  return (
    <>
      <PageHeader
        crumbs={[{ label: "Setup overview", to: "/setup" }, { label: "Plant hierarchy" }]}
        title="Plant hierarchy"
        sub="Enterprise, site, area, unit and equipment positions (ISA-95)"
        actions={
          <>
            <HowTo title="Plant hierarchy">
              Build the tree from the top: site, area, unit, then equipment. Health rolls up from
              equipment to site, and a user's access can be limited to one branch.
            </HowTo>
            {editable && (
              <>
                <button className="btn btn-s" type="button" onClick={() => setImport(true)}>
                  Import registry
                </button>
                <button
                  className="btn btn-p"
                  type="button"
                  onClick={() => setAdding({ parent: null })}
                >
                  Add a level
                </button>
              </>
            )}
          </>
        }
      />
      {!editable && (
        <p className="notice">
          You can look at the registry; Model Engineers and Administrators change it.
        </p>
      )}
      <div className="side3">
        <Panel title="Tree" actions={<Badge>{all.length} nodes</Badge>}>
          <input
            className="in"
            placeholder="Find a node"
            aria-label="Find a node"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ marginBottom: 8 }}
          />
          {(() => {
            const items = renderTree(null, 0);
            return Array.isArray(items) && items.length === 0 ? (
              <p className="sec s13">
                {q.trim() ? "Nothing matches the search." : "No sites yet. Add one to start."}
              </p>
            ) : (
              <div role="group" aria-label="Plant hierarchy" style={{ fontSize: 13 }}>
                {items}
              </div>
            );
          })()}
        </Panel>
        <div className="col">
          {selected && (
            <NodeEditor
              key={`${selected.id}-${selected.name}-${selected.parent_id}`}
              node={selected}
              assets={all}
              editable={editable}
            />
          )}
          {selected && selected.level !== "equipment" && (
            <Panel
              title={`Below ${selected.name}`}
              actions={
                editable && (
                  <button
                    className="btn btn-s btn-sm"
                    type="button"
                    onClick={() => setAdding({ parent: selected })}
                  >
                    Add below
                  </button>
                )
              }
            >
              {below.length === 0 ? (
                <p className="sec s13">
                  Nothing below yet.{" "}
                  {selected.level === "unit" && (
                    <Link to="/setup/equipment/new">Add equipment step by step.</Link>
                  )}
                </p>
              ) : (
                <div className="tw">
                  <table className="tb">
                    <thead>
                      <tr>
                        <th>Name</th>
                        <th>Level</th>
                        <th>Code</th>
                        <th style={{ textAlign: "right" }}>Equipment</th>
                        <th>Criticality</th>
                      </tr>
                    </thead>
                    <tbody>
                      {below.map((a) => (
                        <tr key={a.id} onClick={() => pick(a.id)} style={{ cursor: "pointer" }}>
                          <td>
                            <b>{a.level === "equipment" ? `${a.code} ${a.name}` : a.name}</b>
                          </td>
                          <td>{LEVEL_LABEL[a.level]}</td>
                          <td className="mono sec">{a.code}</td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {equipmentUnder(a)}
                          </td>
                          <td>
                            {a.criticality ? (
                              <Badge>{a.criticality}</Badge>
                            ) : (
                              <span className="sec">n/a</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>
          )}
        </div>
      </div>
      {adding && <AddDialog parent={adding.parent} onClose={() => setAdding(null)} />}
      {importing && (
        <Dialog open wide onOpenChange={(o) => !o && setImport(false)} title="Import the registry">
          <div className="legacy">
            <ImportTab editable={editable} />
          </div>
        </Dialog>
      )}
    </>
  );
}
