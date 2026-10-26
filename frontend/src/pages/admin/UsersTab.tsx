import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  type AdminUser,
  ROLES,
  type RoleGrant,
  changeUser,
  createUser,
  fetchUsers,
} from "../../api/admin";
import { type Asset, fetchAllAssets } from "../../api/assets";
import { formatDateTime } from "../../app/format";
import { useAnnounce } from "../../app/liveContext";
import { useMe } from "../../app/session";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Skeleton } from "../fleet/FleetPage";
import { Field, Problems } from "../registry/common";
import { grantText, passwordProblems } from "./adminModel";
import { UnsavedChanges } from "../../components/UnsavedChanges";

type Editing = { kind: "new" } | { kind: "roles"; user: AdminUser } | null;
type Confirm = { kind: "active" | "password"; user: AdminUser } | null;

/** UC-17, FR-SEC-01: users, their roles (optionally limited to part of the hierarchy),
 * deactivation and password reset. Changes take effect on the user's next request. */
export function UsersTab() {
  const client = useQueryClient();
  const announce = useAnnounce();
  const me = useMe();
  const users = useQuery({ queryKey: ["users"], queryFn: ({ signal }) => fetchUsers(signal) });
  const assets = useQuery({
    queryKey: ["assets", "all"],
    queryFn: ({ signal }) => fetchAllAssets(signal),
  });
  const [editing, setEditing] = useState<Editing>(null);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [password, setPassword] = useState("");

  if (users.isPending) return <Skeleton rows={6} />;
  if (users.isError)
    return <p role="alert">The users could not be loaded: {users.error.message}</p>;
  const allAssets = assets.data ?? [];

  async function apply(patch: Parameters<typeof changeUser>[1], said: string) {
    await changeUser(confirm!.user.id, patch);
    announce(said);
    await client.invalidateQueries({ queryKey: ["users"] });
  }

  return (
    <div className="registry-split">
      <section className="panel" aria-labelledby="users-title">
        <div className="panel-head">
          <h2 id="users-title" className="panel-title">
            Users ({users.data.length})
          </h2>
          <button
            type="button"
            className="button button-small"
            onClick={() => setEditing({ kind: "new" })}
          >
            Add a user
          </button>
        </div>
        <table className="tree-table">
          <caption className="visually-hidden">Users and their roles</caption>
          <thead>
            <tr>
              <th scope="col">User</th>
              <th scope="col">Roles</th>
              <th scope="col">Status</th>
              <th scope="col">Last sign-in</th>
              <th scope="col">Change</th>
            </tr>
          </thead>
          <tbody>
            {users.data.map((u) => {
              const self = u.id === me.data?.id;
              const locked = u.locked_until && new Date(u.locked_until) > new Date();
              return (
                <tr key={u.id} className={u.active ? "" : "row-muted"}>
                  <td>
                    <strong>{u.username}</strong> {u.display_name !== u.username && u.display_name}
                    {u.email && <div className="muted small">{u.email}</div>}
                  </td>
                  <td>{u.roles.map((g) => grantText(g, allAssets)).join(", ")}</td>
                  <td>
                    {u.active ? "Active" : "Deactivated"}
                    {locked && ` · locked until ${formatDateTime(new Date(u.locked_until!))}`}
                  </td>
                  <td>{u.last_login_at ? formatDateTime(new Date(u.last_login_at)) : "Never"}</td>
                  <td>
                    <span className="lifecycle">
                      <button
                        type="button"
                        className="button button-small"
                        aria-label={`Roles of ${u.username}`}
                        onClick={() => setEditing({ kind: "roles", user: u })}
                      >
                        Roles
                      </button>
                      <button
                        type="button"
                        className="button button-small"
                        aria-label={`Reset the password of ${u.username}`}
                        onClick={() => setConfirm({ kind: "password", user: u })}
                      >
                        Reset password
                      </button>
                      {!self && (
                        <button
                          type="button"
                          className={`button button-small${u.active ? " button-danger-outline" : ""}`}
                          aria-label={`${u.active ? "Deactivate" : "Activate"} ${u.username}`}
                          onClick={() => setConfirm({ kind: "active", user: u })}
                        >
                          {u.active ? "Deactivate" : "Activate"}
                        </button>
                      )}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
      {editing && (
        <UserForm
          key={editing.kind === "new" ? "new" : editing.user.id}
          user={editing.kind === "roles" ? editing.user : null}
          assets={allAssets}
          onDone={() => setEditing(null)}
        />
      )}
      <ConfirmDialog
        open={confirm?.kind === "active"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={
          confirm
            ? `${confirm.user.active ? "Deactivate" : "Activate"} ${confirm.user.username}?`
            : ""
        }
        consequence={
          confirm?.user.active
            ? "They are signed out at once and cannot sign in until activated again. Their history stays."
            : "They can sign in again with their password."
        }
        confirmLabel={confirm?.user.active ? "Deactivate" : "Activate"}
        danger={confirm?.user.active}
        onConfirm={() =>
          apply(
            { active: !confirm!.user.active },
            `${confirm!.user.username} ${confirm!.user.active ? "deactivated" : "activated"}`,
          )
        }
      />
      <ConfirmDialog
        open={confirm?.kind === "password"}
        onOpenChange={(open) => {
          if (!open) {
            setConfirm(null);
            setPassword("");
          }
        }}
        title={confirm ? `Reset the password of ${confirm.user.username}?` : ""}
        consequence="Their sessions end and a lock after failed sign-ins is lifted. Give them the new password in person or by another safe route."
        confirmLabel="Reset password"
        onConfirm={async () => {
          const problems = passwordProblems(confirm!.user.username, password);
          if (problems.length) throw new Error(problems.join("; "));
          await apply({ password }, `Password of ${confirm!.user.username} reset`);
          setPassword("");
        }}
      >
        <Field label="New password">
          <input
            className="control"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
      </ConfirmDialog>
    </div>
  );
}

function UserForm({
  user,
  assets,
  onDone,
}: {
  user: AdminUser | null;
  assets: Asset[];
  onDone: () => void;
}) {
  const client = useQueryClient();
  const announce = useAnnounce();
  const [form, setForm] = useState({ username: "", display_name: "", email: "", password: "" });
  const [roles, setRoles] = useState<RoleGrant[]>(
    user?.roles ?? [{ role: "viewer", scope_asset_id: null }],
  );
  const [tried, setTried] = useState(false);
  const scopes = assets.filter((a) => a.level !== "equipment");
  const save = useMutation({
    mutationFn: () =>
      user
        ? changeUser(user.id, { roles })
        : createUser({
            username: form.username.trim(),
            display_name: form.display_name.trim() || form.username.trim(),
            email: form.email.trim() || null,
            password: form.password,
            roles,
          }),
    onSuccess: (saved) => {
      announce(`${saved.username} saved`);
      void client.invalidateQueries({ queryKey: ["users"] });
      onDone();
    },
  });
  const [snapshot] = useState(() => JSON.stringify({ form, roles }));
  const dirty = !save.isSuccess && JSON.stringify({ form, roles }) !== snapshot;
  const problems = [
    ...(!user && form.username.trim().length < 3
      ? ["The username needs at least 3 characters"]
      : []),
    ...(!user ? passwordProblems(form.username, form.password) : []),
    ...(roles.length ? [] : ["Give at least one role"]),
  ];

  return (
    <section className="panel registry-form" aria-labelledby="user-form-title">
      <h2 id="user-form-title" className="panel-title">
        {user ? `Roles of ${user.username}` : "Add a user"}
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
        {!user && (
          <>
            <Field label="Username">
              <input
                className="control"
                autoComplete="off"
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
              />
            </Field>
            <Field label="Display name">
              <input
                className="control"
                value={form.display_name}
                onChange={(e) => setForm({ ...form, display_name: e.target.value })}
              />
            </Field>
            <Field label="Email">
              <input
                className="control"
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
              />
            </Field>
            <Field label="Password">
              <input
                className="control"
                type="password"
                autoComplete="new-password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
              />
            </Field>
          </>
        )}
        <fieldset className="builder-wide builder-filters">
          <legend>Roles</legend>
          {roles.map((g, i) => (
            <div key={i} className="builder-row">
              <label className="field-inline">
                <span>Role {i + 1}</span>
                <select
                  className="control"
                  value={g.role}
                  onChange={(e) =>
                    setRoles(roles.map((r, j) => (j === i ? { ...r, role: e.target.value } : r)))
                  }
                >
                  {ROLES.map((r) => (
                    <option key={r.value} value={r.value}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field-inline">
                <span>on</span>
                <select
                  className="control"
                  aria-label={`Where role ${i + 1} applies`}
                  value={g.scope_asset_id ?? ""}
                  onChange={(e) =>
                    setRoles(
                      roles.map((r, j) =>
                        j === i
                          ? { ...r, scope_asset_id: e.target.value ? Number(e.target.value) : null }
                          : r,
                      ),
                    )
                  }
                >
                  <option value="">Everything</option>
                  {scopes.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.code} {a.name}
                    </option>
                  ))}
                </select>
              </label>
              {roles.length > 1 && (
                <button
                  type="button"
                  className="button button-small"
                  onClick={() => setRoles(roles.filter((_, j) => j !== i))}
                >
                  Remove role {i + 1}
                </button>
              )}
            </div>
          ))}
          <button
            type="button"
            className="button button-small"
            onClick={() => setRoles([...roles, { role: "viewer", scope_asset_id: null }])}
          >
            Add a role
          </button>
        </fieldset>
        <div className="builder-wide">
          <Problems problems={tried ? problems : []} error={save.error} />
          <div className="builder-buttons">
            <button type="button" className="button" onClick={onDone}>
              Cancel
            </button>
            <button type="submit" className="button button-primary" disabled={save.isPending}>
              {user ? "Save roles" : "Add user"}
            </button>
          </div>
        </div>
      </form>
    </section>
  );
}
