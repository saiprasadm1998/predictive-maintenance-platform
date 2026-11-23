import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { errorMessages } from "../../api/client";
import { CRITICALITIES, type Role, createAsset, promoteUnmapped } from "../../api/registry";
import type { AssetNode } from "../../api/types";
import { useScope } from "../../app/scope";
import {
  Badge,
  KeyValues,
  Loading,
  PageHeader,
  Pill,
  Problems,
  type StepItem,
  Steps,
} from "../../components/ui";
import { defaultRange, roleKind, useTypes, useUnmapped } from "./setupModel";

const CRIT_LABEL: Record<string, string> = { A: "A, critical", B: "B, important", C: "C, other" };

/** ISA-5.1 first letters of a tag name, matched against role names. */
const MEASURED: [RegExp, RegExp][] = [
  [/^T/, /temp/i],
  [/^P/, /pressure/i],
  [/^F/, /flow/i],
  [/^I/, /current/i],
  [/^V/, /vibration/i],
  [/^Z/, /displacement|position/i],
  [/^S/, /speed/i],
];

function letters(source: string): string {
  const parts = source.split(".");
  return ((parts.length > 1 ? parts[1] : parts[0]) ?? "").replace(/[^A-Z]/g, "");
}

function matchByName(code: string, roles: Role[], names: string[]): Record<string, string> {
  const prefix = code.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
  const free = names.filter((n) =>
    n
      .toUpperCase()
      .replace(/[^A-Z0-9.]/g, "")
      .startsWith(prefix),
  );
  const out: Record<string, string> = {};
  for (const role of roles) {
    const hit = free.find((n) => {
      if (Object.values(out).includes(n)) return false;
      const l = letters(n);
      return MEASURED.some(([first, name]) => first.test(l) && name.test(role.name));
    });
    if (hit) out[role.code] = hit;
  }
  return out;
}

interface Form {
  unit: string; // unit asset code
  code: string;
  name: string;
  type: string;
  crit: string;
  description: string;
}

