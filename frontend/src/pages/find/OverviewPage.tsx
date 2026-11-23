import { useQueries, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { fetchDiagnosis } from "../../api/diagnostics";
import { fetchModel, fetchScores } from "../../api/models";
import type { AssetNode } from "../../api/types";
import {
  useCases,
  useModels,
  useOpenAlerts,
  useSensorHealth,
  WINDOWS,
  windowMs,
  type WindowKey,
} from "../../app/data";
import { formatDateTime, formatTime } from "../../app/format";
import { useLive } from "../../app/liveContext";
import { useScope } from "../../app/scope";
import { alertState, alertText, plainReason } from "../../app/words";
import { Chart, Legend } from "../../components/Chart";
import { trendPoints } from "../../components/chartData";
import {
  Badge,
  BandPill,
  Empty,
  HealthBar,
  HowTo,
  ICONS,
  IdChip,
  Kpis,
  PageHeader,
  Panel,
  Pill,
  Seg,
} from "../../components/ui";

const ORDER: Record<string, number> = { Alert: 0, Watch: 1, Unknown: 2, Healthy: 3 };

export function OverviewPage() {
  const scope = useScope();
  const live = useLive();
  const [params, setParams] = useSearchParams();
  const win = (params.get("window") as WindowKey | null) ?? "7d";
  const alerts = useOpenAlerts();
  const models = useModels();
  const cases = useCases(true);
  const sensors = useSensorHealth();

  const monitored = scope.equipment.filter((n) => n.band !== null);
  const codes = new Set(scope.equipment.map((n) => n.code));
  const ids = new Set(scope.equipment.map((n) => n.id));
  const byBand = (b: string) => monitored.filter((n) => n.band === b).length;
  const scopedAlerts = (alerts.data ?? []).filter((a) => ids.has(a.asset_id));
  const unack = scopedAlerts.filter(
    (a) => a.state === "Active-Unacknowledged" || a.state === "RTN-Unacknowledged",
  ).length;
  const shelved = scopedAlerts.filter((a) => a.state === "Shelved").length;
  const openCases = (cases.data ?? []).filter((c) => ids.has(c.asset_id)).length;
  const badSensors = (sensors.data ?? []).filter(
    (s) => codes.has(s.asset_code) && s.status !== "Good",
  ).length;
  const review = (models.data ?? []).filter(
    (m) => codes.has(m.asset_code) && m.latest.status === "Validated",
  ).length;

  const attention = monitored
    .filter((n) => n.band !== "Healthy")
    .sort(
      (a, b) =>
        (ORDER[a.band ?? "Unknown"] ?? 9) - (ORDER[b.band ?? "Unknown"] ?? 9) ||
        (a.health ?? 101) - (b.health ?? 101),
    );
  const [picked, setPicked] = useState<number | null>(null);
  const current: AssetNode | undefined =
    attention.find((n) => n.id === picked) ?? attention[0] ?? monitored[0];

  const causes = useQueries({
    queries: attention.slice(0, 8).map((n) => ({
      queryKey: ["models", n.models[0]?.model_id, "diagnosis", "now"],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        fetchDiagnosis(n.models[0]!.model_id, null, signal),
      enabled: !!n.models[0] && (n.band === "Alert" || n.band === "Watch"),
      staleTime: 60_000,
    })),
  });

  const kpis = [
    {
      label: "Equipment monitored",
      value: monitored.length,
      icon: ICONS.equipment,
      to: "/equipment",
    },
    {
      label: "In alert",
      value: byBand("Alert"),
      icon: ICONS.alert,
      tone: "danger" as const,
      to: "/equipment?band=Alert",
    },
    {
      label: "In watch",
      value: byBand("Watch"),
      icon: ICONS.watch,
      tone: "warning" as const,
      to: "/equipment?band=Watch",
    },
    {
      label: "Unknown, cannot score",
      value: byBand("Unknown"),
      icon: ICONS.unknown,
      tone: "unknown" as const,
      to: "/equipment?band=Unknown",
    },
    {
      label: "Healthy",
      value: byBand("Healthy"),
      icon: ICONS.healthy,
      tone: "neutral" as const,
      to: "/equipment?band=Healthy",
    },
    {
      label: "Unacknowledged alerts",
      value: unack,
      icon: ICONS.bell,
      tone: "warning" as const,
      to: "/alerts",
    },
    {
      label: "Shelved alerts",
      value: shelved,
      icon: ICONS.shelve,
      tone: "neutral" as const,
      to: "/alerts?tab=shelved",
    },
    {
      label: "Open cases",
      value: openCases,
      icon: ICONS.folder,
      tone: "info" as const,
      to: "/cases",
    },
    {
      label: "Sensors not good",
      value: badSensors,
      icon: ICONS.gauge,
      tone: "warning" as const,
      to: "/sensors",
    },
    {
      label: "Models to review",
      value: review,
      icon: ICONS.trend,
      tone: "warning" as const,
      to: "/models",
    },
  ];

  const events = [...scopedAlerts]
    .sort((a, b) => b.raised_at.localeCompare(a.raised_at))
    .slice(0, 6);
  const last = live.lastCycle;
  const sub = `Scope: ${scope.label.split(" · ")[0]}. Scored every 60 s${last ? `, last at ${formatTime(last)}` : ", not scored yet"}.`;

  return (
    <>
      <PageHeader
        title="Overview"
        sub={sub}
        actions={
          <>
            <HowTo title="How to read this view">
              Equipment is ranked by band, then health. Health is 100 at normal behaviour and 50 at
              the alert limit. Unknown means the model cannot score, not that the equipment is
              healthy. Select a row to see its deviation trend.
            </HowTo>
            <Seg
              label="Time window"
              value={win}
              options={WINDOWS}
              onChange={(v) => {
                params.set("window", v);
                setParams(params, { replace: true });
              }}
            />
          </>
        }
      />
      <Kpis label="Fleet summary" items={kpis} />
      <div className="two">
        <Panel
          title="Equipment needing attention"
          id="att-h"
          actions={
            <Link className="btn btn-s" to="/equipment">
              View all →
            </Link>
          }
        >
          <div className="tw fill">
            <table className="tb">
              <thead>
                <tr>
                  <th>Band</th>
                  <th>Equipment</th>
                  <th>Likely cause</th>
                  <th>Health</th>
                </tr>
              </thead>
              <tbody>
                {attention.slice(0, 8).map((n, i) => {
                  const diag = causes[i]?.data;
                  const top = diag?.modes.find(
                    (m) => !m.insufficient_evidence && (m.score ?? 0) > 0,
                  );
                  const cause =
                    n.band === "Unknown"
                      ? plainReason(n.models[0]?.reason)
                      : top
                        ? top.mode.name
                        : causes[i]?.isPending
                          ? "…"
                          : "No clear match";
                  return (
                    <tr
                      key={n.id}
                      className={`click${current?.id === n.id ? " sel" : ""}`}
                      tabIndex={0}
                      onClick={() => setPicked(n.id)}
                      onKeyDown={(e) => e.key === "Enter" && setPicked(n.id)}
                    >
                      <td>
                        <BandPill band={n.band} />
                      </td>
                      <td>
                        <IdChip to={`/assets/${n.id}`}>{n.code}</IdChip>{" "}
                        <span className="sec s13">{n.name}</span>
                      </td>
                      <td>
                        <Pill trunc title={cause}>
                          {cause}
                        </Pill>
                      </td>
                      <td>
                        <HealthBar health={n.health} band={n.band} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {attention.length === 0 && <Empty>Nothing needs attention in this scope.</Empty>}
          </div>
        </Panel>
        {current ? (
          <TrendPanel node={current} windowMs={windowMs(win)} />
        ) : (
          <Panel title="Deviation trend">
            <Empty>No equipment is monitored in this scope yet.</Empty>
          </Panel>
        )}
      </div>
      <Panel
        title="Recent events"
        id="ev-h"
        actions={
          <Link className="btn btn-s" to="/alerts">
            All events →
          </Link>
        }
      >
        <div className="tw">
          <table className="tb">
            <thead>
              <tr>
                <th>Opened</th>
                <th>Equipment</th>
                <th>Event</th>
                <th>Priority</th>
                <th>State</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => {
                const st = alertState(e.state);
                return (
                  <tr key={e.id}>
                    <td className="num sec">{formatDateTime(new Date(e.raised_at))}</td>
                    <td>
                      <IdChip to={`/assets/${e.asset_id}`}>{e.asset_code}</IdChip>
                    </td>
                    <td>{alertText(e)}</td>
                    <td>
                      <Badge>{e.priority ?? "—"}</Badge>
                    </td>
                    <td>
                      <Pill tone={st.tone}>{st.label}</Pill>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {events.length === 0 && <Empty>No open alerts in this scope.</Empty>}
        </div>
      </Panel>
    </>
  );
}

function TrendPanel({ node, windowMs: span }: { node: AssetNode; windowMs: number }) {
  const modelId = node.models[0]?.model_id;
  const [to] = useState(() => Date.now());
  const from = to - span;
  const scores = useQuery({
    queryKey: ["scores", modelId, span],
    queryFn: ({ signal }) => fetchScores(modelId!, new Date(from), new Date(to), 400, signal),
    enabled: !!modelId,
  });
  const model = useQuery({
    queryKey: ["models", modelId],
    queryFn: ({ signal }) => fetchModel(modelId!, signal),
    enabled: !!modelId,
  });
  const rule = model.data?.alert_rules.find((r) => r.kind === "di");
  const di = node.models[0] ? model.data?.runtime?.di : null;
  return (
    <Panel
      title={`${node.code} ${node.name}`}
      id="tr-h"
      actions={
        <Link className="btn btn-p" to={`/assets/${node.id}`}>
          Review →
        </Link>
      }
    >
      <div className="chips" style={{ marginBottom: 8 }}>
        <Pill>Health {node.health === null ? "n/a" : Math.round(node.health)}</Pill>
        <Pill>Deviation {di === null || di === undefined ? "n/a" : `${di.toFixed(1)} %`}</Pill>
        <BandPill band={node.band} />
      </div>
      {modelId ? (
        <>
          <Chart
            from={from}
            to={to}
            width={420}
            height={250}
            yMin={0}
            label={`Deviation trend for ${node.code}`}
            series={scores.data ? [{ points: trendPoints(scores.data, "di"), cls: "pv" }] : []}
            limits={
              rule
                ? [
                    { value: rule.warning, cls: "lw" },
                    { value: rule.alert, cls: "la" },
                  ]
                : []
            }
          />
          <Legend
            items={[
              { label: "Deviation %" },
              { cls: "w", label: "Warning" },
              { cls: "a", label: "Alert" },
            ]}
          />
        </>
      ) : (
        <Empty>No model scores this equipment yet.</Empty>
      )}
    </Panel>
  );
}
