import { useQueries, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import { fetchAlerts } from "../../api/alerts";
import { fetchAsset } from "../../api/assets";
import { fetchScores } from "../../api/models";
import type { AssetNode } from "../../api/types";
import { useBreadcrumbs } from "../../app/breadcrumbs";
import { formatDi, formatHealth } from "../../app/format";
import { timeRangeParams, useTimeRange } from "../../app/timeRange";
import { Sparkline } from "../../components/Sparkline";
import { StatusChip } from "../../components/StatusChip";
import { TrendChart } from "../../components/TrendChart";
import { Skeleton } from "./FleetPage";
import {
  assetLabel,
  assetLink,
  equipmentUnder,
  openAlertSeries,
  unknownReason,
} from "./fleetModel";

const SPARK_DAYS = 7;
const SPARK_PX = 84; // one point every 2 hours

/**
 * SCR-08 Area / unit view (PDS §4.8, FR-VIS-01, FR-HLT-01): which assets in this unit are
 * abnormal and how the unit is trending. One card per monitored asset (band, Health, 7-day
 * DI sparkline, open alerts) and the unit's open-alert count over the chosen period.
 */
export function UnitPage() {
  const id = Number(useParams().assetId);
  const location = useLocation();
  const carried = timeRangeParams(new URLSearchParams(location.search)).toString();
  const withRange = (path: string) => `${path}${carried ? `?${carried}` : ""}`;
  const { range } = useTimeRange();

  const detail = useQuery({
    queryKey: ["assets", "detail", id],
    queryFn: ({ signal }) => fetchAsset(id, signal),
    enabled: Number.isFinite(id),
  });
  const asset = detail.data;
  useBreadcrumbs(
    asset
      ? [
          { label: "Fleet", to: "/fleet" },
          ...asset.ancestors.map((a) => ({ label: a.name, to: `/units/${a.id}` })),
          { label: asset.name },
        ]
      : null,
  );

  const alerts = useQuery({
    queryKey: ["alerts", "unit", asset?.code],
    queryFn: ({ signal }) =>
      fetchAlerts({ asset: asset!.code, includeClosed: true, limit: 1000 }, signal),
    enabled: !!asset,
  });

  const cards = useMemo(() => (asset ? equipmentUnder(asset.health) : []), [asset]);
  const sparkTo = useMemo(() => {
    const now = new Date();
    now.setSeconds(0, 0);
    return now;
  }, []);
  const sparkFrom = useMemo(() => new Date(sparkTo.getTime() - SPARK_DAYS * 86_400_000), [sparkTo]);
  const sparks = useQueries({
    queries: cards.flatMap((card) =>
      card.models.map((m) => ({
        queryKey: ["scores", m.model_id, "spark", sparkFrom.toISOString()],
        queryFn: ({ signal }: { signal: AbortSignal }) =>
          fetchScores(m.model_id, sparkFrom, sparkTo, SPARK_PX, signal),
      })),
    ),
  });
  const sparkOf = new Map<number, (number | null)[]>();
  let index = 0;
  for (const card of cards) {
    for (const m of card.models) {
      const data = sparks[index++]?.data;
      if (data) sparkOf.set(m.model_id, data.max.di ?? []);
    }
  }

  const from = range.from.getTime();
  const to = range.to.getTime();
  const alertTrend = useMemo(
    () => openAlertSeries(alerts.data?.items ?? [], from, to),
    [alerts.data, from, to],
  );

  if (detail.isError) {
    return (
      <section className="panel" role="alert">
        {detail.error.message}
      </section>
    );
  }
  if (!asset) return <Skeleton rows={6} />;
  const node = asset.health;
  const open = node.open_alerts;

  return (
    <div className="unit">
      <section className="panel unit-head" aria-label={`${asset.name} summary`}>
        <div>
          <div className="unit-title">{asset.name}</div>
          <div className="muted">
            {asset.code} · {asset.level}
          </div>
        </div>
        <div className="unit-figures">
          {node.band ? (
            <StatusChip kind="band" value={node.band} />
          ) : (
            <span className="muted">Not monitored</span>
          )}
          <span>
            Health <b>{formatHealth(node.health)}</b>
          </span>
          <span>
            <b>{open}</b> open alert{open === 1 ? "" : "s"}
          </span>
          <span className="muted">
            {(["Alert", "Watch", "Unknown", "Healthy"] as const)
              .filter((b) => node.counts[b])
              .map((b) => `${b} ${node.counts[b]}`)
              .join(" · ")}
          </span>
        </div>
      </section>

      {cards.length === 0 ? (
        <section className="panel">
          <p className="muted">No monitored assets here yet. Models are added under Models.</p>
        </section>
      ) : (
        <ul className="cards" aria-label="Assets">
          {cards.map((card) => (
            <AssetCard
              key={card.id}
              node={card}
              link={withRange(assetLink(card))}
              spark={card.models[0] ? sparkOf.get(card.models[0].model_id) : undefined}
            />
          ))}
        </ul>
      )}

      <section className="panel">
        <TrendChart
          title={`Open alerts in ${asset.name}`}
          data={{ actual: alertTrend }}
          settings={{ unit: "alerts", from, to, actualName: "Open alerts" }}
          height={160}
          loading={alerts.isPending}
        />
      </section>
    </div>
  );
}

function AssetCard({
  node,
  link,
  spark,
}: {
  node: AssetNode;
  link: string;
  spark: (number | null)[] | undefined;
}) {
  const reason = unknownReason(node);
  const latestDi = spark?.filter((v): v is number => v !== null).at(-1);
  return (
    <li className="panel card">
      <Link to={link} className="card-title">
        {assetLabel(node)}
      </Link>
      <div className="card-row" title={reason ?? undefined}>
        {node.band ? <StatusChip kind="band" value={node.band} detail={reason} /> : null}
        <span className="card-health">
          Health <b>{formatHealth(node.health)}</b>
        </span>
      </div>
      <div className="card-spark">
        {spark === undefined ? (
          <span className="muted">Loading DI…</span>
        ) : (
          <Sparkline
            values={spark}
            width={120}
            label={`${node.code} Deviation Index, last 7 days (%)`}
          />
        )}
        <span className="muted nowrap">DI {formatDi(latestDi ?? null)} · 7 d</span>
      </div>
      <div className="muted">
        {node.open_alerts
          ? `${node.open_alerts} open alert${node.open_alerts === 1 ? "" : "s"}`
          : "No open alerts"}
      </div>
    </li>
  );
}
