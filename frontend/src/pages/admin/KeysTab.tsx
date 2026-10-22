import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  type ApiKey,
  type IssuedKey,
  type KeyScope,
  fetchApiKeys,
  issueApiKey,
  revokeApiKey,
  rotateApiKey,
} from "../../api/admin";
import { formatDateTime } from "../../app/format";
import { useAnnounce } from "../../app/liveContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Skeleton } from "../fleet/FleetPage";
import { Field, Problems } from "../registry/common";

const SCOPES: { value: KeyScope; label: string }[] = [
  { value: "ingest", label: "Ingest: send samples and history (gateways)" },
  { value: "results-read", label: "Results read: read health, scores and alerts" },
];

type Confirm = { kind: "revoke" | "rotate"; key: ApiKey } | null;

/** FR-SEC-02, UC-18: keys for gateways and other systems. A key is shown once, when it is
 * issued; only its hash is stored. Rotation issues a replacement, and the old key works
 * until it is revoked, so the system can switch without a gap. */
export function KeysTab() {
  const client = useQueryClient();
  const announce = useAnnounce();
  const keys = useQuery({ queryKey: ["api-keys"], queryFn: ({ signal }) => fetchApiKeys(signal) });
  const [name, setName] = useState("");
  const [scope, setScope] = useState<KeyScope>("ingest");
  const [tried, setTried] = useState(false);
  const [issued, setIssued] = useState<(IssuedKey & { name: string }) | null>(null);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [copied, setCopied] = useState(false);
  const refresh = () => client.invalidateQueries({ queryKey: ["api-keys"] });
  const issue = useMutation({
    mutationFn: () => issueApiKey(name.trim(), scope),
    onSuccess: (key) => {
      setIssued({ ...key, name: name.trim() });
      setCopied(false);
      setName("");
      setTried(false);
      announce(`Key ${key.prefix} issued; copy it now`);
      void refresh();
    },
  });

  if (keys.isPending) return <Skeleton rows={4} />;
  if (keys.isError) return <p role="alert">The keys could not be loaded: {keys.error.message}</p>;
  const problems = name.trim() ? [] : ["Name the key after the system that will use it"];

  return (
    <div className="registry-types">
      {issued && (
        <section className="panel key-once" aria-labelledby="key-once-title">
          <h2 id="key-once-title" className="panel-title">
            New key for {issued.name}: copy it now
          </h2>
          <p>
            This is the only time the key is shown. Only its hash is stored, so it cannot be shown
            again; if it is lost, rotate it.
          </p>
          <div className="builder-row">
            <code className="key-value" aria-label="The new key">
              {issued.key}
            </code>
            <span className="lifecycle">
              <button
                type="button"
                className="button button-small"
                onClick={() =>
                  void navigator.clipboard?.writeText(issued.key).then(() => setCopied(true))
                }
              >
                {copied ? "Copied" : "Copy"}
              </button>
              <button type="button" className="button button-small" onClick={() => setIssued(null)}>
                I have stored it
              </button>
            </span>
          </div>
        </section>
      )}
      <section className="panel" aria-labelledby="issue-title">
        <h2 id="issue-title" className="panel-title">
          Issue a key
        </h2>
        <form
          className="form-grid"
          onSubmit={(e) => {
            e.preventDefault();
            setTried(true);
            if (!problems.length) issue.mutate();
          }}
        >
          <Field label="Name">
            <input className="control" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Scope">
            <select
              className="control"
              value={scope}
              onChange={(e) => setScope(e.target.value as KeyScope)}
            >
              {SCOPES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </Field>
          <div className="builder-wide">
            <Problems problems={tried ? problems : []} error={issue.error} />
            <div className="builder-buttons">
              <button type="submit" className="button button-primary" disabled={issue.isPending}>
                Issue key
              </button>
            </div>
          </div>
        </form>
      </section>
      <section className="panel" aria-labelledby="keys-title">
        <h2 id="keys-title" className="panel-title">
          Keys ({keys.data.length})
        </h2>
        <table className="tree-table">
          <caption className="visually-hidden">API keys</caption>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Key</th>
              <th scope="col">Scope</th>
              <th scope="col">Issued</th>
              <th scope="col">Last used</th>
              <th scope="col">Status</th>
              <th scope="col">Change</th>
            </tr>
          </thead>
          <tbody>
            {keys.data.map((k) => (
              <tr key={k.id} className={k.revoked_at ? "row-muted" : ""}>
                <td>{k.name}</td>
                <td className="mono">{k.prefix}…</td>
                <td>{k.scope}</td>
                <td>{formatDateTime(new Date(k.created_at))}</td>
                <td>{k.last_used_at ? formatDateTime(new Date(k.last_used_at)) : "Never"}</td>
                <td>
                  {k.revoked_at ? `Revoked ${formatDateTime(new Date(k.revoked_at))}` : "Active"}
                </td>
                <td>
                  {!k.revoked_at && (
                    <span className="lifecycle">
                      <button
                        type="button"
                        className="button button-small"
                        aria-label={`Rotate ${k.name}`}
                        onClick={() => setConfirm({ kind: "rotate", key: k })}
                      >
                        Rotate
                      </button>
                      <button
                        type="button"
                        className="button button-small button-danger-outline"
                        aria-label={`Revoke ${k.name}`}
                        onClick={() => setConfirm({ kind: "revoke", key: k })}
                      >
                        Revoke
                      </button>
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={
          confirm
            ? `${confirm.kind === "revoke" ? "Revoke" : "Rotate"} the key ${confirm.key.name}?`
            : ""
        }
        consequence={
          confirm?.kind === "revoke"
            ? "It stops working at once: anything still using it is refused."
            : "A replacement is issued and shown once. The old key keeps working until you revoke it, so switch the system over first."
        }
        confirmLabel={confirm?.kind === "revoke" ? "Revoke" : "Rotate"}
        danger={confirm?.kind === "revoke"}
        onConfirm={async () => {
          const { kind, key } = confirm!;
          if (kind === "revoke") {
            await revokeApiKey(key.id);
            announce(`Key ${key.name} revoked`);
          } else {
            const replacement = await rotateApiKey(key.id);
            setIssued({ ...replacement, name: key.name });
            setCopied(false);
            announce(`Replacement for ${key.name} issued; copy it now`);
          }
          await refresh();
        }}
      />
    </div>
  );
}
