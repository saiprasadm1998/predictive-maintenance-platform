import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { fetchUsers } from "../../api/admin";
import { errorMessages } from "../../api/client";
import {
  type FailureMode,
  fetchLibrary,
  fetchModeVersions,
  retireMode,
} from "../../api/diagnostics";
import { useMe } from "../../app/session";
import { Badge, Dialog, HowTo, Loading, PageHeader, Panel, Problems } from "../../components/ui";
import { canEditLibrary } from "../diagnostics/diagnosticsModel";
import { ModeForm } from "../library/LibraryPage";
import { useTypes } from "./setupModel";

const DIRECTION: Record<string, string> = { up: "Rise", down: "Fall", any: "Any" };
const stamp = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

type Editing = { mode: FailureMode | null } | null;

export function FailureModesPage() {
  const [params, setParams] = useSearchParams();
  const me = useMe();
  const may = canEditLibrary(me.data);
  const client = useQueryClient();
  const types = useTypes();
  const showRetired = params.get("retired") === "true";
  const all = useQuery({
    queryKey: ["library", "all", showRetired],
    queryFn: ({ signal }) => fetchLibrary(null, showRetired, signal),
  });
  const users = useQuery({
    queryKey: ["users"],
    queryFn: ({ signal }) => fetchUsers(signal),
    retry: false,
  });
  const [editing, setEditing] = useState<Editing>(null);
  const [retiring, setRetiring] = useState<FailureMode | null>(null);
  const typeCode = params.get("type") ?? types.data?.[0]?.code ?? null;
  const modes = (all.data ?? []).filter((m) => m.asset_type === typeCode);
  const selected = modes.find((m) => String(m.id) === params.get("mode")) ?? modes[0] ?? null;
  const versions = useQuery({
    queryKey: ["library", "versions", selected?.id],
    queryFn: ({ signal }) => fetchModeVersions(selected!.id, signal),
    enabled: !!selected,
  });
  const retire = useMutation({
    mutationFn: (m: FailureMode) => retireMode(m.id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["library"] });
      setRetiring(null);
    },
  });
  if (types.isPending || all.isPending) return <Loading what="the failure-mode library" />;

  const type = (types.data ?? []).find((t) => t.code === typeCode);
  const roleName = (code: string) =>
    type?.roles.find((r) => r.code === code)?.name ?? code.replace(/_/g, " ");
  const count = (code: string) =>
    (all.data ?? []).filter((m) => m.asset_type === code && !m.retired_at).length;
  const userName = (id: number | null) =>
    users.data?.find((u) => u.id === id)?.display_name ?? (id ? `User ${id}` : "System");
  const set = (key: string, value: string | null) => {
    if (value) params.set(key, value);
    else params.delete(key);
    if (key === "type") params.delete("mode");
    setParams(params, { replace: true });
  };
  const live = (all.data ?? []).filter((m) => !m.retired_at);
  const typesUsed = new Set(live.map((m) => m.asset_type)).size;

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Setup overview", to: "/setup" }, { label: "Failure modes" }]}
        title="Failure-mode library"
        sub={`${live.length} modes across ${typesUsed} equipment types, coded to ISO 14224`}
        actions={
          <>
            <HowTo title="Failure modes">
              Each mode lists the roles that move when it develops and in which direction. Diagnosis
              ranks the modes by how well the current deviations match. Changes create a new
              version; earlier diagnoses keep the version they used.
            </HowTo>
            {may && type && (
              <button
                className="btn btn-p"
                type="button"
                onClick={() => setEditing({ mode: null })}
              >
                Add a failure mode
              </button>
            )}
          </>
        }
      />
      <div className="side3">
        <Panel title="Equipment types">
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {(types.data ?? []).map((t) => {
              const on = t.code === typeCode;
              return (
                <button
                  key={t.code}
                  type="button"
                  onClick={() => set("type", t.code)}
                  aria-pressed={on}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "8px 12px",
                    border: 0,
                    borderLeft: `3px solid ${on ? "var(--traverse-action-primary)" : "transparent"}`,
                    borderRadius: 6,
                    background: on ? "var(--traverse-surface-selected)" : "transparent",
                    font: "inherit",
                    color: "var(--traverse-text-primary)",
                    cursor: "pointer",
                    textAlign: "left",
                  }}
                >
                  {t.name}
                  <Badge>{count(t.code)}</Badge>
                </button>
              );
            })}
          </div>
        </Panel>
        <div className="col">
          <Panel
            title={type?.name ?? "No type"}
            actions={
              <label className="chk">
                <input
                  type="checkbox"
                  checked={showRetired}
                  onChange={(e) => set("retired", e.target.checked ? "true" : null)}
                />
                Show retired
              </label>
            }
          >
            {modes.length === 0 ? (
              <p className="sec s13">No failure modes for this type yet.</p>
            ) : (
              <div className="tw">
                <table className="tb">
                  <thead>
                    <tr>
                      <th>Failure mode</th>
                      <th>ISO 14224</th>
                      <th style={{ textAlign: "right" }}>Symptoms</th>
                      <th style={{ textAlign: "right" }}>Checks</th>
                      <th>Version</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {modes.map((m) => {
                      const on = m.id === selected?.id;
                      return (
                        <tr
                          key={m.id}
                          onClick={() => set("mode", String(m.id))}
                          style={{
                            cursor: "pointer",
                            background: on ? "var(--traverse-surface-selected)" : undefined,
                            boxShadow: on
                              ? "inset 3px 0 0 var(--traverse-action-primary)"
                              : undefined,
                          }}
                          aria-selected={on}
                        >
                          <td>
                            <b>{m.name}</b> {m.retired_at && <Badge>Retired</Badge>}
                          </td>
                          <td>{m.iso_code ? <Badge>{m.iso_code}</Badge> : "n/a"}</td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {m.symptoms.length}
                          </td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {m.tasks.length}
                          </td>
                          <td className="mono sec">v{m.version}</td>
                          <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                            {may && !m.retired_at && (
                              <>
                                <button
                                  className="btn btn-s btn-sm"
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setEditing({ mode: m });
                                  }}
                                >
                                  Edit
                                </button>{" "}
                                <button
                                  className="btn btn-s btn-sm"
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setRetiring(m);
                                  }}
                                >
                                  Retire
                                </button>
                              </>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
          {selected && (
            <div className="half">
              <Panel title={`Symptoms of ${selected.name}`}>
                <div className="tw">
                  <table className="tb">
                    <thead>
                      <tr>
                        <th>Role</th>
                        <th>Direction</th>
                        <th style={{ textAlign: "right" }}>Weight</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selected.symptoms.map((s) => (
                        <tr key={s.role}>
                          <td>{roleName(s.role)}</td>
                          <td>{DIRECTION[s.direction] ?? s.direction}</td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {s.weight}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {selected.description && (
                  <p className="sec s13" style={{ marginTop: 12 }}>
                    {selected.description}
                  </p>
                )}
              </Panel>
              <Panel title="Checks">
                {selected.tasks.map((t, i) => (
                  <div
                    key={i}
                    className="s13"
                    style={{
                      padding: "8px 0",
                      borderBottom: "1px solid var(--traverse-border-subtle)",
                    }}
                  >
                    {t}
                  </div>
                ))}
                <span className="cap" style={{ marginTop: 16, marginBottom: 6 }}>
                  Version history
                </span>
                {(versions.data ?? []).map((v) => (
                  <div
                    key={v.version}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "32px minmax(0,1fr)",
                      gap: 8,
                      padding: "4px 0",
                    }}
                  >
                    <span className="mono sec">v{v.version}</span>
                    <span className="s13">
                      {v.comment || (v.version === 1 ? "Created" : "Changed")}
                      <br />
                      <span className="meta">
                        {userName(v.updated_by)}, {stamp(v.updated_at)}
                      </span>
                    </span>
                  </div>
                ))}
              </Panel>
            </div>
          )}
        </div>
      </div>
      {editing && type && (
        <Dialog
          open
          wide
          onOpenChange={(o) => !o && setEditing(null)}
          title={editing.mode ? `Edit ${editing.mode.name}` : `Add a failure mode to ${type.name}`}
        >
          <div className="legacy">
            <ModeForm type={type} mode={editing.mode} onDone={() => setEditing(null)} />
          </div>
        </Dialog>
      )}
      {retiring && (
        <Dialog
          open
          onOpenChange={(o) => !o && setRetiring(null)}
          title={`Retire ${retiring.name}?`}
          footer={
            <>
              <button className="btn btn-s" type="button" onClick={() => setRetiring(null)}>
                Keep it
              </button>
              <button
                className="btn btn-d"
                type="button"
                disabled={retire.isPending}
                onClick={() => retire.mutate(retiring)}
              >
                Retire
              </button>
            </>
          }
        >
          <p className="s13">
            Diagnosis stops ranking this mode. Cases that confirmed it keep their record, and it can
            be seen again with Show retired.
          </p>
          <Problems messages={retire.isError ? errorMessages(retire.error) : []} />
        </Dialog>
      )}
    </>
  );
}