export function AddEquipmentPage() {
  const scope = useScope();
  const types = useTypes();
  const unmapped = useUnmapped();
  const client = useQueryClient();
  const [step, setStep] = useState(1);
  const [help, setHelp] = useState(false);
  const [form, setForm] = useState<Form>({
    unit: "",
    code: "",
    name: "",
    type: "",
    crit: "B",
    description: "",
  });
  const [map, setMap] = useState<Record<string, string>>({});
  const [ranges, setRanges] = useState<Record<string, [string, string]>>({});
  const [touched, setTouched] = useState(false);

  const units = useMemo(() => {
    const out: { node: AssetNode; path: string }[] = [];
    const walk = (nodes: readonly AssetNode[], trail: string[]) => {
      for (const n of nodes) {
        const here = n.level === "enterprise" ? trail : [...trail, n.name];
        if (n.level === "unit") out.push({ node: n, path: here.join(" / ") });
        walk(n.children, here);
      }
    };
    walk(scope.tree, []);
    return out;
  }, [scope.tree]);

  const type = (types.data ?? []).find((t) => t.code === form.type);
  const roles = type?.roles ?? [];
  const names = (unmapped.data ?? []).map((u) => u.source_name);
  const unit = units.find((u) => u.node.code === form.unit);
  const mapped = roles.filter((r) => map[r.code]).length;
  const codeTaken = scope.equipment.some(
    (n) => n.code.toLowerCase() === form.code.trim().toLowerCase(),
  );

  const save = useMutation({
    mutationFn: async () => {
      const asset = await createAsset({
        code: form.code.trim(),
        name: form.name.trim(),
        level: "equipment",
        parent: form.unit,
        criticality: form.crit,
        asset_type: form.type || null,
        description: form.description.trim(),
      });
      for (const role of roles) {
        const tag = map[role.code];
        if (!tag) continue;
        const source = (unmapped.data ?? []).find((u) => u.source_name === tag)?.source ?? "";
        const [lo, hi] = ranges[role.code] ?? defaultRange(role.unit);
        await promoteUnmapped({
          source,
          source_name: tag,
          asset: asset.code,
          unit: role.unit,
          range_lo: Number(lo),
          range_hi: Number(hi),
          interval_s: 60,
          description: role.name,
          role: role.code,
        });
      }
      return asset;
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ["assets"] });
      void client.invalidateQueries({ queryKey: ["tags"] });
    },
  });

  if (types.isPending || unmapped.isPending) return <Loading what="setup data" />;

  const valid: Record<number, boolean> = {
    1: !!form.unit,
    2: !!form.code.trim() && !!form.name.trim() && !!form.type && !codeTaken,
    3: true,
    4: true,
  };
  const labels = ["Location", "Details", "Tags and roles", "Review"];
  const steps: StepItem[] = labels.map((label, i) => ({
    label,
    state: i + 1 === step ? "on" : i + 1 < step ? "done" : "todo",
    onClick: i + 1 < step && !save.isSuccess ? () => setStep(i + 1) : undefined,
  }));
  const set = (k: keyof Form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [k]: e.target.value });
  const HELP: Record<number, [string, string]> = {
    1: [
      "Where is it?",
      "Pick the unit the equipment belongs to. Units come from the plant hierarchy.",
    ],
    2: [
      "What is it?",
      "The equipment tag is its plant identifier. The type decides which roles (sensor positions) it has and which model template applies.",
    ],
    3: [
      "Which tags measure it?",
      "Pick the live tag that measures each role. Tags arriving from the gateway but not yet registered are listed. Required roles must have a tag before a model can be trained.",
    ],
    4: [
      "Check and add",
      "The equipment is added to the plant tree and its tags are registered with their roles.",
    ],
  };
  const next = () => {
    setTouched(true);
    if (!valid[step]) return;
    setTouched(false);
    setStep(step + 1);
  };

  return (
    <>
      <PageHeader
        crumbs={[
          { label: "Setup overview", to: "/setup" },
          { label: "Equipment register", to: "/setup/equipment" },
          { label: "Add equipment" },
        ]}
        title="Add equipment"
        sub={`Step ${step} of 4`}
        actions={
          <>
            <span style={{ position: "relative" }}>
              <button
                className="qi"
                type="button"
                aria-expanded={help}
                aria-label="Help for this step"
                onClick={() => setHelp(!help)}
              >
                ?
              </button>
              {help && (
                <div className="tt" role="dialog" aria-label="Help for this step">
                  <b>{HELP[step]?.[0]}</b>
                  <span>{HELP[step]?.[1]}</span>
                </div>
              )}
            </span>
            <Link className="btn btn-g" to="/setup/equipment">
              Cancel
            </Link>
          </>
        }
      />
      <Steps steps={steps} label="Steps" />
      <section className="pnl fill" aria-labelledby="ae-h" style={{ minHeight: 480 }}>
        {step === 1 && (
          <>
            <div className="pnlh">
              <span className="pt" id="ae-h">
                Where is it?
              </span>
            </div>
            <div className="fg">
              <div className="fld span2">
                <label htmlFor="a-unit">Unit</label>
                <select id="a-unit" className="sl" value={form.unit} onChange={set("unit")}>
                  <option value="">Choose a unit</option>
                  {units.map((u) => (
                    <option key={u.node.code} value={u.node.code}>
                      {u.path}
                    </option>
                  ))}
                </select>
                {touched && !valid[1] && <span className="err">Choose the unit.</span>}
                {units.length === 0 && (
                  <span className="sec s13">
                    No units yet. <Link to="/setup/hierarchy">Add one in the plant hierarchy.</Link>
                  </span>
                )}
              </div>
            </div>
          </>
        )}
        {step === 2 && (
          <>
            <div className="pnlh">
              <span className="pt" id="ae-h">
                What is it?
              </span>
            </div>
            <div className="fg">
              <div className="fld">
                <label htmlFor="b1">Equipment tag</label>
                <input
                  id="b1"
                  className="in mono"
                  value={form.code}
                  onChange={set("code")}
                  placeholder="P-104C"
                />
                {touched && !form.code.trim() && (
                  <span className="err">Enter the equipment tag.</span>
                )}
                {codeTaken && <span className="err">{form.code} is already in the register.</span>}
              </div>
              <div className="fld">
                <label htmlFor="b2">Name</label>
                <input
                  id="b2"
                  className="in"
                  value={form.name}
                  onChange={set("name")}
                  placeholder="BFW pump C"
                />
                {touched && !form.name.trim() && <span className="err">Enter a name.</span>}
              </div>
              <div className="fld">
                <label htmlFor="b3">Equipment type</label>
                <select
                  id="b3"
                  className="sl"
                  value={form.type}
                  onChange={(e) => {
                    setForm({ ...form, type: e.target.value });
                    setMap({});
                  }}
                >
                  <option value="">Choose a type</option>
                  {(types.data ?? []).map((t) => (
                    <option key={t.code} value={t.code}>
                      {t.name}
                    </option>
                  ))}
                </select>
                {touched && !form.type && <span className="err">Choose the equipment type.</span>}
              </div>
              <div className="fld">
                <label htmlFor="b4">Criticality</label>
                <select id="b4" className="sl" value={form.crit} onChange={set("crit")}>
                  {CRITICALITIES.map((c) => (
                    <option key={c} value={c}>
                      {CRIT_LABEL[c]}
                    </option>
                  ))}
                </select>
              </div>
              <div className="fld span2">
                <label htmlFor="b5">Description (optional)</label>
                <input
                  id="b5"
                  className="in"
                  value={form.description}
                  onChange={set("description")}
                  placeholder="Make, model, duty"
                />
              </div>
            </div>
          </>
        )}
        {step === 3 && (
          <>
            <div className="pnlh">
              <span className="pt" id="ae-h">
                Which tags measure it?
              </span>
              <button
                className="btn btn-s"
                type="button"
                onClick={() => setMap({ ...map, ...matchByName(form.code, roles, names) })}
              >
                Match tags by name
              </button>
            </div>
            <div className="tw">
              <table className="tb">
                <thead>
                  <tr>
                    <th>Role</th>
                    <th>Kind</th>
                    <th>Tag</th>
                    <th>Range</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {roles.map((r) => {
                    const value = map[r.code] ?? "";
                    const taken = new Set(
                      Object.entries(map)
                        .filter(([k]) => k !== r.code)
                        .map(([, v]) => v),
                    );
                    const d = defaultRange(r.unit);
                    const range: [string, string] = ranges[r.code] ?? [String(d[0]), String(d[1])];
                    return (
                      <tr key={r.code}>
                        <td>
                          <b>{r.name}</b> <span className="sec s13">{r.unit}</span>
                        </td>
                        <td>
                          <Badge>{roleKind(r.code)}</Badge>
                        </td>
                        <td style={{ width: 280 }}>
                          <select
                            className="sl mono"
                            value={value}
                            aria-label={`Tag for ${r.name}`}
                            onChange={(e) => setMap({ ...map, [r.code]: e.target.value })}
                          >
                            <option value="">Not mapped</option>
                            {names
                              .filter((n) => !taken.has(n))
                              .map((n) => (
                                <option key={n} value={n}>
                                  {n}
                                </option>
                              ))}
                          </select>
                        </td>
                        <td style={{ width: 200 }}>
                          <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
                            <input
                              className="in num"
                              style={{ width: 80 }}
                              aria-label={`Low range for ${r.name}`}
                              value={range[0]}
                              disabled={!value}
                              onChange={(e) =>
                                setRanges({ ...ranges, [r.code]: [e.target.value, range[1]] })
                              }
                            />
                            <span className="sec">to</span>
                            <input
                              className="in num"
                              style={{ width: 80 }}
                              aria-label={`High range for ${r.name}`}
                              value={range[1]}
                              disabled={!value}
                              onChange={(e) =>
                                setRanges({ ...ranges, [r.code]: [range[0], e.target.value] })
                              }
                            />
                          </span>
                        </td>
                        <td>
                          <Pill tone={value ? "neutral" : "unknown"}>
                            {value ? "Mapped" : "Not mapped"}
                          </Pill>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="sec s13" style={{ marginTop: 12 }}>
              {mapped} of {roles.length} roles mapped.{" "}
              {names.length === 0
                ? "No unregistered tags are arriving. Tags can also be registered later in Tags and mapping."
                : "Roles can also be mapped later in Tags and mapping."}
            </p>
          </>
        )}
        {step === 4 && !save.isSuccess && (
          <>
            <div className="pnlh">
              <span className="pt" id="ae-h">
                Check and add
              </span>
            </div>
            <KeyValues
              rows={[
                ["Location", unit?.path ?? form.unit],
                ["Equipment", `${form.code} ${form.name}`],
                ["Type", type?.name ?? "Not set"],
                ["Criticality", CRIT_LABEL[form.crit]],
                ["Tags", `${mapped} of ${roles.length} roles mapped`],
              ]}
            />
            <Problems messages={save.isError ? errorMessages(save.error) : []} />
          </>
        )}
        {step === 4 && save.isSuccess && (
          <div
            style={{ display: "flex", flexDirection: "column", gap: 12, alignItems: "flex-start" }}
          >
            <Pill tone="success">Added</Pill>
            <h2>
              {form.code} {form.name} is in the plant tree
            </h2>
            <p className="sec">
              Next, upload its history and train a model so it gets a health score.
            </p>
            <div className="acts">
              <Link className="btn btn-p" to={`/setup/history/upload?asset=${save.data.id}`}>
                Upload history
              </Link>
              <Link
                className="btn btn-s"
                to={`/models/new/build/1?asset=${encodeURIComponent(save.data.code)}`}
              >
                Train a model
              </Link>
              <button
                className="btn btn-g"
                type="button"
                onClick={() => {
                  save.reset();
                  setForm({ ...form, code: "", name: "", description: "" });
                  setMap({});
                  setStep(1);
                }}
              >
                Add another
              </button>
            </div>
          </div>
        )}
        {!(step === 4 && save.isSuccess) && (
          <div className="wfoot">
            <button
              className="btn btn-s"
              type="button"
              disabled={step === 1}
              onClick={() => setStep(step - 1)}
            >
              Back
            </button>
            {step < 4 ? (
              <button className="btn btn-p" type="button" onClick={next}>
                Continue
              </button>
            ) : (
              <button
                className="btn btn-p"
                type="button"
                disabled={save.isPending}
                onClick={() => save.mutate()}
              >
                {save.isPending ? "Adding…" : "Add equipment"}
              </button>
            )}
          </div>
        )}
      </section>
    </>
  );
}
