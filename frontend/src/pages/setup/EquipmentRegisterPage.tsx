import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { Badge, HowTo, ICONS, Kpis, Loading, PageHeader, Panel, Pill } from "../../components/ui";
import { locations } from "../../app/places";
import { READINESS, type Readiness, useEquipmentSetup } from "./setupModel";

export function EquipmentRegisterPage() {
  const { rows, loading, scope } = useEquipmentSetup();
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [only, setOnly] = useState<Readiness | null>(null);
  const where = useMemo(() => locations(scope.tree), [scope.tree]);
  if (loading) return <Loading what="the equipment register" />;

  const typeNames = [...new Set(rows.map((r) => r.type?.name).filter(Boolean))] as string[];
  const count = (k: Readiness) => rows.filter((r) => r.readiness === k).length;
  const toggle = (k: Readiness) => setOnly(only === k ? null : k);
  const needle = q.trim().toLowerCase();
  const shown = rows.filter(
    (r) =>
      (!only || r.readiness === only) &&
      (!type || r.type?.name === type) &&
      (!needle ||
        r.node.code.toLowerCase().includes(needle) ||
        r.node.name.toLowerCase().includes(needle)),
  );

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Setup overview", to: "/setup" }, { label: "Equipment register" }]}
        title="Equipment register"
        sub={`${rows.length} equipment, ${typeNames.length} types`}
        actions={
          <>
            <HowTo title="Readiness">
              Ready and scoring: a deployed model is scoring every minute. Missing required roles: a
              role the model template needs has no tag. Model waiting for review: a trained version
              has not been deployed. Cannot score: the deployed model is not running.
            </HowTo>
            <Link className="btn btn-s" to="/setup/hierarchy?import=1">
              Import workbook
            </Link>
            <Link className="btn btn-p" to="/setup/equipment/new">
              Add equipment
            </Link>
          </>
        }
      />
      <Kpis
        cols={4}
        label="Readiness"
        items={[
          {
            label: "Ready and scoring",
            value: count("ready"),
            tone: "success",
            icon: ICONS.check,
            onClick: () => toggle("ready"),
            pressed: only === "ready",
          },
          {
            label: "Missing required roles",
            value: count("roles"),
            tone: "warning",
            icon: ICONS.tag,
            onClick: () => toggle("roles"),
            pressed: only === "roles",
          },
          {
            label: "Model waiting for review",
            value: count("review"),
            tone: "warning",
            icon: ICONS.trend,
            onClick: () => toggle("review"),
            pressed: only === "review",
          },
          {
            label: "Cannot score",
            value: count("cannot"),
            tone: "unknown",
            icon: ICONS.unknown,
            onClick: () => toggle("cannot"),
            pressed: only === "cannot",
          },
        ]}
      />
      <Panel className="fill">
        <div className="filters" style={{ marginBottom: 12 }}>
          <div className="fld" style={{ width: 240 }}>
            <label htmlFor="er-q">Find</label>
            <input
              id="er-q"
              className="in"
              placeholder="Tag or name"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <div className="fld" style={{ width: 220 }}>
            <label htmlFor="er-t">Type</label>
            <select id="er-t" className="sl" value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">All types</option>
              {typeNames.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="tw">
          <table className="tb">
            <thead>
              <tr>
                <th>Equipment</th>
                <th>Type</th>
                <th>Criticality</th>
                <th>Location</th>
                <th>Roles mapped</th>
                <th>History</th>
                <th>Model</th>
                <th>Readiness</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.node.id}>
                  <td>
                    <Link
                      to={`/assets/${r.node.id}`}
                      style={{ color: "inherit", textDecoration: "none" }}
                    >
                      <b className="mono">{r.node.code}</b>{" "}
                      <span className="sec s13">{r.node.name}</span>
                    </Link>
                  </td>
                  <td>{r.type?.name ?? <span className="sec">Not set</span>}</td>
                  <td>{r.node.criticality ? <Badge>{r.node.criticality}</Badge> : "n/a"}</td>
                  <td className="sec">{where.get(r.node.id)}</td>
                  <td className="num">
                    <Link
                      to={`/setup/tags?asset=${r.node.id}`}
                      style={{ color: "inherit", textDecoration: "none" }}
                    >
                      {r.rolesMapped} of {r.rolesTotal}
                    </Link>
                  </td>
                  <td className="num">
                    {r.historyDays ? `${r.historyDays} days` : <span className="sec">None</span>}
                  </td>
                  <td className="mono sec">
                    {r.model ? (
                      <Link
                        to={`/models/${r.model.id}/versions/${r.model.latest.version}`}
                        style={{ textDecoration: "none" }}
                      >
                        v{r.model.latest.version} {r.model.latest.status.toLowerCase()}
                      </Link>
                    ) : (
                      "none"
                    )}
                  </td>
                  <td>
                    <Pill tone={READINESS[r.readiness].tone}>{READINESS[r.readiness].label}</Pill>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {shown.length === 0 && (
            <p className="sec s13" style={{ padding: 16 }}>
              No equipment matches.
            </p>
          )}
        </div>
      </Panel>
    </>
  );
}
