import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  type AdminUser,
  type ApiKey,
  type IssuedKey,
  type KeyScope,
  ROLES,
  type RoleGrant,
  changeUser,
  createUser,
  fetchApiKeys,
  fetchUsers,
  issueApiKey,
  revokeApiKey,
  rotateApiKey,
} from "../../api/admin";
import { fetchAllAssets } from "../../api/assets";
import { errorMessages } from "../../api/client";
import {
  Badge,
  Dialog,
  HowTo,
  Loading,
  PageHeader,
  Panel,
  Pill,
  Problems,
  Tabs,
} from "../../components/ui";
import { MIN_PASSWORD, passwordProblems, roleLabel } from "../admin/adminModel";

type Tab = "users" | "keys" | "roles";
const stamp = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString("en-GB", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Never";

const ROLE_RIGHTS: [string, string][] = [
  ["Viewer", "Sees everything in scope; changes nothing."],
  [
    "Reliability analyst",
    "Acknowledges and shelves alerts, runs forecasts, excludes sensors, opens and works on cases.",
  ],
  ["Maintenance", "Works on the cases assigned to them: actions, comments, attachments."],
  [
    "Model engineer",
    "Registry, history imports, data-quality rules, models, templates and the failure-mode library, plus everything an analyst does.",
  ],
  ["Administrator", "Every function, plus users, API keys, retention and the audit log."],
];

function useAssets() {
  return useQuery({ queryKey: ["assets", "all"], queryFn: ({ signal }) => fetchAllAssets(signal) });
}

function ScopeSelect({
  id,
  value,
  onChange,
}: {
  id: string;
  value: number | null;
  onChange: (v: number | null) => void;
}) {
  const assets = useAssets();
  const places = (assets.data ?? []).filter((a) => a.level !== "equipment");
  return (
    <select
      id={id}
      className="sl"
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
    >
      <option value="">All sites</option>
      {places.map((a) => (
        <option key={a.id} value={a.id}>
          {a.name} ({a.code})
        </option>
      ))}
    </select>
  );
}

function scopeText(grant: RoleGrant | undefined, names: Map<number, string>): string {
  if (!grant || grant.scope_asset_id === null) return "All sites";
  return names.get(grant.scope_asset_id) ?? `Asset ${grant.scope_asset_id}`;
}

function AddUserDialog({ onClose }: { onClose: () => void }) {
  const client = useQueryClient();
  const [username, setUsername] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("analyst");
  const [scope, setScope] = useState<number | null>(null);
  const [password, setPassword] = useState("");
  const [tried, setTried] = useState(false);
  const problems = [
    ...(username.trim() ? [] : ["Enter a user name"]),
    ...(name.trim() ? [] : ["Enter the person's name"]),
    ...passwordProblems(username, password),
  ];
  const save = useMutation({
    mutationFn: () =>
      createUser({
        username: username.trim(),
        display_name: name.trim(),
        email: email.trim() || null,
        password,
        roles: [{ role, scope_asset_id: scope }],
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["users"] });
      onClose();
    },
  });
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Add user"
      footer={
        <>
          <button className="btn btn-s" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-p"
            type="button"
            disabled={save.isPending}
            onClick={() => {
              setTried(true);
              if (!problems.length) save.mutate();
            }}
          >
            Add user
          </button>
        </>
      }
    >
      <div className="fg">
        <div className="fld">
          <label htmlFor="au-n">Name</label>
          <input id="au-n" className="in" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="fld">
          <label htmlFor="au-u">User name</label>
          <input
            id="au-u"
            className="in"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="off"
          />
        </div>
        <div className="fld span2">
          <label htmlFor="au-e">E-mail (for notifications)</label>
          <input
            id="au-e"
            className="in"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="fld">
          <label htmlFor="au-r">Role</label>
          <select id="au-r" className="sl" value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </div>
        <div className="fld">
          <label htmlFor="au-s">Scope</label>
          <ScopeSelect id="au-s" value={scope} onChange={setScope} />
        </div>
        <div className="fld span2">
          <label htmlFor="au-p">Temporary password (at least {MIN_PASSWORD} characters)</label>
          <input
            id="au-p"
            className="in"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
          />
        </div>
      </div>
      {tried && problems.length > 0 && <Problems messages={problems} />}
      <Problems messages={save.isError ? errorMessages(save.error) : []} />
    </Dialog>
  );
}

