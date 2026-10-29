import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { fetchAllAssets } from "../../api/assets";
import { fetchAssetTypes } from "../../api/registry";
import { type TemplateResult, applyTemplate, fetchTemplates } from "../../api/templates";
import { useAnnounce } from "../../app/liveContext";
import { Problems } from "../registry/common";

/**
 * Apply template (UC-07, FR-MOD-08): a model engineer picks an asset type's template and
 * its assets, previews how each role resolves to the asset's tag (gaps and skipped assets
 * listed, UC-07 2a), then creates a draft model per eligible asset, each submitted for
 * training at once. The results link to the new models.
 */
export function ApplyTemplate({ onClose }: { onClose: () => void }) {
  const client = useQueryClient();
  const announce = useAnnounce();
  const types = useQuery({
    queryKey: ["asset-types"],
    queryFn: ({ signal }) => fetchAssetTypes(signal),
  });
  const assets = useQuery({
    queryKey: ["assets", "all"],
    queryFn: ({ signal }) => fetchAllAssets(signal),
  });
  const [type, setType] = useState("");
  const templates = useQuery({
    queryKey: ["model-templates", type],
    queryFn: ({ signal }) => fetchTemplates(type, signal),
    enabled: !!type,
  });
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [unticked, setUnticked] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<TemplateResult[] | null>(null);
  const [results, setResults] = useState<TemplateResult[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const ofType = (assets.data ?? []).filter((a) => a.asset_type === type);
  const chosen = ofType.filter((a) => !unticked.has(a.code)).map((a) => a.code);
  const template = templates.data?.find((t) => t.id === templateId) ?? templates.data?.[0];
  const ready = preview?.filter((r) => r.outcome === "ready").length ?? 0;

  function reset() {
    setPreview(null);
    setResults(null);
    setError(null);
  }

  async function run(isPreview: boolean) {
    if (!template) return;
    setBusy(true);
    setError(null);
    try {
      const done = await applyTemplate(template.id, chosen, isPreview);
      if (isPreview) setPreview(done);
      else {
        setResults(done);
        const made = done.filter((r) => r.outcome === "created").length;
        announce(`${made} model${made === 1 ? "" : "s"} created and queued for training`);
        void client.invalidateQueries({ queryKey: ["models"] });
      }
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  }

  const shown = results ?? preview;
  return (
    <section className="panel" aria-labelledby="apply-title">
      <div className="panel-head">
        <h2 id="apply-title" className="panel-title">
          Apply a template
        </h2>
        <button type="button" className="link-button" onClick={onClose}>
          Close
        </button>
      </div>
      <div className="field-row">
        <label className="field-inline">
          <span>Asset type</span>
          <select
            className="control"
            value={type}
            onChange={(e) => {
              setType(e.target.value);
              setTemplateId(null);
              setUnticked(new Set());
              reset();
            }}
          >
            <option value="">Choose…</option>
            {(types.data ?? []).map((t) => (
              <option key={t.code} value={t.code}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        {type && (
          <label className="field-inline">
            <span>Template</span>
            <select
              className="control"
              value={template?.id ?? ""}
              disabled={!templates.data?.length}
              onChange={(e) => {
                setTemplateId(Number(e.target.value));
                reset();
              }}
            >
              {(templates.data ?? []).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} (models named {t.model_name})
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {type && templates.isSuccess && !templates.data.length && (
        <p className="muted">
          This asset type has no template yet. Import one with <code>pmp template import FILE</code>{" "}
          or <code>PUT /api/v1/model-templates</code>.
        </p>
      )}
      {template && (
        <>
          <p className="muted small">
            Required roles: {template.required_roles.join(", ") || "none"}. Optional:{" "}
            {template.optional_roles.join(", ") || "none"}.
          </p>
          <fieldset className="event-choices" disabled={busy || !!results}>
            <legend>
              Assets ({chosen.length} of {ofType.length})
            </legend>
            {ofType.map((a) => (
              <label key={a.code} className="field-inline">
                <input
                  type="checkbox"
                  checked={!unticked.has(a.code)}
                  onChange={(e) => {
                    const next = new Set(unticked);
                    if (e.target.checked) next.delete(a.code);
                    else next.add(a.code);
                    setUnticked(next);
                    reset();
                  }}
                />
                {a.code}
              </label>
            ))}
          </fieldset>
          <div className="form-actions">
            <button
              type="button"
              className="button"
              disabled={busy || !chosen.length || !!results}
              onClick={() => void run(true)}
            >
              Preview
            </button>
            <button
              type="button"
              className="button button-primary"
              disabled={busy || !preview || !ready || !!results}
              onClick={() => void run(false)}
            >
              {busy && preview ? "Creating…" : `Create ${ready} model${ready === 1 ? "" : "s"}`}
            </button>
          </div>
        </>
      )}
      <Problems error={error} />
      {shown && (
        <table className="tree-table">
          <caption className="visually-hidden">
            {results ? "Results per asset" : "Preview per asset"}
          </caption>
          <thead>
            <tr>
              <th scope="col">Asset</th>
              <th scope="col">Outcome</th>
              <th scope="col">Sensors (role → tag)</th>
              <th scope="col">Gaps (left out)</th>
              <th scope="col">Model</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.asset}>
                <td>{r.asset}</td>
                <td className={r.outcome === "skipped" ? "overdue" : undefined}>
                  {r.outcome === "ready" ? "will be created" : r.outcome}
                  {r.reason ? `: ${r.reason}` : ""}
                </td>
                <td className="small">
                  {Object.entries(r.tags)
                    .map(([role, tag]) => `${role} → ${tag}`)
                    .join(", ") || "—"}
                </td>
                <td>{r.missing_optional.join(", ") || "—"}</td>
                <td>
                  {r.model_id ? (
                    <Link to={`/models/${r.model_id}/versions/1`}>Training…</Link>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
