import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useModels, useSensorHealth } from "../../app/data";
import { locations } from "../../app/places";
import { useScope } from "../../app/scope";
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
} from "../../components/ui";

function downloadCsv(name: string, rows: (string | number)[][]) {
  const text = rows
    .map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(","))
    .join("\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export function EquipmentPage() {
  const scope = useScope();
  const models = useModels();
  const sensors = useSensorHealth();
  const [params, setParams] = useSearchParams();
  const band = params.get("band");
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [crit, setCrit] = useState("");
  const where = useMemo(() => locations(scope.tree), [scope.tree]);

  const all = scope.equipment;
  const types = [
    ...new Set(all.map((n) => n.asset_type_name ?? n.asset_type).filter(Boolean)),
  ] as string[];
  const rows = all.filter((n) => {
    const needle = q.trim().toLowerCase();
    if (band && (n.band ?? "Not monitored") !== band) return false;
    if (type && (n.asset_type_name ?? n.asset_type) !== type) return false;
    if (crit && n.criticality !== crit) return false;
    return (
      !needle || n.code.toLowerCase().includes(needle) || n.name.toLowerCase().includes(needle)
    );
  });
  const model = (code: string) => (models.data ?? []).find((m) => m.asset_code === code);
  const coverage = (code: string) => {
    const mine = (sensors.data ?? []).filter((s) => s.asset_code === code && s.models.length);
    return mine.length
      ? `${mine.filter((s) => s.status === "Good").length} of ${mine.length}`
      : "—";
  };
  const count = (b: string) => all.filter((n) => n.band === b).length;
  const pick = (b: string) => {
    if (band === b) params.delete("band");
    else params.set("band", b);
    setParams(params, { replace: true });
  };

  const exportCsv = () =>
    downloadCsv("equipment.csv", [
      [
        "Tag",
        "Name",
        "Location",
        "Type",
        "Criticality",
        "Band",
        "Health",
        "Deviation %",
        "Coverage",
        "Open alerts",
        "Model",
      ],
      ...rows.map((n) => {
        const m = model(n.code);
        return [
          n.code,
          n.name,
          where.get(n.id) ?? "",
          n.asset_type_name ?? n.asset_type ?? "",
          n.criticality ?? "",
          n.band ?? "Not monitored",
          n.health === null ? "" : Math.round(n.health),
          m?.runtime?.di?.toFixed(1) ?? "",
          coverage(n.code),
          n.open_alerts,
          m ? `${m.name} v${m.in_service?.version ?? m.latest.version}` : "",
        ];
      }),
    ]);

  return (
    <>
      <PageHeader
        title="Equipment"
        sub={`${rows.length} of ${all.length} equipment in scope`}
        actions={
          <>
            <HowTo title="How to read this view">
              One row per equipment. Band and health come from its live model. Coverage shows how
              many sensors could be used in the last cycle. Select a row to open its analysis.
            </HowTo>
            <button className="btn btn-s" type="button" onClick={exportCsv}>
              Export CSV
            </button>
          </>
        }
      />
      <Kpis
        cols={4}
        label="Band totals"
        items={[
          {
            label: "In alert",
            value: count("Alert"),
            tone: "danger",
            icon: ICONS.alert,
            onClick: () => pick("Alert"),
            pressed: band === "Alert",
          },
          {
            label: "In watch",
            value: count("Watch"),
            tone: "warning",
            icon: ICONS.watch,
            onClick: () => pick("Watch"),
            pressed: band === "Watch",
          },
          {
            label: "Unknown",
            value: count("Unknown"),
            tone: "unknown",
            icon: ICONS.unknown,
            onClick: () => pick("Unknown"),
            pressed: band === "Unknown",
          },
          {
            label: "Healthy",
            value: count("Healthy"),
            tone: "neutral",
            icon: ICONS.healthy,
            onClick: () => pick("Healthy"),
            pressed: band === "Healthy",
          },
        ]}
      />
      <Panel className="fill">
        <div className="pnlh">
          <div className="filters">
            <div className="fld">
              <label htmlFor="eq-f">Find</label>
              <input
                id="eq-f"
                className="in"
                type="search"
                placeholder="Tag or name"
                style={{ width: 240 }}
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </div>
            <div className="fld">
              <label htmlFor="eq-t">Type</label>
              <select
                id="eq-t"
                className="sl"
                style={{ width: 220 }}
                value={type}
                onChange={(e) => setType(e.target.value)}
              >
                <option value="">All types</option>
                {types.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </div>
            <div className="fld">
              <label htmlFor="eq-c">Criticality</label>
              <select
                id="eq-c"
                className="sl"
                style={{ width: 160 }}
                value={crit}
                onChange={(e) => setCrit(e.target.value)}
              >
                <option value="">All</option>
                <option>A</option>
                <option>B</option>
                <option>C</option>
              </select>
            </div>
          </div>
          {band && (
            <button className="btn btn-g" type="button" onClick={() => pick(band)}>
              Clear band filter
            </button>
          )}
        </div>
        <div className="tw">
          <table className="tb">
            <thead>
              <tr>
                <th>Equipment</th>
                <th>Location</th>
                <th>Type</th>
                <th>Criticality</th>
                <th>Band</th>
                <th>Health</th>
                <th className="r">Deviation</th>
                <th>Coverage</th>
                <th>Open alerts</th>
                <th>Model</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((n) => {
                const m = model(n.code);
                return (
                  <tr key={n.id}>
                    <td>
                      <IdChip to={`/assets/${n.id}`}>{n.code}</IdChip>{" "}
                      <span className="sec s13">{n.name}</span>
                    </td>
                    <td className="sec">{where.get(n.id)}</td>
                    <td>{n.asset_type_name ?? n.asset_type ?? "—"}</td>
                    <td>{n.criticality ? <Badge>{n.criticality}</Badge> : "—"}</td>
                    <td>
                      <BandPill band={n.band} />
                    </td>
                    <td>
                      <HealthBar health={n.health} band={n.band} />
                    </td>
                    <td className="r num">
                      {m?.runtime?.di === null || m?.runtime?.di === undefined
                        ? "n/a"
                        : `${m.runtime.di.toFixed(1)} %`}
                    </td>
                    <td className="num">{coverage(n.code)}</td>
                    <td className="num">{n.open_alerts}</td>
                    <td className="mono sec">
                      {m ? `${m.name} v${m.in_service?.version ?? m.latest.version}` : "No model"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length === 0 && <Empty>No equipment matches these filters.</Empty>}
        </div>
      </Panel>
    </>
  );
}