function RoleDialog({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const client = useQueryClient();
  const [role, setRole] = useState(user.roles[0]?.role ?? "viewer");
  const [scope, setScope] = useState<number | null>(user.roles[0]?.scope_asset_id ?? null);
  const save = useMutation({
    mutationFn: () => changeUser(user.id, { roles: [{ role, scope_asset_id: scope }] }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["users"] });
      onClose();
    },
  });
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Role of ${user.display_name}`}
      footer={
        <>
          <button className="btn btn-s" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-p"
            type="button"
            disabled={save.isPending}
            onClick={() => save.mutate()}
          >
            Save
          </button>
        </>
      }
    >
      <div className="fg">
        <div className="fld">
          <label htmlFor="ur-r">Role</label>
          <select id="ur-r" className="sl" value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </div>
        <div className="fld">
          <label htmlFor="ur-s">Scope</label>
          <ScopeSelect id="ur-s" value={scope} onChange={setScope} />
        </div>
      </div>
      <p className="sec s13">The change applies from the user's next request.</p>
      <Problems messages={save.isError ? errorMessages(save.error) : []} />
    </Dialog>
  );
}

function PasswordDialog({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const [password, setPassword] = useState("");
  const problems = passwordProblems(user.username, password);
  const save = useMutation({
    mutationFn: () => changeUser(user.id, { password }),
    onSuccess: onClose,
  });
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Reset password for ${user.display_name}`}
      footer={
        <>
          <button className="btn btn-s" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-p"
            type="button"
            disabled={problems.length > 0 || save.isPending}
            onClick={() => save.mutate()}
          >
            Reset password
          </button>
        </>
      }
    >
      <div className="fld">
        <label htmlFor="pw-n">New temporary password</label>
        <input
          id="pw-n"
          className="in"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="new-password"
        />
      </div>
      <p className="sec s13">Resetting unlocks the account and signs the user out everywhere.</p>
      {password && problems.length > 0 && <Problems messages={problems} />}
      <Problems messages={save.isError ? errorMessages(save.error) : []} />
    </Dialog>
  );
}

function IssueKeyDialog({ onClose }: { onClose: () => void }) {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [scope, setScope] = useState<KeyScope>("ingest");
  const [issued, setIssued] = useState<IssuedKey | null>(null);
  const [copied, setCopied] = useState(false);
  const save = useMutation({
    mutationFn: () => issueApiKey(name.trim(), scope),
    onSuccess: (key) => {
      setIssued(key);
      void client.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });
  if (issued)
    return (
      <Dialog
        open
        onOpenChange={(o) => !o && onClose()}
        title="Key shown once"
        footer={
          <button className="btn btn-p" type="button" onClick={onClose}>
            Done
          </button>
        }
      >
        <p className="s13">
          Copy the key now and store it in the gateway or system that uses it. It is not shown
          again.
        </p>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            className="in mono"
            readOnly
            value={issued.key}
            aria-label="API key"
            onFocus={(e) => e.target.select()}
          />
          <button
            className="btn btn-s"
            type="button"
            onClick={() =>
              void navigator.clipboard.writeText(issued.key).then(() => setCopied(true))
            }
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </Dialog>
    );
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Issue an API key"
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
            Issue key
          </button>
        </>
      }
    >
      <div className="fg">
        <div className="fld span2">
          <label htmlFor="ik-n">Name</label>
          <input
            id="ik-n"
            className="in"
            placeholder="Gateway site A"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="fld span2">
          <label htmlFor="ik-s">Scope</label>
          <select
            id="ik-s"
            className="sl"
            value={scope}
            onChange={(e) => setScope(e.target.value as KeyScope)}
          >
            <option value="ingest">Ingest: send samples and history (gateways)</option>
            <option value="results-read">Results read: health results for plant systems</option>
          </select>
        </div>
      </div>
      <Problems messages={save.isError ? errorMessages(save.error) : []} />
    </Dialog>
  );
}

