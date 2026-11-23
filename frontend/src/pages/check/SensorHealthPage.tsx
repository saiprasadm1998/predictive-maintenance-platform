import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { endExclusion } from "../../api/admin";
import { fetchAllTags } from "../../api/registry";
import { useSensorHealth } from "../../app/data";
import { formatDateTime } from "../../app/format";
import { flatten, useScope } from "../../app/scope";
import { NE107_CODE, plainDescription, shortTag } from "../../app/words";
import { Empty, HowTo, ICONS, Icon, IdChip, PageHeader, Panel } from "../../components/ui";
import { ExcludeDialog } from "./ExcludeDialog";

const ORDER = ["Failure", "Out of specification", "Function check", "Maintenance required", "Good"];
const RULES: Record<string, string> = {
  bad_quality: "Bad quality from source",
  stale: "Stale, no new sample",
  manual_exclusion: "Manual exclusion",
  out_of_range: "Outside the instrument range",
  flatline: "Frozen value",
  spike: "Spike, sample removed",
  uncertain_quality: "Uncertain quality from source",
  override: "Status overridden to Good",
  none: "No rule triggered",
};
const EFFECT: Record<string, string> = {
  used: "Used",
  used_flagged: "Used, flagged",
  excluded: "Left out",
  sample_excluded: "Sample removed",
};

function reason(rule: string, effect: string): string {
  return RULES[rule] ?? (rule ? rule.replace(/_/g, " ") : effect || "—");
}

export function SensorHealthPage() {
  const scope = useScope();
  const client = useQueryClient();
  const health = useSensorHealth();
  const tags = useQuery({
    queryKey: ["tags", "all"],
    queryFn: ({ signal }) => fetchAllTags(signal),
  });
  const [showGood, setShowGood] = useState(false);
  const [equipment, setEquipment] = useState("");
  const [excluding, setExcluding] = useState<{ id: number; name: string } | null>(null);
  const end = useMutation({
    mutationFn: (id: number) => endExclusion(id),
    onSuccess: () =>
      void client.invalidateQueries({
        predicate: (q) => ["sensors", "models"].includes(String(q.queryKey[0])),
      }),
  });

  const nodes = flatten(scope.tree);
  const assetId = (code: string) => nodes.find((n) => n.code === code)?.id;
  const codes = new Set(scope.equipment.map((n) => n.code));
  const inScope = (health.data ?? []).filter((s) => scope.ids === null || codes.has(s.asset_code));
  const desc = (id: number) => tags.data?.find((t) => t.id === id)?.description ?? "";
  const inModels = inScope.filter((s) => s.models.length);
  const count = (st: string) => inScope.filter((s) => s.status === st).length;
  const rows = inScope
    .filter(
      (s) =>
        (showGood || s.status !== "Good" || s.exclusion) &&
        (!equipment || s.asset_code === equipment),
    )
    .sort(
      (a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status) || a.since.localeCompare(b.since),
    );
  const bad = inScope.filter((s) => s.status !== "Good");
  const affected = new Set(bad.flatMap((s) => s.models)).size;
  const equipmentCodes = [...new Set(inScope.map((s) => s.asset_code))].sort();

  const kpi = (label: string, n: number, code: string | null, tone: string) => (
    <div key={label} className={`kpi k-${tone}`}>
      <span className="kh">
        <span className="kl">{label}</span>
        <span className="ki">
          {code ? (
            <span className={`diag ${NE107_CODE[label]?.cls ?? ""}`}>{code}</span>
          ) : (
            <Icon d={ICONS.gauge} />
          )}
        </span>
      </span>
      <span className="kv">{n}</span>
    </div>
  );

  return (
    <>
      <PageHeader
        title="Sensor health"
        sub="Data quality is checked before any analytics run"
        actions={
          <>
            <HowTo title="How to read this view">
              Categories follow NAMUR NE 107. Failure, Out of specification, Function check and
              frozen values are left out of scoring. A spike removes only that sample. Exclusions
              and overrides need a reason and an end time.
            </HowTo>
            <label className="chk">
              <input
                type="checkbox"
                checked={showGood}
                onChange={(e) => setShowGood(e.target.checked)}
              />
              Show Good sensors
            </label>
          </>
        }
      />
      <section className="kpis" aria-label="Sensor status totals">
        {kpi("Sensors in models", inModels.length, null, "neutral")}
        {kpi("Failure", count("Failure"), "F", "danger")}
        {kpi("Out of specification", count("Out of specification"), "S", "warning")}
        {kpi("Maintenance required", count("Maintenance required"), "M", "info")}
        {kpi("Function check", count("Function check"), "C", "warning")}
      </section>
      <Panel
        className="fill"
        title={`Sensors not Good (${bad.length}), ${affected} model${affected === 1 ? "" : "s"} affected`}
        id="sl-h"
        actions={
          <select
            className="sl"
            aria-label="Equipment"
            style={{ width: 200 }}
            value={equipment}
            onChange={(e) => setEquipment(e.target.value)}
          >
            <option value="">All equipment</option>
            {equipmentCodes.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        }
      >
        <div className="tw">
          <table className="tb">
            <thead>
              <tr>
                <th>Status</th>
                <th>Tag</th>
                <th>Description</th>
                <th>Equipment</th>
                <th>Rule or reason</th>
                <th>Since</th>
                <th>Models</th>
                <th>Scoring</th>
                <th className="r">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => {
                const ne = NE107_CODE[s.status];
                const id = assetId(s.asset_code);
                const why = s.exclusion
                  ? `Manual: ${s.exclusion.reason}, until ${formatDateTime(new Date(s.exclusion.expires_at)).slice(0, 6)}`
                  : reason(s.rule, s.effect);
                return (
                  <tr key={s.tag_id}>
                    <td>
                      <span className="ne">
                        {ne?.code && <span className={`diag ${ne.cls}`}>{ne.code}</span>}
                        {s.status}
                      </span>
                    </td>
                    <td className="mono">{shortTag(s.source_name)}</td>
                    <td>{plainDescription(s.source_name, desc(s.tag_id))}</td>
                    <td>
                      {id ? (
                        <IdChip to={`/assets/${id}?tab=sensors`}>{s.asset_code}</IdChip>
                      ) : (
                        s.asset_code
                      )}
                    </td>
                    <td className="w">{why}</td>
                    <td className="num sec">{formatDateTime(new Date(s.since))}</td>
                    <td className="mono sec">{s.models.join(", ") || "—"}</td>
                    <td className="sec">{EFFECT[s.effect] ?? s.effect}</td>
                    <td className="r">
                      {s.exclusion ? (
                        <button
                          className="btn btn-s btn-sm"
                          type="button"
                          disabled={end.isPending}
                          onClick={() => end.mutate(s.exclusion!.id)}
                        >
                          End
                        </button>
                      ) : (
                        <button
                          className="btn btn-s btn-sm"
                          type="button"
                          onClick={() => setExcluding({ id: s.tag_id, name: s.source_name })}
                        >
                          Exclude
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {health.isSuccess && rows.length === 0 && (
            <Empty>Every sensor in this scope is Good.</Empty>
          )}
          {health.isPending && <p className="sec s13">Loading…</p>}
        </div>
      </Panel>
      {excluding && (
        <ExcludeDialog
          tagId={excluding.id}
          name={excluding.name}
          onClose={() => setExcluding(null)}
        />
      )}
    </>
  );
}
