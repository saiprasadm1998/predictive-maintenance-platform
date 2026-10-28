import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { fetchAsset } from "../../api/assets";
import { type ModeMatch, fetchDiagnosis } from "../../api/diagnostics";
import { fetchAssetTypes } from "../../api/registry";
import { useBreadcrumbs } from "../../app/breadcrumbs";
import { formatDateTime, formatIso } from "../../app/format";
import { Skeleton } from "../fleet/FleetPage";
import { ARROW, NOT_PROBABILITY, scoreText, signed, sparkPaths } from "./diagnosticsModel";

/**
 * SCR-04 Diagnostics and forecast (PDS §4.4, UC-09 step 4, wireframe 04): failure modes of
 * the asset's type ranked by match at the latest cycle (or `?at=`), each with a score bar
 * and a 7-day sparkline; the selected mode's symptoms (expected, observed z, result, "not
 * evaluated" where the sensor is excluded) and its recommended tasks. The forecast arrives
 * with plan 8.3, similar past cases in Release 3.
 */
export function DiagnosticsPage() {
  const id = Number(useParams().assetId);
  const [params, setParams] = useSearchParams();
  const at = params.get("at");
  const detail = useQuery({
    queryKey: ["assets", "detail", id],
    queryFn: ({ signal }) => fetchAsset(id, signal),
    enabled: Number.isFinite(id),
  });
  const types = useQuery({
    queryKey: ["asset-types"],
    queryFn: ({ signal }) => fetchAssetTypes(signal),
  });
  const asset = detail.data;
  const models = asset?.health.models ?? [];
  const modelId = Number(params.get("model")) || models[0]?.model_id || null;
  const diagnosis = useQuery({
    queryKey: ["diagnostics", modelId, at],
    queryFn: ({ signal }) => fetchDiagnosis(modelId!, at, signal),
    enabled: modelId !== null,
  });
  useBreadcrumbs(
    asset
      ? [
          { label: "Fleet", to: "/fleet" },
          ...asset.ancestors.map((a) => ({ label: a.name, to: `/units/${a.id}` })),
          { label: asset.code, to: `/assets/${asset.id}` },
          { label: "Diagnostics and forecast" },
        ]
      : null,
  );
  const roleNames = useMemo(() => {
    const type = types.data?.find((t) => t.code === asset?.asset_type);
    return new Map((type?.roles ?? []).map((r) => [r.code, r.name]));
  }, [types.data, asset?.asset_type]);

  if (detail.isPending) return <Skeleton rows={8} />;
  if (detail.isError)
    return <p role="alert">The asset could not be loaded: {detail.error.message}</p>;
  if (modelId === null)
    return (
      <section className="panel empty-state">
        <p>This asset has no model, so there is nothing to diagnose yet.</p>
      </section>
    );

  const modes = diagnosis.data?.modes ?? [];
  const chosenCode = params.get("mode") ?? modes[0]?.mode.code ?? null;
  const chosen = modes.find((m) => m.mode.code === chosenCode) ?? modes[0];

  function choose(code: string) {
    setParams((current) => {
      const p = new URLSearchParams(current);
      p.set("mode", code);
      return p;
    });
  }

  return (
    <div className="diagnostics">
      <section className="panel" aria-labelledby="match-title">
        <div className="panel-head">
          <h2 id="match-title" className="panel-title">
            Failure-mode match ·{" "}
            {diagnosis.data?.at ? (
              <time title={formatIso(new Date(diagnosis.data.at))}>
                {at ? formatDateTime(new Date(diagnosis.data.at)) : "current"}
              </time>
            ) : (
              "current"
            )}
          </h2>
          <Link className="link-button" to={`/assets/${id}?model=${modelId}`}>
            Back to asset analysis
          </Link>
        </div>
        {diagnosis.isPending ? (
          <Skeleton rows={4} />
        ) : diagnosis.isError ? (
          <p role="alert">Diagnostics could not be loaded: {diagnosis.error.message}</p>
        ) : !diagnosis.data.at ? (
          <p className="muted">The model has not been scored yet.</p>
        ) : modes.length === 0 ? (
          <p className="muted">
            The failure-mode library has no modes for this asset type yet. Model engineers add them
            under <Link to={`/library?type=${asset?.asset_type ?? ""}`}>Library</Link>.
          </p>
        ) : (
          <>
            <ul className="mode-list" aria-label="Failure modes ranked by match">
              {modes.map((m) => (
                <li key={m.mode.code}>
                  <ModeRow mode={m} selected={m === chosen} onSelect={() => choose(m.mode.code)} />
                </li>
              ))}
            </ul>
            <p className="muted small">{NOT_PROBABILITY}</p>
          </>
        )}
      </section>

      <section className="panel" aria-labelledby="forecast-title">
        <h2 id="forecast-title" className="panel-title">
          Time-to-threshold forecast
        </h2>
        <p className="muted">The forecast arrives with prognostics (plan 8.3).</p>
      </section>

      {chosen && (
        <>
          <section className="panel" aria-labelledby="symptoms-title">
            <h2 id="symptoms-title" className="panel-title">
              Symptoms · {chosen.mode.name.toLowerCase()}
            </h2>
            <table className="tree-table">
              <thead>
                <tr>
                  <th scope="col">Symptom (role)</th>
                  <th scope="col">Expected</th>
                  <th scope="col" className="num">
                    Observed z
                  </th>
                  <th scope="col" className="num">
                    Weight
                  </th>
                  <th scope="col">Result</th>
                </tr>
              </thead>
              <tbody>
                {chosen.symptoms.map((s) => (
                  <tr key={s.role}>
                    <td title={s.source_name ?? undefined}>{roleNames.get(s.role) ?? s.role}</td>
                    <td>{ARROW[s.direction]}</td>
                    <td className="num">
                      {s.result === "not evaluated" ? "excluded" : signed(s.z)}
                    </td>
                    <td className="num">{s.weight}</td>
                    <td>
                      <span className={`symptom-${s.result.replace(" ", "-")}`}>
                        {s.result === "match"
                          ? "✔ match"
                          : s.result === "partial"
                            ? "✔ partial"
                            : s.result === "no match"
                              ? "✘ no match"
                              : "— not evaluated"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {chosen.insufficient_evidence && (
              <p className="form-warning">
                ⚠ Insufficient evidence: only {chosen.evaluated_weight} of {chosen.total_weight}{" "}
                weight could be evaluated (UCS §6.7.2 needs half).
              </p>
            )}
          </section>
          <section className="panel" aria-labelledby="tasks-title">
            <h2 id="tasks-title" className="panel-title">
              Recommended tasks
            </h2>
            {chosen.mode.tasks.length ? (
              <ul className="task-list">
                {chosen.mode.tasks.map((t) => (
                  <li key={t}>
                    <span aria-hidden="true">☐ </span>
                    {t}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No tasks are linked to this failure mode.</p>
            )}
            <p className="muted small">
              Tasks are copied into a case with its snapshot when cases arrive (plan 8.4).
            </p>
          </section>
        </>
      )}
    </div>
  );
}

function ModeRow({
  mode: m,
  selected,
  onSelect,
}: {
  mode: ModeMatch;
  selected: boolean;
  onSelect: () => void;
}) {
  const score = m.insufficient_evidence ? null : m.score;
  const paths = sparkPaths(m.trend);
  return (
    <button
      type="button"
      className="mode-row"
      aria-pressed={selected}
      aria-label={`${m.mode.name}: ${scoreText(m)}`}
      onClick={onSelect}
    >
      <span className="mode-name">
        {m.mode.name}
        {m.mode.iso_code && <span className="muted small"> (ISO 14224: {m.mode.iso_code})</span>}
      </span>
      <span className="contributor-bar" aria-hidden="true">
        <span style={{ width: `${Math.round(score ?? 0)}%` }} />
      </span>
      <span className="num">{scoreText(m)}</span>
      <svg className="sparkline" width="80" height="18" viewBox="0 0 80 18" aria-hidden="true">
        {paths.map((points, i) => (
          <polyline key={i} points={points} fill="none" stroke="currentColor" strokeWidth="1.5" />
        ))}
      </svg>
    </button>
  );
}
