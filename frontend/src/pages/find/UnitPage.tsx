import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";

import { fetchAllAlerts } from "../../api/alerts";
import { fetchModel, fetchScores } from "../../api/models";
import type { AssetNode } from "../../api/types";
import { useCases, useSensorHealth } from "../../app/data";
import { formatDateTime } from "../../app/format";
import { find, flatten, nodesOfLevel, useScope } from "../../app/scope";
import { trendPoints } from "../../components/chartData";
import { BandPill, Empty, HealthBar, HowTo, PageHeader, Panel } from "../../components/ui";

const DAY = 86_400_000;

/** /units without an id: the first unit in scope. */
export function UnitIndexPage() {
  const scope = useScope();
  const units = nodesOfLevel(scope.node ? [scope.node] : scope.tree, "unit");
  if (!scope.tree.length) return <p className="sec s13">Loading…</p>;
  if (!units.length)
    return (
      <>
        <PageHeader title="Unit view" />
        <Panel>
          <Empty>No units in this scope. Add them in Plant hierarchy.</Empty>
        </Panel>
      </>
    );
  return <Navigate to={`/units/${units[0]!.id}`} replace />;
}

export function UnitPage() {
  const { assetId } = useParams();
  const navigate = useNavigate();
  const scope = useScope();
  const unit = find(scope.tree, Number(assetId));
  const units = nodesOfLevel(scope.tree, "unit");
  const cases = useCases(true);
  const sensors = useSensorHealth();
  const [now] = useState(() => Date.now());
  const history = useQuery({
    queryKey: ["alerts", "unit", unit?.code],
    queryFn: async ({ signal }) =>
      (await fetchAllAlerts({ asset: unit!.code, includeClosed: true }, signal)).items,
    enabled: !!unit,
  });

  if (!scope.tree.length) return <p className="sec s13">Loading…</p>;
  if (!unit) return <Navigate to="/units" replace />;

  const equipment = flatten([unit]).filter((n) => n.level === "equipment");
  const ids = new Set(equipment.map((n) => n.id));
  const codes = new Set(equipment.map((n) => n.code));
  const scored = equipment.filter((n) => n.health !== null);
  const lowest = scored.length ? Math.min(...scored.map((n) => n.health!)) : null;
  const open = (history.data ?? []).filter((a) => !a.closed_at);
  const unack = open.filter(
    (a) => a.state === "Active-Unacknowledged" || a.state === "RTN-Unacknowledged",
  ).length;
  const unitSensors = (sensors.data ?? []).filter((s) => codes.has(s.asset_code));
  const good = unitSensors.filter((s) => s.status === "Good").length;
  const openCases = (cases.data ?? []).filter((c) => ids.has(c.asset_id)).length;

  // Open alerts at the end of each of the last 30 days.
  const days = Array.from({ length: 30 }, (_, i) => now - (29 - i) * DAY);
  const counts = days.map(
    (t) =>
      (history.data ?? []).filter(
        (a) => Date.parse(a.raised_at) <= t && (!a.closed_at || Date.parse(a.closed_at) > t),
      ).length,
  );
  const top = Math.max(4, ...counts);
  const crumbs = [
    { label: "Overview", to: "/fleet" },
    ...unitAncestors(scope.tree, unit),
    { label: unit.name },
  ];

  return (
    <>
      <PageHeader
        crumbs={crumbs}
        title={unit.name}
        sub="Unit health is the lowest health of its equipment; open alerts are summed"
        actions={
          <>
            <HowTo title="About the unit view">
              Each card shows one piece of equipment: band, health and the Deviation Index over 7
              days with its alert limit. Open a card for the full diagnosis. The chart below counts
              open alerts at the end of each day.
            </HowTo>
            <select
              className="sl"
              aria-label="Unit"
              style={{ width: 220 }}
              value={unit.id}
              onChange={(e) => void navigate(`/units/${e.target.value}`)}
            >
              {units.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
            </select>
          </>
        }
      />
      <section className="strip" aria-label="Unit summary">
        <div>
          <span className="l">Band</span>
          <span className="v">
            <BandPill band={unit.band} />
          </span>
        </div>
        <div>
          <span className="l">Unit health</span>
          <span className="v">
            {lowest === null ? "n/a" : Math.round(lowest)}
            <small>lowest of {equipment.length}</small>
          </span>
        </div>
        <div>
          <span className="l">Open alerts</span>
          <span className="v">
            {open.length}
            <small>{unack} unacknowledged</small>
          </span>
        </div>
        <div>
          <span className="l">Open cases</span>
          <span className="v">{openCases}</span>
        </div>
        <div>
          <span className="l">Sensors in scoring</span>
          <span className="v">
            {good} of {unitSensors.length}
          </span>
        </div>
      </section>
      {equipment.length ? (
        <section className="three" aria-label="Equipment in the unit">
          {equipment.map((n) => (
            <UnitCard key={n.id} node={n} now={now} />
          ))}
        </section>
      ) : (
        <Panel>
          <Empty>No equipment in this unit yet.</Empty>
        </Panel>
      )}
      <Panel
        title="Open alerts over time"
        id="oa-h"
        className="fill"
        actions={
          <Link to="/alerts" className="s13">
            Open the alert list
          </Link>
        }
      >
        <svg
          className="chart"
          viewBox="0 0 1100 200"
          role="img"
          aria-label={`Open alerts at the end of each day, last 30 days; now ${open.length}`}
        >
          <line className="g" x1="40" x2="1090" y1="20" y2="20" />
          <line className="g" x1="40" x2="1090" y1="90" y2="90" />
          <line className="ax" x1="40" x2="1090" y1="160" y2="160" />
          <text x="34" y="24" textAnchor="end">
            {top}
          </text>
          <text x="34" y="94" textAnchor="end">
            {Math.round(top / 2)}
          </text>
          <text x="34" y="164" textAnchor="end">
            0
          </text>
          {counts.map((c, i) => {
            const h = (c / top) * 140;
            return (
              <rect key={i} className="bar" x={44 + i * 35} y={160 - h} width={26} height={h} />
            );
          })}
          <text x="40" y="184">
            {formatDateTime(new Date(days[0]!)).slice(0, 6)}
          </text>
          <text x="565" y="184" textAnchor="middle">
            {formatDateTime(new Date(days[15]!)).slice(0, 6)}
          </text>
          <text x="1090" y="184" textAnchor="end">
            {formatDateTime(new Date(now)).slice(0, 6)}
          </text>
        </svg>
      </Panel>
    </>
  );
}

function unitAncestors(tree: AssetNode[], unit: AssetNode): { label: string }[] {
  const path: AssetNode[] = [];
  const walk = (nodes: AssetNode[], trail: AssetNode[]): boolean => {
    for (const n of nodes) {
      if (n.id === unit.id) {
        path.push(...trail);
        return true;
      }
      if (walk(n.children, [...trail, n])) return true;
    }
    return false;
  };
  walk(tree, []);
  const names = path.filter((n) => n.level !== "enterprise").map((n) => n.name);
  return names.length ? [{ label: names.join(" / ") }] : [];
}

function UnitCard({ node, now }: { node: AssetNode; now: number }) {
  const modelId = node.models[0]?.model_id;
  const scores = useQuery({
    queryKey: ["scores", modelId, "spark7d"],
    queryFn: ({ signal }) =>
      fetchScores(modelId!, new Date(now - 7 * DAY), new Date(now), 120, signal),
    enabled: !!modelId,
  });
  const model = useQuery({
    queryKey: ["models", modelId],
    queryFn: ({ signal }) => fetchModel(modelId!, signal),
    enabled: !!modelId,
  });
  const alertLimit = model.data?.alert_rules.find((r) => r.kind === "di")?.alert ?? null;
  const pts = scores.data ? trendPoints(scores.data, "di").filter((p) => p[1] !== null) : [];
  const vals = pts.map((p) => p[1]!);
  const top = Math.max(1, ...vals, alertLimit ?? 0) * 1.1;
  const x = (t: number) => ((t - (now - 7 * DAY)) / (7 * DAY)) * 300;
  const y = (v: number) => 54 - (v / top) * 50;
  const d = pts
    .map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]!).toFixed(1)}`)
    .join("");
  const di = model.data?.runtime?.di;
  return (
    <Link className="pnl uc" to={`/assets/${node.id}`}>
      <div className="row">
        <span className="pt">
          {node.code}{" "}
          <span className="sec s13" style={{ fontWeight: 400 }}>
            {node.name}
          </span>
        </span>
        <BandPill band={node.band} />
      </div>
      <div className="row s13">
        <HealthBar health={node.health} band={node.band} />
        <span className="sec">{node.open_alerts} open alerts</span>
      </div>
      <svg
        className="spk"
        viewBox="0 0 300 56"
        preserveAspectRatio="none"
        role="img"
        aria-label={`Deviation Index of ${node.code}, last 7 days`}
      >
        {alertLimit !== null && <line x1="0" x2="300" y1={y(alertLimit)} y2={y(alertLimit)} />}
        <path d={d} />
      </svg>
      <div className="row meta">
        <span>Deviation Index, 7 days</span>
        <span>Now {di === null || di === undefined ? "n/a" : `${di.toFixed(1)} %`}</span>
      </div>
    </Link>
  );
}
