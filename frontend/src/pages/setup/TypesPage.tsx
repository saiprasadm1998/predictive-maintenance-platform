import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { errorMessages } from "../../api/client";
import { type AssetType, createAssetType, saveRole } from "../../api/registry";
import { useMe } from "../../app/session";
import { Badge, Dialog, HowTo, Loading, PageHeader, Panel, Problems } from "../../components/ui";
import { canEditRegistry } from "../registry/registryModel";
import { roleKind, useEquipmentSetup } from "./setupModel";

function codeFrom(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}

function AddTypeDialog({ onClose }: { onClose: () => void }) {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const save = useMutation({
    mutationFn: () =>
      createAssetType({ code: codeFrom(name), name: name.trim(), description: description.trim() }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["asset-types"] });
      onClose();
    },
  });
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Add an equipment type"
      footer={
        <>
          <button className="btn btn-s" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-p"
            type="button"
            disabled={!name.trim() || save.isPending}
            onClick={() => save.mutate()}
          >
            Add type
          </button>
        </>
      }
    >
      <div className="fld">
        <label htmlFor="at-n">Name</label>
        <input
          id="at-n"
          className="in"
          placeholder="Centrifugal pump"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        {name.trim() && <span className="meta">Code: {codeFrom(name)}</span>}
      </div>
      <div className="fld">
        <label htmlFor="at-d">Description</label>
        <input
          id="at-d"
          className="in"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <Problems messages={save.isError ? errorMessages(save.error) : []} />
    </Dialog>
  );
}

