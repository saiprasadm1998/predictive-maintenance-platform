import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { fetchRules } from "../../api/admin";
import { fetchLibrary } from "../../api/diagnostics";
import { fetchIngestionHealth } from "../../api/ingestion";
import { flatten } from "../../app/scope";
import {
  Badge,
  HowTo,
  ICONS,
  Icon,
  KeyValues,
  Loading,
  PageHeader,
  Panel,
  Pill,
  type ToneName,
} from "../../components/ui";
import { useEquipmentSetup, useUnmapped } from "./setupModel";

type StepKey = "hierarchy" | "equipment" | "tags" | "mapping" | "history" | "models";

interface Card {
  key: StepKey;
  title: string;
  value: string;
  done: boolean;
  icon: string;
}

interface Attention {
  kind: string;
  text: ReactNode;
  action: string;
  to: string;
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function SetupOverviewPage() {
  const [params, setParams] = useSearchParams();
  const { rows, loading, tags, coverage, scope } = useEquipmentSetup();
  const unmapped = useUnmapped();
  const library = useQuery({
    queryKey: ["library", "all"],
    queryFn: ({ signal }) => fetchLibrary(null, false, signal),
  });
  const rules = useQuery({
    queryKey: ["dq", "rules", "global"],
    queryFn: ({ signal }) => fetchRules("global", signal),
  });
  const ingestion = useQuery({
    queryKey: ["ingestion", "health"],
    queryFn: ({ signal }) => fetchIngestionHealth(signal),
  });

  if (loading) return <Loading what="setup" />;

  const nodes = flatten(scope.tree);
  const sites = nodes.filter((n) => n.level === "site").length;
  const units = nodes.filter((n) => n.level === "unit").length;
  const allTags = tags.data ?? [];
  const rolesTotal = rows.reduce((a, r) => a + r.rolesTotal, 0);
  const rolesMapped = rows.reduce((a, r) => a + r.rolesMapped, 0);
  const withHistory = rows.filter((r) => r.historyDays).length;
  const longest = Math.max(0, ...rows.map((r) => r.historyDays ?? 0));
  const deployed = rows.filter((r) => r.model?.in_service).length;
  const unmappedCount = unmapped.data?.length ?? 0;

  const cards: Card[] = [
    {
      key: "hierarchy",
      title: "1. Plant hierarchy",
      value: `${sites} site${sites === 1 ? "" : "s"}, ${units} unit${units === 1 ? "" : "s"}`,
      done: units > 0,
      icon: ICONS.hierarchy,
    },
    {
      key: "equipment",
      title: "2. Equipment",
      value: `${rows.length} equipment`,
      done: rows.length > 0 && rows.every((r) => r.type),
      icon: ICONS.equipment,
    },
    {
      key: "tags",
      title: "3. Tags",
      value: `${allTags.length} registered`,
      done: allTags.length > 0 && unmappedCount === 0,
      icon: ICONS.tag,
    },
    {
      key: "mapping",
      title: "4. Tag mapping",
      value: `${rolesMapped} of ${rolesTotal}`,
      done: rows.every((r) => r.missingRequired.length === 0),
      icon: ICONS.map,
    },
    {
      key: "history",
      title: "5. Historical data",
      value: longest ? `${longest} days` : "None yet",
      done: rows.length > 0 && withHistory === rows.length,
      icon: ICONS.database,
    },
    {
      key: "models",
      title: "6. Models",
      value: `${deployed} deployed`,
      done: rows.length > 0 && rows.every((r) => r.readiness === "ready"),
      icon: ICONS.trend,
    },
  ];
  const firstOpen = cards.find((c) => !c.done)?.key ?? "models";
  const selected = (params.get("step") as StepKey | null) ?? firstOpen;
  const pick = (key: StepKey) => {
    params.set("step", key);
    setParams(params, { replace: true });
  };

  const attention: Attention[] = [
    ...(unmapped.data ?? []).slice(0, 3).map((u) => ({
      kind: "Tags",
      text: (
        <>
          <span className="mono">{u.source_name}</span> is arriving but not registered
        </>
      ),
      action: "Register",
      to: "/setup/tags?tab=unmapped",
    })),
    ...rows
      .filter((r) => r.missingRequired.length)
      .map((r) => ({
        kind: "Mapping",
        text: `${r.node.code} has no tag for ${r.missingRequired.map((x) => x.replace(/_/g, " ")).join(", ")}`,
        action: "Map",
        to: `/setup/tags?asset=${r.node.id}`,
      })),
    ...rows
      .filter((r) => !r.historyDays && r.tags.length)
      .map((r) => ({
        kind: "History",
        text: `${r.node.code} has no stored history`,
        action: "Upload",
        to: "/setup/history/upload",
      })),
    ...rows
      .filter((r) => r.readiness === "review" || r.readiness === "no-model")
      .map((r) => ({
        kind: "Models",
        text:
          r.readiness === "review"
            ? `${r.node.code} v${r.model?.latest.version} is waiting for review`
            : `${r.node.code} has no model yet`,
        action: r.readiness === "review" ? "Review" : "Build",
        to: r.model
          ? `/models/${r.model.id}/versions/${r.model.latest.version}`
          : `/models/new/build/1?asset=${encodeURIComponent(r.node.code)}`,
      })),
  ];

  const cov = coverage.data ?? [];
  const firstTs = cov.reduce<string | null>(
    (a, c) => (a === null || c.first_ts < a ? c.first_ts : a),
    null,
  );
  const lastTs = cov.reduce<string | null>(
    (a, c) => (a === null || c.last_ts > a ? c.last_ts : a),
    null,
  );
  const samples = cov.reduce((a, c) => a + c.samples, 0);

  const detail: Record<StepKey, { body: ReactNode; actions: ReactNode }> = {
    hierarchy: {
      body: (
        <KeyValues
          rows={[
            ["Sites", sites],
            ["Units", units],
            ["Equipment", rows.length],
          ]}
        />
      ),
      actions: (
        <Link className="btn btn-p" to="/setup/hierarchy">
          Open plant hierarchy
        </Link>
      ),
    },
    equipment: {
      body: (
        <KeyValues
          rows={[
            ["Equipment", rows.length],
            ["Without a type", rows.filter((r) => !r.type).length],
            ["Ready and scoring", rows.filter((r) => r.readiness === "ready").length],
          ]}
        />
      ),
      actions: (
        <>
          <Link className="btn btn-s" to="/setup/equipment">
            Equipment register
          </Link>
          <Link className="btn btn-p" to="/setup/equipment/new">
            Add equipment
          </Link>
        </>
      ),
    },
    tags: {
      body: (
        <KeyValues
          rows={[
            ["Registered", allTags.length],
            ["Arriving but not registered", unmappedCount],
          ]}
        />
      ),
      actions: (
        <Link className="btn btn-p" to="/setup/tags">
          Tags and mapping
        </Link>
      ),
    },
    mapping: {
      body: (
        <KeyValues
          rows={[
            ["Roles with a tag", `${rolesMapped} of ${rolesTotal}`],
            [
              "Equipment missing a required role",
              rows.filter((r) => r.missingRequired.length).length,
            ],
          ]}
        />
      ),
      actions: (
        <Link className="btn btn-p" to="/setup/tags">
          Map tags
        </Link>
      ),
    },
    history: {
      body: (
        <KeyValues
          rows={[
            [
              "Span",
              firstTs && lastTs ? `${fmtDate(firstTs)} to ${fmtDate(lastTs)}` : "No data stored",
            ],
            ["Tags covered", `${cov.length} of ${allTags.length}`],
            [
              "Samples",
              samples >= 1e6 ? `${(samples / 1e6).toFixed(1)} million` : samples.toLocaleString(),
            ],
            ["Equipment with history", `${withHistory} of ${rows.length}`],
          ]}
        />
      ),
      actions: (
        <>
          <Link className="btn btn-s" to="/setup/history">
            Past uploads
          </Link>
          <Link className="btn btn-p" to="/setup/history/upload">
            Upload history
          </Link>
        </>
      ),
    },
    models: {
      body: (
        <KeyValues
          rows={[
            ["Deployed", deployed],
            ["Waiting for review", rows.filter((r) => r.readiness === "review").length],
            ["Cannot score", rows.filter((r) => r.readiness === "cannot").length],
            ["No model yet", rows.filter((r) => r.readiness === "no-model").length],
          ]}
        />
      ),
      actions: (
        <Link className="btn btn-p" to="/models">
          Open models
        </Link>
      ),
    },
  };
  const current = cards.find((c) => c.key === selected) ?? cards[0]!;
  const sources = ingestion.data?.sources ?? [];
  const connected = sources.length > 0 && sources.some((s) => !s.stale);
  const overrides = Object.keys(rules.data?.overrides ?? {}).length;
  const modes = library.data ?? [];
  const modeTypes = new Set(modes.map((m) => m.asset_type)).size;

  return (
    <>
      <PageHeader
        title="Setup overview"
        sub="Set up in order. Each step builds on the one before it."
        actions={
          <HowTo title="How setup works" label="How setup works">
            Build the plant tree, register each piece of equipment, map its tags to roles, upload
            history covering normal operation, then train and deploy a model. Equipment gets a
            health score once its model is deployed.
          </HowTo>
        }
      />
      <section
        className="kpis"
        style={{ gridTemplateColumns: "repeat(6, minmax(0, 1fr))" }}
        aria-label="Setup steps"
      >
        {cards.map((c) => {
          const tone: ToneName = c.done ? "success" : "warning";
          return (
            <button
              key={c.key}
              type="button"
              className={`kpi k-${tone}`}
              aria-pressed={c.key === current.key}
              onClick={() => pick(c.key)}
              style={
                c.key === current.key
                  ? { background: "var(--traverse-surface-selected)" }
                  : undefined
              }
            >
              <span className="kh">
                <span className="kl">{c.title}</span>
                <span className="ki">
                  <Icon d={c.icon} />
                </span>
              </span>
              <span className="kv" style={{ fontSize: 17 }}>
                {c.value}
              </span>
              <span>
                <Pill tone={tone}>{c.done ? "Complete" : "Needs attention"}</Pill>
              </span>
            </button>
          );
        })}
      </section>
      <div className="two">
        <Panel title={current.title} actions={detail[current.key].actions}>
          {detail[current.key].body}
        </Panel>
        <Panel
          title="Needs your attention"
          actions={<Badge tone={attention.length ? "warning" : null}>{attention.length}</Badge>}
        >
          {attention.length === 0 ? (
            <p className="sec s13">Nothing waiting. Every step is complete.</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column" }}>
              {attention.slice(0, 6).map((a, i) => (
                <div
                  key={i}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "auto minmax(0, 1fr) auto",
                    gap: 12,
                    alignItems: "center",
                    padding: "8px 0",
                    borderTop: i ? "1px solid var(--traverse-border-subtle)" : undefined,
                  }}
                >
                  <Pill tone="warning">{a.kind}</Pill>
                  <span className="s13">{a.text}</span>
                  <Link className="btn btn-s btn-sm" to={a.to}>
                    {a.action}
                  </Link>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
      <div className="three">
        <Panel title="Failure modes" actions={<Badge>{modes.length} modes</Badge>}>
          <p className="sec s13" style={{ marginBottom: 16 }}>
            Symptoms and checks for {modeTypes} equipment type{modeTypes === 1 ? "" : "s"}
          </p>
          <span>
            <Link className="btn btn-s" to="/library">
              Open library
            </Link>
          </span>
        </Panel>
        <Panel title="Data-quality rules" actions={<Badge>{overrides} overrides</Badge>}>
          <p className="sec s13" style={{ marginBottom: 16 }}>
            Stale, frozen, range and spike checks
          </p>
          <span>
            <Link className="btn btn-s" to="/setup/data-quality">
              Edit rules
            </Link>
          </span>
        </Panel>
        <Panel
          title="Data source"
          actions={
            <Pill tone={connected ? "info" : "warning"}>
              {connected ? "Connected" : "No live data"}
            </Pill>
          }
        >
          <p className="sec s13" style={{ marginBottom: 16 }}>
            {sources.length} gateway{sources.length === 1 ? "" : "s"},{" "}
            {sources.reduce((a, s) => a + s.tags, 0)} tags receiving
          </p>
          <span>
            <Link className="btn btn-s" to="/system/ingestion">
              Ingestion health
            </Link>
          </span>
        </Panel>
      </div>
    </>
  );
}
