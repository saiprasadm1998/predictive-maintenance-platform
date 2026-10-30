import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { fetchIngestionHealth } from "../../api/ingestion";
import { formatDateTime, formatIso } from "../../app/format";
import { Skeleton } from "../fleet/FleetPage";
import { ageText, skewText, sourceState, tagsInView } from "./ingestionModel";

const MAX_TAGS = 500;

function Time({ iso, now }: { iso: string | null; now: string }) {
  if (!iso) return <span className="muted">never</span>;
  return (
    <span title={`${formatDateTime(new Date(iso))} (${formatIso(new Date(iso))})`}>
      {ageText(iso, now)}
    </span>
  );
}

/**
 * Ingestion health (FR-ING-07, SCR-14, administrators): per source the last receipt, the
 * newest sample, throughput, accepted and rejected counts, stale and clock-skew warnings;
 * per tag its newest sample. Refreshed every 15 seconds; times are from the server clock.
 */
export function IngestionTab() {
  const [source, setSource] = useState("");
  const [staleOnly, setStaleOnly] = useState(false);
  const [text, setText] = useState("");
  const health = useQuery({
    queryKey: ["ingestion", "health"],
    queryFn: ({ signal }) => fetchIngestionHealth(signal),
    refetchInterval: 15_000,
  });
  if (health.isPending) return <Skeleton rows={4} />;
  if (health.isError)
    return <p role="alert">Ingestion health could not be loaded: {health.error.message}</p>;
  const h = health.data;
  const tags = tagsInView(h, source, staleOnly, text);
  const stale = h.sources.filter((s) => sourceState(s).warn).length;

  return (
    <>
      <section className="panel" aria-labelledby="sources-title">
        <div className="panel-head">
          <h2 id="sources-title" className="panel-title">
            Sources
          </h2>
          <span className="muted small">
            Checked {formatDateTime(new Date(h.checked_at))} · stale after 2 scan intervals · clock
            skew warned above 60 s
          </span>
        </div>
        {stale > 0 && (
          <p role="status" className="form-error">
            {stale === 1 ? "1 source needs attention." : `${stale} sources need attention.`} Models
            scoring their sensors show Insufficient data.
          </p>
        )}
        {h.sources.length === 0 ? (
          <p className="muted">No source has sent data or has registered tags yet.</p>
        ) : (
          <table className="tree-table">
            <caption className="visually-hidden">Gateway sources</caption>
            <thead>
              <tr>
                <th scope="col">Source</th>
                <th scope="col">State</th>
                <th scope="col">Last received</th>
                <th scope="col">Newest sample</th>
                <th scope="col" className="num">
                  Clock skew
                </th>
                <th scope="col" className="num">
                  Samples / min
                </th>
                <th scope="col" className="num">
                  Accepted
                </th>
                <th scope="col" className="num">
                  Rejected
                </th>
                <th scope="col" className="num">
                  Tags
                </th>
              </tr>
            </thead>
            <tbody>
              {h.sources.map((s) => {
                const state = sourceState(s);
                return (
                  <tr key={s.source}>
                    <th scope="row">{s.source}</th>
                    <td className={state.warn ? "overdue" : undefined}>{state.text}</td>
                    <td>
                      <Time iso={s.last_received_at} now={h.checked_at} />
                    </td>
                    <td>
                      <Time iso={s.last_sample_ts} now={h.checked_at} />
                    </td>
                    <td className={`num${s.skewed ? " overdue" : ""}`}>{skewText(s)}</td>
                    <td className="num">{s.per_minute}</td>
                    <td className="num">{s.accepted_total.toLocaleString()}</td>
                    <td className="num">{s.rejected_total.toLocaleString()}</td>
                    <td className="num">{s.tags}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel" aria-labelledby="tags-title">
        <div className="panel-head">
          <h2 id="tags-title" className="panel-title">
            Tags
          </h2>
          <div className="field-row">
            <label className="field-inline">
              <span>Source</span>
              <select
                className="control"
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                <option value="">All</option>
                {h.sources.map((s) => (
                  <option key={s.source} value={s.source}>
                    {s.source}
                  </option>
                ))}
              </select>
            </label>
            <label className="field-inline">
              <span>Tag or asset</span>
              <input
                className="control"
                type="search"
                value={text}
                onChange={(e) => setText(e.target.value)}
              />
            </label>
            <label className="field-inline">
              <input
                type="checkbox"
                checked={staleOnly}
                onChange={(e) => setStaleOnly(e.target.checked)}
              />
              <span>Stale only</span>
            </label>
          </div>
        </div>
        {tags.length === 0 ? (
          <p className="muted">No tag matches.</p>
        ) : (
          <table className="tree-table">
            <caption className="visually-hidden">Tags and their newest sample</caption>
            <thead>
              <tr>
                <th scope="col">Tag</th>
                <th scope="col">Asset</th>
                <th scope="col">Source</th>
                <th scope="col" className="num">
                  Scan interval
                </th>
                <th scope="col">Newest sample</th>
              </tr>
            </thead>
            <tbody>
              {tags.slice(0, MAX_TAGS).map((t) => (
                <tr key={t.tag_id}>
                  <th scope="row">{t.source_name}</th>
                  <td>{t.asset_code}</td>
                  <td>{t.source}</td>
                  <td className="num">{t.interval_s} s</td>
                  <td className={t.stale ? "overdue" : undefined}>
                    <Time iso={t.last_sample_ts} now={h.checked_at} />
                    {t.stale ? " · stale" : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {tags.length > MAX_TAGS && (
          <p className="muted small">
            Showing {MAX_TAGS} of {tags.length}; narrow by source or text.
          </p>
        )}
      </section>
    </>
  );
}