function KeysTable() {
  const client = useQueryClient();
  const keys = useQuery({ queryKey: ["api-keys"], queryFn: ({ signal }) => fetchApiKeys(signal) });
  const [rotated, setRotated] = useState<IssuedKey | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  const rotate = useMutation({
    mutationFn: (k: ApiKey) => rotateApiKey(k.id),
    onSuccess: (k) => {
      setRotated(k);
      void client.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });
  const revoke = useMutation({
    mutationFn: (k: ApiKey) => revokeApiKey(k.id),
    onSuccess: () => {
      setRevoking(null);
      void client.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });
  if (keys.isPending) return <Loading what="keys" />;
  return (
    <>
      <div className="tw">
        <table className="tb">
          <caption className="sr">API keys</caption>
          <thead>
            <tr>
              <th>Name</th>
              <th>Key</th>
              <th>Scope</th>
              <th>Issued</th>
              <th>Last used</th>
              <th>Status</th>
              <th style={{ textAlign: "right" }}>Change</th>
            </tr>
          </thead>
          <tbody>
            {(keys.data ?? []).map((k) => (
              <tr key={k.id}>
                <td>
                  <b>{k.name}</b>
                </td>
                <td className="mono sec">{k.prefix}…</td>
                <td>
                  <Badge>{k.scope}</Badge>
                </td>
                <td>{stamp(k.created_at)}</td>
                <td>{stamp(k.last_used_at)}</td>
                <td>
                  {k.revoked_at ? (
                    <Pill tone="unknown">Revoked</Pill>
                  ) : (
                    <Pill tone="info">Active</Pill>
                  )}
                </td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  {!k.revoked_at && (
                    <>
                      <button
                        className="btn btn-s btn-sm"
                        type="button"
                        onClick={() => rotate.mutate(k)}
                      >
                        Rotate
                      </button>{" "}
                      <button
                        className="btn btn-g btn-sm"
                        type="button"
                        onClick={() => setRevoking(k)}
                      >
                        Revoke
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Problems messages={rotate.isError ? errorMessages(rotate.error) : []} />
      {rotated && (
        <Dialog
          open
          onOpenChange={(o) => !o && setRotated(null)}
          title="Key shown once"
          footer={
            <button className="btn btn-p" type="button" onClick={() => setRotated(null)}>
              Done
            </button>
          }
        >
          <p className="s13">
            The old key stops working now. Copy the new key; it is not shown again.
          </p>
          <input
            className="in mono"
            readOnly
            value={rotated.key}
            aria-label="API key"
            onFocus={(e) => e.target.select()}
          />
        </Dialog>
      )}
      {revoking && (
        <Dialog
          open
          onOpenChange={(o) => !o && setRevoking(null)}
          title={`Revoke ${revoking.name}?`}
          footer={
            <>
              <button className="btn btn-s" type="button" onClick={() => setRevoking(null)}>
                Keep it
              </button>
              <button
                className="btn btn-d"
                type="button"
                disabled={revoke.isPending}
                onClick={() => revoke.mutate(revoking)}
              >
                Revoke
              </button>
            </>
          }
        >
          <p className="s13">
            Anything using this key is refused from now on. This cannot be undone.
          </p>
          <Problems messages={revoke.isError ? errorMessages(revoke.error) : []} />
        </Dialog>
      )}
    </>
  );
}

export function UsersPage() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab | null) ?? "users";
  const client = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: ({ signal }) => fetchUsers(signal) });
  const assets = useAssets();
  const [adding, setAdding] = useState(false);
  const [issuing, setIssuing] = useState(false);
  const [roleOf, setRoleOf] = useState<AdminUser | null>(null);
  const [passwordOf, setPasswordOf] = useState<AdminUser | null>(null);
  const toggle = useMutation({
    mutationFn: (u: AdminUser) => changeUser(u.id, { active: !u.active }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["users"] }),
  });
  const names = new Map((assets.data ?? []).map((a) => [a.id, a.name]));
  const setTab = (t: Tab) => {
    params.set("tab", t);
    setParams(params, { replace: true });
  };
  const [now] = useState(() => Date.now());
  return (
    <>
      <PageHeader
        title="Users and roles"
        sub="Five roles; access can be limited to part of the plant. Five failed sign-ins lock an account for 15 minutes."
        actions={
          <>
            <HowTo title="Users and roles">
              Each person has one role, optionally limited to a site, area or unit. Gateways and
              plant systems use API keys instead of user accounts.
            </HowTo>
            {tab === "keys" ? (
              <button className="btn btn-p" type="button" onClick={() => setIssuing(true)}>
                Issue a key
              </button>
            ) : (
              <button className="btn btn-p" type="button" onClick={() => setAdding(true)}>
                Add user
              </button>
            )}
          </>
        }
      />
      <Tabs
        label="Users and access"
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "users", label: "Users" },
          { value: "keys", label: "API keys" },
          { value: "roles", label: "Roles" },
        ]}
      />
      <Panel className="fill">
        {tab === "users" &&
          (users.isPending ? (
            <Loading what="users" />
          ) : (
            <div className="tw">
              <table className="tb">
                <thead>
                  <tr>
                    <th>User</th>
                    <th>Role</th>
                    <th>Scope</th>
                    <th>Status</th>
                    <th>Last sign-in</th>
                    <th style={{ textAlign: "right" }}>Change</th>
                  </tr>
                </thead>
                <tbody>
                  {(users.data ?? []).map((u) => {
                    const locked = u.locked_until && Date.parse(u.locked_until) > now;
                    return (
                      <tr key={u.id}>
                        <td>
                          <b>{u.display_name}</b>
                          <br />
                          <span className="meta">{u.email ?? u.username}</span>
                        </td>
                        <td>
                          {u.roles.map((r, i) => (
                            <Badge key={i}>{roleLabel(r.role)}</Badge>
                          ))}
                        </td>
                        <td>{scopeText(u.roles[0], names)}</td>
                        <td>
                          {!u.active ? (
                            <Pill tone="unknown">Inactive</Pill>
                          ) : locked ? (
                            <Pill tone="warning">Locked, failed sign-ins</Pill>
                          ) : (
                            <Pill tone="info">Active</Pill>
                          )}
                        </td>
                        <td>{stamp(u.last_login_at)}</td>
                        <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                          <button
                            className="btn btn-s btn-sm"
                            type="button"
                            onClick={() => setRoleOf(u)}
                          >
                            Role
                          </button>{" "}
                          <button
                            className="btn btn-s btn-sm"
                            type="button"
                            onClick={() => setPasswordOf(u)}
                          >
                            Reset password
                          </button>{" "}
                          <button
                            className="btn btn-g btn-sm"
                            type="button"
                            onClick={() => toggle.mutate(u)}
                          >
                            {u.active ? "Deactivate" : "Activate"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <Problems messages={toggle.isError ? errorMessages(toggle.error) : []} />
            </div>
          ))}
        {tab === "keys" && <KeysTable />}
        {tab === "roles" && (
          <dl className="kvs">
            {ROLE_RIGHTS.map(([role, rights]) => (
              <div key={role} style={{ display: "contents" }}>
                <dt>
                  <b>{role}</b>
                </dt>
                <dd style={{ fontWeight: 400 }}>{rights}</dd>
              </div>
            ))}
          </dl>
        )}
      </Panel>
      {adding && <AddUserDialog onClose={() => setAdding(false)} />}
      {issuing && <IssueKeyDialog onClose={() => setIssuing(false)} />}
      {roleOf && <RoleDialog user={roleOf} onClose={() => setRoleOf(null)} />}
      {passwordOf && <PasswordDialog user={passwordOf} onClose={() => setPasswordOf(null)} />}
    </>
  );
}
