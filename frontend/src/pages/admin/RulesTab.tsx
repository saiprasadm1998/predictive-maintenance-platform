import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { type RuleSet, type RulesIn, fetchRules, previewRules, saveRules } from "../../api/admin";
import { ApiError } from "../../api/client";
import { fetchAllTags, fetchAssetTypes } from "../../api/registry";
import { formatDateTime } from "../../app/format";
import { useAnnounce } from "../../app/liveContext";
import { useMe } from "../../app/session";
import { Skeleton } from "../fleet/FleetPage";
import { share } from "../models/builderModel";
import { Field, Problems } from "../registry/common";
import {
  RULE_LABELS,
  RULE_PARAMS,
  type RuleForm,
  isModelEngineer,
  overridesOf,
  ruleForm,
  ruleProblems,
} from "./adminModel";

const DAYS = [7, 30, 90];

/**
 * UC-04, FR-DQ-01, UCS §6.1: the data-quality rules everywhere, for a role of an asset type,
 * or for one tag (the most specific wins). A change is previewed on recent data first and
 * saved as a new, audited version that applies from the next cycle; if a tag would lose
 * more than 20 % of its data, saving needs a confirmation (UC-04 3a).
 */
export function RulesTab() {
  const me = useMe();
  const editable = isModelEngineer(me.data);
  const [kind, setKind] = useState<"global" | "role" | "tag">("global");
  const [typeRole, setTypeRole] = useState("");
  const [tagId, setTagId] = useState("");
  const types = useQuery({
    queryKey: ["asset-types"],
    queryFn: ({ signal }) => fetchAssetTypes(signal),
  });
  const tags = useQuery({
    queryKey: ["tags", "all"],
    queryFn: ({ signal }) => fetchAllTags(signal),
  });
  const scope =
    kind === "global"
      ? "global"
      : kind === "role"
        ? typeRole
          ? `role:${typeRole}`
          : null
        : tagId
          ? `tag:${tagId}`
          : null;
  const rules = useQuery({
    queryKey: ["dq-rules", scope],
    queryFn: ({ signal }) => fetchRules(scope!, signal),
    enabled: scope !== null,
  });

  return (
    <div className="registry-types">
      <section className="panel" aria-labelledby="scope-title">
        <h2 id="scope-title" className="panel-title">
          Data-quality rules
        </h2>
        <p className="muted small">
          Rules apply everywhere unless an asset-type role or a tag has its own; the most specific
          wins. Bad source quality is always excluded and cannot be switched off.
          {!editable && " Model Engineers change the rules."}
        </p>
        <div className="form-grid">
          <Field label="Applies to">
            <select
              className="control"
              value={kind}
              onChange={(e) => setKind(e.target.value as typeof kind)}
            >
              <option value="global">Everywhere</option>
              <option value="role">A role of an asset type</option>
              <option value="tag">One tag</option>
            </select>
          </Field>
          {kind === "role" && (
            <Field label="Role">
              <select
                className="control"
                value={typeRole}
                onChange={(e) => setTypeRole(e.target.value)}
              >
                <option value="">Choose…</option>
                {(types.data ?? []).flatMap((t) =>
                  t.roles.map((r) => (
                    <option key={`${t.code}/${r.code}`} value={`${t.code}/${r.code}`}>
                      {t.name}: {r.name}
                    </option>
                  )),
                )}
              </select>
            </Field>
          )}
          {kind === "tag" && (
            <Field label="Tag">
              <select className="control" value={tagId} onChange={(e) => setTagId(e.target.value)}>
                <option value="">Choose…</option>
                {(tags.data ?? []).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.source_name} ({t.asset_code})
                  </option>
                ))}
              </select>
            </Field>
          )}
        </div>
      </section>
      {scope === null ? null : rules.isPending ? (
        <Skeleton rows={6} />
      ) : rules.isError ? (
        <p role="alert">The rules could not be loaded: {rules.error.message}</p>
      ) : (
        <RuleEditor key={`${scope}:${rules.data.version}`} rules={rules.data} editable={editable} />
      )}
    </div>
  );
}

