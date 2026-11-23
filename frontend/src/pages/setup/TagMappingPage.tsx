import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { errorMessages } from "../../api/client";
import { fetchLatest } from "../../api/models";
import { type Role, type Unmapped, changeTag, promoteUnmapped } from "../../api/registry";
import type { Tag } from "../../api/types";
import {
  Badge,
  Dialog,
  HowTo,
  Loading,
  PageHeader,
  Panel,
  Pill,
  Problems,
} from "../../components/ui";
import {
  defaultRange,
  type EquipmentSetup,
  roleKind,
  useEquipmentSetup,
  useUnmapped,
} from "./setupModel";

function downloadCsv(name: string, rows: (string | number)[][]) {
  const text = rows
    .map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(","))
    .join("\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

type Choice = { kind: "tag"; tag: Tag } | { kind: "unmapped"; item: Unmapped };

/** Pick the tag that fills one role: a tag already on the equipment, or one arriving unregistered. */
function ChooseTagDialog({
  row,
  role,
  unmapped,
  onClose,
}: {
  row: EquipmentSetup;
  role: Role;
  unmapped: Unmapped[];
  onClose: () => void;
}) {
  const client = useQueryClient();
  const free = row.tags.filter((t) => !t.role);
  const [value, setValue] = useState("");
  const d = defaultRange(role.unit);
  const [lo, setLo] = useState(String(d[0]));
  const [hi, setHi] = useState(String(d[1]));
  const choices: Choice[] = [
    ...free.map((tag) => ({ kind: "tag" as const, tag })),
    ...unmapped.map((item) => ({ kind: "unmapped" as const, item })),
  ];
  const chosen = choices.find(
    (c) =>
      (c.kind === "tag" ? `t:${c.tag.id}` : `u:${c.item.source}/${c.item.source_name}`) === value,
  );
  const save = useMutation({
    mutationFn: async () => {
      if (!chosen) return;
      if (chosen.kind === "tag") await changeTag(chosen.tag.id, { role: role.code });
      else
        await promoteUnmapped({
          source: chosen.item.source,
          source_name: chosen.item.source_name,
          asset: row.node.code,
          unit: role.unit,
          range_lo: Number(lo),
          range_hi: Number(hi),
          interval_s: 60,
          description: role.name,
          role: role.code,
        });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["tags"] });
      onClose();
    },
  });
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Tag for ${role.name}`}
      footer={
        <>
          <button className="btn btn-s" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-p"
            type="button"
            disabled={!chosen || save.isPending}
            onClick={() => save.mutate()}
          >
            Map tag
          </button>
        </>
      }
    >
      <p className="sec s13">
        {row.node.code} {row.node.name}. Choose the tag that measures {role.name.toLowerCase()} (
        {role.unit}).
      </p>
      <div className="fld">
        <label htmlFor="ct-tag">Tag</label>
        <select
          id="ct-tag"
          className="sl mono"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        >
          <option value="">Choose a tag</option>
          {free.length > 0 && (
            <optgroup label="On this equipment, no role yet">
              {free.map((t) => (
                <option key={t.id} value={`t:${t.id}`}>
                  {t.source_name}
                </option>
              ))}
            </optgroup>
          )}
          {unmapped.length > 0 && (
            <optgroup label="Arriving but not registered">
              {unmapped.map((u) => (
                <option
                  key={`${u.source}/${u.source_name}`}
                  value={`u:${u.source}/${u.source_name}`}
                >
                  {u.source_name}
                </option>
              ))}
            </optgroup>
          )}
        </select>
      </div>
      {chosen?.kind === "unmapped" && (
        <div className="fg">
          <div className="fld">
            <label htmlFor="ct-lo">Instrument range, low ({role.unit})</label>
            <input
              id="ct-lo"
              className="in num"
              value={lo}
              onChange={(e) => setLo(e.target.value)}
            />
          </div>
          <div className="fld">
            <label htmlFor="ct-hi">Instrument range, high ({role.unit})</label>
            <input
              id="ct-hi"
              className="in num"
              value={hi}
              onChange={(e) => setHi(e.target.value)}
            />
          </div>
        </div>
      )}
      {choices.length === 0 && (
        <p className="sec s13">
          No free tags. Register the tag first, or import the registry workbook.
        </p>
      )}
      <Problems messages={save.isError ? errorMessages(save.error) : []} />
    </Dialog>
  );
}

/** Register a tag that arrives without being known, and give it an equipment and role. */
function RegisterDialog({
  item,
  rows,
  onClose,
}: {
  item: Unmapped;
  rows: EquipmentSetup[];
  onClose: () => void;
}) {
  const client = useQueryClient();
  const [asset, setAsset] = useState("");
  const [roleCode, setRoleCode] = useState("");
  const row = rows.find((r) => r.node.code === asset);
  const role = row?.type?.roles.find((r) => r.code === roleCode);
  const [unit, setUnit] = useState("");
  const [lo, setLo] = useState("0");
  const [hi, setHi] = useState("100");
  const [description, setDescription] = useState("");
  const pickRole = (code: string) => {
    setRoleCode(code);
    const r = row?.type?.roles.find((x) => x.code === code);
    if (r) {
      const d = defaultRange(r.unit);
      setUnit(r.unit);
      setLo(String(d[0]));
      setHi(String(d[1]));
      setDescription(r.name);
    }
  };
  const save = useMutation({
    mutationFn: () =>
      promoteUnmapped({
        source: item.source,
        source_name: item.source_name,
        asset,
        unit: unit || role?.unit || "",
        range_lo: Number(lo),
        range_hi: Number(hi),
        interval_s: 60,
        description,
        role: roleCode || null,
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["tags"] });
      onClose();
    },
  });
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Register and map a tag"
      footer={
        <>
          <button className="btn btn-s" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-p"
            type="button"
            disabled={!asset || !unit || save.isPending}
            onClick={() => save.mutate()}
          >
            Register tag
          </button>
        </>
      }
    >
      <p className="s13">
        <span className="mono">{item.source_name}</span>{" "}
        <span className="sec">
          from {item.source}, {item.count.toLocaleString()} samples
        </span>
      </p>
      <div className="fg">
        <div className="fld">
          <label htmlFor="rg-a">Equipment</label>
          <select
            id="rg-a"
            className="sl"
            value={asset}
            onChange={(e) => {
              setAsset(e.target.value);
              setRoleCode("");
            }}
          >
            <option value="">Choose equipment</option>
            {rows.map((r) => (
              <option key={r.node.code} value={r.node.code}>
                {r.node.code} {r.node.name}
              </option>
            ))}
          </select>
        </div>
        <div className="fld">
          <label htmlFor="rg-r">Role</label>
          <select
            id="rg-r"
            className="sl"
            value={roleCode}
            disabled={!row}
            onChange={(e) => pickRole(e.target.value)}
          >
            <option value="">No role</option>
            {(row?.type?.roles ?? []).map((r) => (
              <option key={r.code} value={r.code}>
                {r.name}
              </option>
            ))}
          </select>
        </div>
        <div className="fld span2">
          <label htmlFor="rg-d">Description</label>
          <input
            id="rg-d"
            className="in"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div className="fld">
          <label htmlFor="rg-u">Unit</label>
          <input id="rg-u" className="in" value={unit} onChange={(e) => setUnit(e.target.value)} />
        </div>
        <div className="fld">
          <label htmlFor="rg-lo">Range, low and high</label>
          <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input
              id="rg-lo"
              className="in num"
              value={lo}
              onChange={(e) => setLo(e.target.value)}
              aria-label="Range low"
            />
            <span className="sec">to</span>
            <input
              className="in num"
              value={hi}
              onChange={(e) => setHi(e.target.value)}
              aria-label="Range high"
            />
          </span>
        </div>
      </div>
      <Problems messages={save.isError ? errorMessages(save.error) : []} />
    </Dialog>
  );
}

export function TagMappingPage() {
  const [params, setParams] = useSearchParams();
  const { rows, loading, tags } = useEquipmentSetup();
  const unmapped = useUnmapped();
  const [choose, setChoose] = useState<Role | null>(null);
  const [register, setRegister] = useState<Unmapped | null>(null);
  const selectedId = Number(params.get("asset")) || rows[0]?.node.id;
  const row = rows.find((r) => r.node.id === selectedId) ?? rows[0];
  const latest = useQuery({
    queryKey: ["models", row?.model?.id, "latest"],
    queryFn: ({ signal }) => fetchLatest(row!.model!.id, null, signal),
    enabled: !!row?.model?.in_service,
  });
  if (loading) return <Loading what="tags" />;

  const allTags = tags.data ?? [];
  const withRole = allTags.filter((t) => t.role).length;
  const value = (tagId: number) => {
    const s = latest.data?.sensors.find((x) => x.tag_id === tagId);
    return s?.actual == null ? "n/a" : `${s.actual.toFixed(1)} ${s.unit}`;
  };
  const exportCsv = () =>
    downloadCsv("tag-mapping.csv", [
      ["Equipment", "Tag", "Source", "Role", "Unit", "Range low", "Range high", "Description"],
      ...allTags.map((t) => [
        t.asset_code,
        t.source_name,
        t.source,
        t.role ?? "",
        t.unit,
        t.range_lo,
        t.range_hi,
        t.description,
      ]),
    ]);
  const pick = (id: number) => {
    params.set("asset", String(id));
    setParams(params, { replace: true });
  };
  const roles = row?.type?.roles ?? [];
  const required = new Set(row?.template?.required_roles ?? []);
  const extra = row ? row.tags.filter((t) => !t.role || !roles.some((r) => r.code === t.role)) : [];
  const waiting = unmapped.data ?? [];

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Setup overview", to: "/setup" }, { label: "Tags and mapping" }]}
        title="Tags and mapping"
        sub={`${withRole} of ${allTags.length} tags mapped to an equipment role`}
        actions={
          <>
            <HowTo title="Roles and tags">
              Each equipment type has roles: the positions a sensor can measure, such as drive-end
              bearing temperature. Mapping a tag to a role lets templates, models and failure modes
              find it. Required roles must be mapped before a model can be trained.
            </HowTo>
            <button className="btn btn-s" type="button" onClick={exportCsv}>
              Export mapping
            </button>
            <Link className="btn btn-s" to="/setup/hierarchy?import=1">
              Import workbook
            </Link>
          </>
        }
      />
      <div className="side3">
        <Panel title="Equipment" actions={<Badge>{rows.length}</Badge>}>
          <div
            style={{ display: "flex", flexDirection: "column", gap: 2 }}
            role="listbox"
            aria-label="Equipment"
          >
            {rows.map((r) => {
              const on = r.node.id === row?.node.id;
              return (
                <button
                  key={r.node.id}
                  type="button"
                  role="option"
                  aria-selected={on}
                  onClick={() => pick(r.node.id)}
                  className="lst"
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: 8,
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
                  <span style={{ minWidth: 0 }}>
                    <b className="mono">{r.node.code}</b>
                    <br />
                    <span className="sec s13">{r.node.name}</span>
                  </span>
                  {r.missingRequired.length ? (
                    <Badge tone="warning">Required missing</Badge>
                  ) : (
                    <Badge>
                      {r.rolesMapped} of {r.rolesTotal}
                    </Badge>
                  )}
                </button>
              );
            })}
          </div>
        </Panel>
        <div className="col">
          {row && (
            <Panel
              title={
                <>
                  {row.node.code} {row.node.name} {row.type && <Badge>{row.type.name}</Badge>}
                </>
              }
              actions={
                <Link
                  className="btn btn-s btn-sm"
                  to={`/setup/types${row.type ? `?type=${row.type.code}` : ""}`}
                >
                  Edit roles
                </Link>
              }
            >
              <div className="tw">
                <table className="tb">
                  <thead>
                    <tr>
                      <th>Role</th>
                      <th>Kind</th>
                      <th>Tag</th>
                      <th style={{ textAlign: "right" }}>Latest value</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {roles.map((r) => {
                      const tag = row.tags.find((t) => t.role === r.code);
                      const req = required.has(r.code);
                      return (
                        <tr key={r.code}>
                          <td>
                            <b>{r.name}</b> {req && <Badge>Required</Badge>}
                          </td>
                          <td>
                            <Badge>{roleKind(r.code)}</Badge>
                          </td>
                          <td className="mono">
                            {tag ? (
                              tag.source_name
                            ) : (
                              <button
                                className="btn btn-s btn-sm"
                                type="button"
                                onClick={() => setChoose(r)}
                              >
                                Choose tag
                              </button>
                            )}
                          </td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {tag ? value(tag.id) : "n/a"}
                          </td>
                          <td>
                            {tag ? (
                              <Pill>Mapped</Pill>
                            ) : req ? (
                              <Pill tone="warning">Required, missing</Pill>
                            ) : (
                              <Pill tone="unknown">Not mapped</Pill>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                    {extra.map((t) => (
                      <tr key={t.id}>
                        <td className="sec">{t.description || "No role"}</td>
                        <td>
                          <Badge>Other</Badge>
                        </td>
                        <td className="mono">{t.source_name}</td>
                        <td className="num" style={{ textAlign: "right" }}>
                          {value(t.id)}
                        </td>
                        <td>
                          <Pill tone="unknown">No role</Pill>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {roles.length === 0 && (
                <p className="sec s13" style={{ padding: 12 }}>
                  This equipment has no type, so it has no roles. Set its type in the equipment
                  register.
                </p>
              )}
            </Panel>
          )}
          <Panel
            title={
              <>
                Arriving but not registered{" "}
                <Badge tone={waiting.length ? "warning" : null}>{waiting.length}</Badge>
              </>
            }
          >
            {waiting.length === 0 ? (
              <p className="sec s13">Every tag arriving from the gateways is registered.</p>
            ) : (
              waiting.map((u) => (
                <div
                  key={`${u.source}/${u.source_name}`}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "6px 0",
                    borderTop: "1px solid var(--traverse-border-subtle)",
                  }}
                >
                  <b className="mono">{u.source_name}</b>
                  <span className="sec s13 grow">
                    {u.source}, first seen{" "}
                    {new Date(u.first_seen).toLocaleString("en-GB", {
                      day: "numeric",
                      month: "short",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                    , {u.count.toLocaleString()} samples
                  </span>
                  <button className="btn btn-p btn-sm" type="button" onClick={() => setRegister(u)}>
                    Register and map
                  </button>
                </div>
              ))
            )}
          </Panel>
        </div>
      </div>
      {choose && row && (
        <ChooseTagDialog
          row={row}
          role={choose}
          unmapped={waiting}
          onClose={() => setChoose(null)}
        />
      )}
      {register && <RegisterDialog item={register} rows={rows} onClose={() => setRegister(null)} />}
    </>
  );
}