function AddRoleDialog({ type, onClose }: { type: AssetType; onClose: () => void }) {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("");
  const save = useMutation({
    mutationFn: () =>
      saveRole(type.id, { code: codeFrom(name), name: name.trim(), unit: unit.trim() }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["asset-types"] });
      onClose();
    },
  });
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Add a role to ${type.name}`}
      footer={
        <>
          <button className="btn btn-s" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-p"
            type="button"
            disabled={!name.trim() || !unit.trim() || save.isPending}
            onClick={() => save.mutate()}
          >
            Add role
          </button>
        </>
      }
    >
      <div className="fg">
        <div className="fld">
          <label htmlFor="ar-n">Description</label>
          <input
            id="ar-n"
            className="in"
            placeholder="Drive-end bearing temperature"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          {name.trim() && <span className="meta">Role: {codeFrom(name)}</span>}
        </div>
        <div className="fld">
          <label htmlFor="ar-u">Unit</label>
          <input
            id="ar-u"
            className="in"
            placeholder="°C"
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
          />
        </div>
      </div>
      <Problems messages={save.isError ? errorMessages(save.error) : []} />
    </Dialog>
  );
}

export function TypesPage() {
  const me = useMe();
  const editable = canEditRegistry(me.data);
  const [params, setParams] = useSearchParams();
  const { rows, loading, types, templates, models } = useEquipmentSetup();
  const [addingType, setAddingType] = useState(false);
  const [addingRole, setAddingRole] = useState(false);
  if (loading) return <Loading what="equipment types" />;

  const all = types.data ?? [];
  const type = all.find((t) => t.code === params.get("type")) ?? all[0];
  const equipmentOf = (code: string) => rows.filter((r) => r.node.asset_type === code);
  const pick = (code: string) => {
    params.set("type", code);
    setParams(params, { replace: true });
  };
  const mine = type ? equipmentOf(type.code) : [];
  const typeTemplates = (templates.data ?? []).filter((t) => t.asset_type === type?.code);
  const required = new Set(typeTemplates.flatMap((t) => t.required_roles));
  const mapped = (role: string) => mine.filter((r) => r.tags.some((t) => t.role === role)).length;
  const modelsBuilt = (models.data ?? []).filter((m) =>
    mine.some((r) => r.node.code === m.asset_code),
  ).length;

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Setup overview", to: "/setup" }, { label: "Equipment types and roles" }]}
        title="Equipment types and roles"
        sub="A type lists the sensor roles its equipment has; templates build models from those roles"
        actions={
          <>
            <HowTo title="Types and roles">
              A role is a sensor position on a type of equipment, such as drive-end bearing
              temperature on a centrifugal pump. Tags are mapped to roles, so one failure mode and
              one model template serve every pump of the same type.
            </HowTo>
            {editable && (
              <button className="btn btn-p" type="button" onClick={() => setAddingType(true)}>
                Add a type
              </button>
            )}
          </>
        }
      />
      <div className="side3">
        <Panel title="Types" actions={<Badge>{all.length}</Badge>}>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {all.map((t) => {
              const on = t.code === type?.code;
              return (
                <button
                  key={t.code}
                  type="button"
                  aria-pressed={on}
                  onClick={() => pick(t.code)}
                  style={{
                    padding: "8px 12px",
                    border: 0,
                    borderLeft: `3px solid ${on ? "var(--traverse-action-primary)" : "transparent"}`,
                    borderRadius: 6,
                    background: on ? "var(--traverse-surface-selected)" : "transparent",
                    font: "inherit",
                    textAlign: "left",
                    cursor: "pointer",
                    color: "var(--traverse-text-primary)",
                  }}
                >
                  {t.name}
                  <br />
                  <span className="meta">
                    {t.roles.length} roles · {equipmentOf(t.code).length} equipment
                  </span>
                </button>
              );
            })}
          </div>
        </Panel>
        {type && (
          <div className="col">
            <Panel
              title={`${type.name}: roles`}
              actions={
                editable && (
                  <button
                    className="btn btn-s btn-sm"
                    type="button"
                    onClick={() => setAddingRole(true)}
                  >
                    Add a role
                  </button>
                )
              }
            >
              <div className="tw">
                <table className="tb">
                  <thead>
                    <tr>
                      <th>Role</th>
                      <th>Description</th>
                      <th>Unit</th>
                      <th>Kind</th>
                      <th>Required</th>
                      <th style={{ textAlign: "right" }}>Mapped</th>
                    </tr>
                  </thead>
                  <tbody>
                    {type.roles.map((r) => (
                      <tr key={r.code}>
                        <td className="mono">{r.code}</td>
                        <td>{r.name}</td>
                        <td className="sec">{r.unit}</td>
                        <td>
                          <Badge>{roleKind(r.code)}</Badge>
                        </td>
                        <td>{required.has(r.code) ? "Yes" : "No"}</td>
                        <td className="num" style={{ textAlign: "right" }}>
                          {mapped(r.code)} of {mine.length}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {type.roles.length === 0 && (
                <p className="sec s13">No roles yet. Add the sensor positions this type has.</p>
              )}
            </Panel>
            <Panel
              title={`Model templates for ${type.name}`}
              actions={
                <Link className="btn btn-s btn-sm" to="/models?apply=template">
                  Apply a template
                </Link>
              }
            >
              {typeTemplates.length === 0 ? (
                <p className="sec s13">
                  No template for this type. Models are built one by one in the model builder.
                </p>
              ) : (
                <div className="tw">
                  <table className="tb">
                    <thead>
                      <tr>
                        <th>Template</th>
                        <th>Algorithm</th>
                        <th>Roles used</th>
                        <th>Operating mode</th>
                        <th style={{ textAlign: "right" }}>Models on this type</th>
                      </tr>
                    </thead>
                    <tbody>
                      {typeTemplates.map((t) => {
                        const def = t.definition as { algorithm?: string; mode_filters?: string[] };
                        const used = t.required_roles.length + t.optional_roles.length;
                        return (
                          <tr key={t.id}>
                            <td>
                              <b>{t.description || t.name}</b>
                            </td>
                            <td className="mono">{def.algorithm ?? "aakr"}</td>
                            <td>
                              {used === type.roles.length
                                ? `All ${used} roles`
                                : `${used} of ${type.roles.length} roles`}
                            </td>
                            <td className="mono sec">
                              {(def.mode_filters ?? []).join("; ") || "none"}
                            </td>
                            <td className="num" style={{ textAlign: "right" }}>
                              {modelsBuilt}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>
          </div>
        )}
      </div>
      {addingType && <AddTypeDialog onClose={() => setAddingType(false)} />}
      {addingRole && type && <AddRoleDialog type={type} onClose={() => setAddingRole(false)} />}
    </>
  );
}