function RuleEditor({ rules, editable }: { rules: RuleSet; editable: boolean }) {
  const client = useQueryClient();
  const announce = useAnnounce();
  const [form, setForm] = useState<RuleForm>(() => ruleForm(rules.overrides));
  const [comment, setComment] = useState("");
  const [days, setDays] = useState(30);
  const [confirmed, setConfirmed] = useState(false);
  const body = (confirm: boolean): RulesIn => ({
    scope: rules.scope,
    overrides: overridesOf(form),
    comment: comment.trim(),
    confirm,
    days,
  });
  const preview = useMutation({ mutationFn: () => previewRules(body(false)) });
  const save = useMutation({
    mutationFn: () => saveRules(body(confirmed)),
    onSuccess: (saved) => {
      announce(`Rules saved as version ${saved.rules.version}`);
      void client.invalidateQueries({ queryKey: ["dq-rules"] });
    },
  });
  const problems = ruleProblems(form);
  const report = preview.data;
  const needsConfirm =
    !!report?.warning ||
    (save.error instanceof ApiError && save.error.problem.code === "preview_warning");
  const set = (name: string, value: string) => {
    setForm({ ...form, [name]: value });
    preview.reset();
    setConfirmed(false);
  };

  return (
    <section className="panel" aria-labelledby="rules-title">
      <h2 id="rules-title" className="panel-title">
        {rules.scope === "global" ? "Everywhere" : rules.scope}:{" "}
        {rules.version
          ? `version ${rules.version}${rules.created_at ? `, ${formatDateTime(new Date(rules.created_at))}` : ""}`
          : "no rules of its own"}
      </h2>
      {rules.comment && <p className="muted small">“{rules.comment}”</p>}
      <table className="tree-table">
        <caption className="visually-hidden">Rule parameters</caption>
        <thead>
          <tr>
            <th scope="col">Rule</th>
            <th scope="col">This scope</th>
            <th scope="col">Default</th>
          </tr>
        </thead>
        <tbody>
          {RULE_PARAMS.map((p) => {
            const fallback = rules.defaults[p.name];
            return (
              <tr key={p.name}>
                <th scope="row">{p.label}</th>
                <td>
                  {p.kind === "switch" ? (
                    <select
                      className="control"
                      aria-label={p.label}
                      disabled={!editable}
                      value={form[p.name]}
                      onChange={(e) => set(p.name, e.target.value)}
                    >
                      <option value="">Inherit</option>
                      <option value="true">On</option>
                      <option value="false">Off</option>
                    </select>
                  ) : (
                    <span className="field-inline">
                      <input
                        className="control builder-number"
                        type="number"
                        step="any"
                        aria-label={p.label}
                        placeholder="Inherit"
                        disabled={!editable}
                        value={form[p.name]}
                        onChange={(e) => set(p.name, e.target.value)}
                      />
                      <span className="muted small">{p.unit}</span>
                    </span>
                  )}
                </td>
                <td className="muted">
                  {typeof fallback === "boolean"
                    ? fallback
                      ? "On"
                      : "Off"
                    : `${fallback} ${p.unit ?? ""}`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {editable && (
        <>
          <div className="form-grid">
            <Field label="Why (kept with the version)">
              <input
                className="control"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />
            </Field>
            <Field label="Preview over the last">
              <select
                className="control"
                value={days}
                onChange={(e) => {
                  setDays(Number(e.target.value));
                  preview.reset();
                }}
              >
                {DAYS.map((d) => (
                  <option key={d} value={d}>
                    {d} days
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Problems
            problems={problems}
            error={preview.error ?? (needsConfirm ? null : save.error)}
          />
          <div className="builder-buttons">
            <button
              type="button"
              className="button"
              disabled={!!problems.length || preview.isPending}
              onClick={() => preview.mutate()}
            >
              Preview
            </button>
            <button
              type="button"
              className="button button-primary"
              disabled={
                !report || !!problems.length || (needsConfirm && !confirmed) || save.isPending
              }
              onClick={() => save.mutate()}
            >
              Save
            </button>
          </div>
          {report && (
            <div className="registry-report">
              <p role="status">
                With these rules, <strong>{share(report.excluded_share, 1)}</strong> of the scope's
                data over the last {days} days would be excluded.
              </p>
              {needsConfirm && (
                <div role="alert" className="key-once">
                  <p>Some tags would lose more than 20 % of their data (UC-04).</p>
                  <label className="field-inline">
                    <input
                      type="checkbox"
                      checked={confirmed}
                      onChange={(e) => setConfirmed(e.target.checked)}
                    />
                    <span>Save anyway</span>
                  </label>
                </div>
              )}
              <table className="tree-table">
                <caption>Tags most affected</caption>
                <thead>
                  <tr>
                    <th scope="col">Tag</th>
                    <th scope="col">Asset</th>
                    <th scope="col" className="num">
                      Excluded
                    </th>
                    <th scope="col">By rule</th>
                  </tr>
                </thead>
                <tbody>
                  {[...report.tags]
                    .sort((a, b) => b.excluded_share - a.excluded_share)
                    .slice(0, 20)
                    .map((t) => (
                      <tr key={t.tag_id} className={t.excluded_share > 0.2 ? "row-unack" : ""}>
                        <td className="mono">{t.source_name}</td>
                        <td>{t.asset_code}</td>
                        <td className="num">{share(t.excluded_share, 1)}</td>
                        <td>
                          {Object.entries(t.by_rule)
                            .filter(([, n]) => n > 0)
                            .map(([r, n]) => `${RULE_LABELS[r] ?? r} ${n.toLocaleString("en-GB")}`)
                            .join(", ") || "—"}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
