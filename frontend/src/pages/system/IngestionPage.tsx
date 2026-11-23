import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { type Reject, fetchIngestionHealth, fetchRejects, testBroker } from "../../api/ingestion";
import { HowTo, ICONS, IdChip, Kpis, Loading, PageHeader, Panel, Pill } from "../../components/ui";
import { OpsAlerts } from "../admin/OpsAlerts";
import { ageText, skewText, sourceState, tagsInView } from "../admin/ingestionModel";
import { useEquipmentSetup, useUnmapped } from "../setup/setupModel";

const REASON: Record<string, string> = {
  unregistered_tag: "Tag not registered",
  in_future: "More than 5 min in the future",
  too_old: "Older than the late-data window",
  no_value: "No value",
  malformed: "Message not readable",
  source_mismatch: "Source differs from the topic",
};

function exportRejects(rows: Reject[]) {
  const lines = [
    ["received", "source", "transport", "tag", "sample time", "value", "reason", "detail"],
  ];
  for (const r of rows)
    lines.push([
      r.received_at,
      r.source,
      r.transport,
      r.tag ?? "",
      r.sample_ts ?? "",
      String(r.value ?? ""),
      r.reason,
      r.detail ?? "",
    ]);
  const text = lines.map((l) => l.map((c) => `"${c.replace(/"/g, '""')}"`).join(",")).join("\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "reject-log.csv";
  a.click();
  URL.revokeObjectURL(url);
}

export function IngestionPage() {
  const health = useQuery({
    queryKey: ["ingestion", "health"],
    queryFn: ({ signal }) => fetchIngestionHealth(signal),
    refetchInterval: 30_000,
  });
  const unmapped = useUnmapped();
  const rejects = useQuery({
    queryKey: ["ingestion", "rejects"],
    queryFn: ({ signal }) => fetchRejects(signal),
  });
  const test = useMutation({ mutationFn: testBroker });
  const { rows } = useEquipmentSetup();
  const [source, setSource] = useState("");
  const [text, setText] = useState("");
  const [staleOnly, setStaleOnly] = useState(false);
  if (!health.data)
    return (
      <>
        <PageHeader title="Ingestion health" sub="Live samples arrive from the gateways" />
        <OpsAlerts />
        {health.isPending ? (
          <Loading what="ingestion health" />
        ) : (
          <p className="err">Ingestion health could not be read.</p>
        )}
      </>
    );

  const h = health.data;
  const now = h.checked_at;
  const perMinute = h.sources.reduce((a, s) => a + s.per_minute, 0);
  const expected = h.tags.reduce((a, t) => a + 60 / Math.max(1, t.interval_s), 0);
  const tags = tagsInView(h, source, staleOnly, text);
  const assetId = (code: string) => rows.find((r) => r.node.code === code)?.node.id;
  const waiting = unmapped.data ?? [];

  return (
    <>
      <PageHeader
        title="Ingestion health"
        sub="PMP subscribes to the plant MQTT broker and stores every sample, or says why it refused it"
        actions={
          <>
            <HowTo title="Ingestion health">
              A source is stale when nothing arrives for longer than a few scan intervals. Clock
              skew is the gap between when a sample arrives and the time it carries; above 60 s it
              is flagged. Tags that arrive but are not registered wait in Unregistered tags.
            </HowTo>
            <button
              className="btn btn-s"
              type="button"
              disabled={test.isPending}
              onClick={() => test.mutate()}
            >
              {test.isPending ? "Testing…" : "Test broker connection"}
            </button>
          </>
        }
      />
      <OpsAlerts />
      {test.data && (
        <p
          className="notice"
          role="status"
          style={{
            borderLeftColor: test.data.ok
              ? "var(--traverse-status-success-fg)"
              : "var(--traverse-status-warning-fg)",
          }}
        >
          {test.data.message}
        </p>
      )}
      <Kpis
        label="Ingestion"
        items={[
          {
            label: "Broker",
            value: (
              <span style={{ fontSize: 17 }}>
                {!h.broker.configured
                  ? "Not configured"
                  : h.broker.connected
                    ? "Connected"
                    : "Disconnected"}
              </span>
            ),
            tone: h.broker.configured && h.broker.connected ? "info" : "warning",
            icon: ICONS.trend,
            sub: h.broker.url ?? "Set PMP_MQTT_URL to subscribe",
          },
          {
            label: "Samples per minute",
            value: Math.round(perMinute).toLocaleString(),
            icon: ICONS.trend,
            sub: `Expected ${Math.round(expected).toLocaleString()}`,
          },
          { label: "Accepted, 24 h", value: h.accepted_24h.toLocaleString(), icon: ICONS.check },
          {
            label: "Rejected, 24 h",
            value: h.rejected_24h.toLocaleString(),
            tone: h.rejected_24h ? "warning" : undefined,
            icon: ICONS.close,
          },
          {
            label: "Unregistered tags",
            value: waiting.length,
            tone: waiting.length ? "warning" : undefined,
            icon: ICONS.tag,
            to: "/setup/tags",
          },
        ]}
      />
      <Panel
        title="Sources"
        actions={
          <span className="meta">
            Checked{" "}
            {new Date(now).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}
          </span>
        }
      >
        {h.sources.filter((s) => sourceState(s).warn).length > 0 && (
          <p
            className="notice"
            style={{ borderLeftColor: "var(--traverse-status-warning-fg)", marginBottom: 8 }}
          >
            {h.sources.filter((s) => sourceState(s).warn).length} sources need attention.
          </p>
        )}
        <div className="tw">
          <table className="tb">
            <caption className="sr">Gateway sources</caption>
            <thead>
              <tr>
                <th>Source</th>
                <th>Topic</th>
                <th>State</th>
                <th>Last received</th>
                <th>Newest sample</th>
                <th style={{ textAlign: "right" }}>Clock skew</th>
                <th style={{ textAlign: "right" }}>Samples / min</th>
                <th style={{ textAlign: "right" }}>Accepted</th>
                <th style={{ textAlign: "right" }}>Rejected</th>
              </tr>
            </thead>
            <tbody>
              {h.sources.map((s) => {
                const state = sourceState(s);
                return (
                  <tr key={s.source}>
                    <td className="mono">{s.source}</td>
                    <td className="mono sec">{`${h.topic_prefix}/${s.source}/samples`}</td>
                    <td>
                      <Pill tone={state.warn ? "warning" : "info"}>{state.text}</Pill>
                    </td>
                    <td>{ageText(s.last_received_at, now)}</td>
                    <td>{ageText(s.last_sample_ts, now)}</td>
                    <td className="num" style={{ textAlign: "right" }}>
                      {skewText(s)}
                    </td>
                    <td className="num" style={{ textAlign: "right" }}>
                      {Math.round(s.per_minute)}
                    </td>
                    <td className="num" style={{ textAlign: "right" }}>
                      {s.accepted_total.toLocaleString()}
                    </td>
                    <td className="num" style={{ textAlign: "right" }}>
                      {s.rejected_total.toLocaleString()}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {h.sources.length === 0 && <p className="sec s13">No source has sent anything yet.</p>}
        </div>
      </Panel>
      <div className="two">
        <Panel
          title="Tags"
          actions={
            <div className="filters" style={{ alignItems: "center" }}>
              <select
                className="sl"
                style={{ width: 180 }}
                aria-label="Source"
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                <option value="">All sources</option>
                {h.sources.map((s) => (
                  <option key={s.source}>{s.source}</option>
                ))}
              </select>
              <input
                className="in"
                style={{ width: 160 }}
                placeholder="Tag or asset"
                aria-label="Tag or asset"
                value={text}
                onChange={(e) => setText(e.target.value)}
              />
              <label className="chk">
                <input
                  type="checkbox"
                  checked={staleOnly}
                  onChange={(e) => setStaleOnly(e.target.checked)}
                />
                <span>Stale only</span>
              </label>
            </div>
          }
        >
          <div className="tw">
            <table className="tb">
              <caption className="sr">Tags and their newest sample</caption>
              <thead>
                <tr>
                  <th>Tag</th>
                  <th>Asset</th>
                  <th>Source</th>
                  <th style={{ textAlign: "right" }}>Scan interval</th>
                  <th>Newest sample</th>
                </tr>
              </thead>
              <tbody>
                {tags.map((t) => {
                  const id = assetId(t.asset_code);
                  return (
                    <tr key={t.tag_id}>
                      <td className="mono">{t.source_name}</td>
                      <td>
                        {id ? <IdChip to={`/assets/${id}`}>{t.asset_code}</IdChip> : t.asset_code}
                      </td>
                      <td className="mono sec">{t.source}</td>
                      <td className="num" style={{ textAlign: "right" }}>
                        {t.interval_s} s
                      </td>
                      <td>
                        <Pill tone={t.stale ? "warning" : "neutral"}>
                          {t.stale
                            ? `Stale, ${ageText(t.last_sample_ts, now)}`
                            : ageText(t.last_sample_ts, now)}
                        </Pill>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>
        <div className="col">
          <Panel title={`Unregistered tags (${waiting.length})`}>
            {waiting.length === 0 ? (
              <p className="sec s13">Every tag that arrives is registered.</p>
            ) : (
              waiting.map((u) => (
                <div
                  key={`${u.source}/${u.source_name}`}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: 12,
                    padding: "8px 0",
                    borderBottom: "1px solid var(--traverse-border-subtle)",
                  }}
                >
                  <span>
                    <b className="mono">{u.source_name}</b>
                    <br />
                    <span className="meta">
                      {u.source}, first seen{" "}
                      {new Date(u.first_seen).toLocaleString("en-GB", {
                        day: "numeric",
                        month: "short",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                      , {u.count.toLocaleString()} samples
                    </span>
                  </span>
                  <Link className="btn btn-s btn-sm" to="/setup/tags">
                    Register
                  </Link>
                </div>
              ))
            )}
          </Panel>
          <Panel
            title="Reject log"
            actions={
              <button
                className="btn btn-s btn-sm"
                type="button"
                disabled={!rejects.data?.length}
                onClick={() => exportRejects(rejects.data ?? [])}
              >
                Export CSV
              </button>
            }
          >
            {(rejects.data ?? []).length === 0 ? (
              <p className="sec s13">Nothing refused.</p>
            ) : (
              (rejects.data ?? []).slice(0, 8).map((r, i) => (
                <div
                  key={i}
                  style={{
                    padding: "6px 0",
                    borderBottom: "1px solid var(--traverse-border-subtle)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <b className="s13">{REASON[r.reason] ?? r.reason.replace(/_/g, " ")}</b>
                    <span className="meta">
                      {new Date(r.received_at).toLocaleTimeString("en-GB", {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  </div>
                  <span className="mono sec" style={{ fontSize: 12 }}>
                    {[r.tag, r.value, r.detail].filter((x) => x !== null && x !== "").join(", ") ||
                      r.source}
                  </span>
                </div>
              ))
            )}
          </Panel>
        </div>
      </div>
    </>
  );
}
