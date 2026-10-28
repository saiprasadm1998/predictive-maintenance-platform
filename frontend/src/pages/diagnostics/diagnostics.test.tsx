import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { FailureMode, ModeMatch } from "../../api/diagnostics";
import { ADMIN, type Call, TREE, fakeApi, sessionRoutes } from "../../test/fakeApi";
import { renderApp } from "../../test/renderApp";
import { codeFrom, scoreText, signed, sparkPaths } from "./diagnosticsModel";

const K101 = (TREE[0]!.children as { children: object[] }[])[0]!.children[0]!;
const TYPE = {
  id: 1,
  code: "centrifugal_compressor",
  name: "Centrifugal compressor",
  description: "",
  roles: [
    { code: "thrust_pad_temp", name: "Thrust pad temperature", unit: "°C" },
    { code: "axial_displacement", name: "Axial displacement", unit: "µm" },
    { code: "de_bearing_temp", name: "Drive-end bearing temperature", unit: "°C" },
    { code: "lube_oil_supply_temp", name: "Lube oil supply temperature", unit: "°C" },
  ],
};

function mode(code: string, name: string, extra: Partial<FailureMode> = {}): FailureMode {
  return {
    id: code.length,
    asset_type: TYPE.code,
    code,
    version: 1,
    name,
    iso_code: "BRD",
    description: "",
    symptoms: [
      { role: "thrust_pad_temp", direction: "up", weight: 3 },
      { role: "axial_displacement", direction: "up", weight: 3 },
      { role: "de_bearing_temp", direction: "up", weight: 2 },
      { role: "lube_oil_supply_temp", direction: "any", weight: 1 },
    ],
    tasks: ["Check thrust bearing pad temperatures against vendor limits"],
    comment: "",
    updated_at: "2026-10-20T00:00:00Z",
    updated_by: 1,
    retired_at: null,
    ...extra,
  };
}

const THRUST: ModeMatch = {
  mode: mode("thrust_bearing_degradation", "Thrust bearing degradation"),
  score: 78,
  insufficient_evidence: false,
  evaluated_weight: 6,
  total_weight: 9,
  symptoms: [
    {
      role: "thrust_pad_temp",
      direction: "up",
      weight: 3,
      tag_id: 1,
      source_name: "K101.TI1016.PV",
      z: 4,
      z_ref: 3,
      g: null,
      result: "not evaluated",
    },
    {
      role: "axial_displacement",
      direction: "up",
      weight: 3,
      tag_id: 2,
      source_name: "K101.ZI1015.PV",
      z: 2,
      z_ref: 3,
      g: 0.667,
      result: "match",
    },
    {
      role: "de_bearing_temp",
      direction: "up",
      weight: 2,
      tag_id: 3,
      source_name: "K101.TI1012.PV",
      z: 3.1,
      z_ref: 3,
      g: 1,
      result: "match",
    },
    {
      role: "lube_oil_supply_temp",
      direction: "any",
      weight: 1,
      tag_id: 4,
      source_name: "K101.TI1030.PV",
      z: -1.4,
      z_ref: 3,
      g: 0.467,
      result: "partial",
    },
  ],
  trend: [
    { ts: "2026-10-20T00:00:00Z", score: 40 },
    { ts: "2026-10-20T01:00:00Z", score: null },
    { ts: "2026-10-20T02:00:00Z", score: 60 },
    { ts: "2026-10-20T03:00:00Z", score: 78 },
  ],
};
const SEAL: ModeMatch = {
  ...THRUST,
  mode: mode("seal_gas_system_fault", "Seal gas system fault", { iso_code: "ELU", tasks: [] }),
  score: 90,
  insufficient_evidence: true,
  evaluated_weight: 1,
  total_weight: 4,
};

describe("diagnostics rules", () => {
  it("shows scores, signs and sparklines as the wireframe does", () => {
    expect(scoreText(THRUST)).toBe("78 %");
    expect(scoreText(SEAL)).toBe("insufficient evidence");
    expect(signed(3.14)).toBe("+3.1");
    expect(signed(-2)).toBe("−2.0");
    expect(sparkPaths(THRUST.trend)).toEqual(["53.3,7.2 80.0,4.0"]); // the gap splits the line
    expect(codeFrom("Thrust bearing (wear)")).toBe("thrust_bearing_wear");
  });
});

function routes() {
  const r = sessionRoutes(true);
  r["GET /assets/6"] = () => ({
    status: 200,
    body: {
      id: 6,
      code: "K-101",
      name: "Syngas compressor K-101",
      level: "equipment",
      parent_id: 5,
      criticality: "A",
      asset_type: TYPE.code,
      description: "",
      ancestors: [{ id: 5, code: "SA-AMM", name: "Ammonia unit" }],
      health: K101,
    },
  });
  r["GET /asset-types"] = () => ({ status: 200, body: [TYPE] });
  r["GET /models/1/diagnostics"] = () => ({
    status: 200,
    body: {
      model_id: 1,
      asset_code: "K-101",
      asset_type: TYPE.code,
      version_id: 3,
      at: "2026-10-22T08:00:00Z",
      note: "",
      modes: [THRUST, SEAL],
    },
  });
  return r;
}

describe("SCR-04 diagnostics", () => {
  it("ranks the modes and shows the chosen mode's symptoms and tasks", async () => {
    fakeApi(routes());
    const user = userEvent.setup();
    renderApp("/assets/6/diagnostics");

    const list = await screen.findByRole("list", { name: "Failure modes ranked by match" });
    expect(
      within(list)
        .getAllByRole("button")
        .map((b) => b.getAttribute("aria-label")),
    ).toEqual(["Thrust bearing degradation: 78 %", "Seal gas system fault: insufficient evidence"]);
    expect(screen.getByText(/relative ranking, not a calibrated probability/)).toBeInTheDocument();
    const symptoms = screen.getByRole("table");
    const pad = within(symptoms).getByText("Thrust pad temperature").closest("tr")!;
    expect(pad).toHaveTextContent("excluded");
    expect(pad).toHaveTextContent("not evaluated");
    const de = within(symptoms).getByText("Drive-end bearing temperature").closest("tr")!;
    expect(
      within(de)
        .getAllByRole("cell")
        .map((c) => c.textContent),
    ).toEqual(["Drive-end bearing temperature", "↑", "+3.1", "2", "✔ match"]);
    expect(
      screen.getByText("Check thrust bearing pad temperatures against vendor limits"),
    ).toBeInTheDocument();

    await user.click(within(list).getByRole("button", { name: /Seal gas system fault/ }));
    expect(
      await screen.findByText(/Insufficient evidence: only 1 of 4 weight/),
    ).toBeInTheDocument();
    expect(screen.getByText("No tasks are linked to this failure mode.")).toBeInTheDocument();
  });
});

describe("SCR-12 failure-mode library", () => {
  function libraryRoutes(roles: string[]) {
    const r = sessionRoutes(true);
    r["GET /auth/me"] = () => ({
      status: 200,
      body: {
        user: { ...ADMIN, roles: roles.map((role) => ({ role, scope_asset_id: null })) },
        csrf_token: "c",
      },
    });
    r["GET /asset-types"] = () => ({ status: 200, body: [TYPE] });
    r["GET /library"] = () => ({ status: 200, body: [THRUST.mode] });
    r["PUT /library"] = (call) => ({
      status: 200,
      body: { ...THRUST.mode, ...(call.body as object), version: 1 },
    });
    r["POST /library/26/retire"] = () => ({ status: 200, body: THRUST.mode });
    return r;
  }

  it("lets a model engineer add a mode with symptoms and tasks", async () => {
    const { calls } = fakeApi(libraryRoutes(["model_engineer"]));
    const user = userEvent.setup();
    renderApp("/library");

    expect(
      await screen.findByRole("heading", { name: /Thrust bearing degradation/ }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add a failure mode" }));
    const form = screen.getByRole("region", { name: /New failure mode/ });
    await user.type(within(form).getByLabelText("Name"), "Lube oil cooler fouling");
    await user.type(within(form).getByLabelText("ISO 14224 code"), "OHE");
    await user.selectOptions(within(form).getByLabelText("Role 1"), "lube_oil_supply_temp");
    await user.click(within(form).getByRole("button", { name: "Add a symptom" }));
    await user.clear(within(form).getByLabelText("Weight of symptom 1"));
    await user.type(within(form).getByLabelText("Weight of symptom 1"), "3");
    await user.type(
      within(form).getByLabelText(/Recommended tasks/),
      "Clean the cooler{enter}Check the valve",
    );
    await user.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c: Call) => c.method === "PUT")?.body).toEqual({
        asset_type: "centrifugal_compressor",
        code: "lube_oil_cooler_fouling",
        name: "Lube oil cooler fouling",
        iso_code: "OHE",
        description: "",
        symptoms: [
          { role: "lube_oil_supply_temp", direction: "up", weight: 3 },
          { role: "thrust_pad_temp", direction: "up", weight: 1 },
        ],
        tasks: ["Clean the cooler", "Check the valve"],
        comment: "",
      }),
    );
  });

  it("shows the library read-only to others", async () => {
    fakeApi(libraryRoutes(["analyst"]));
    renderApp("/library");
    expect(
      await screen.findByRole("heading", { name: /Thrust bearing degradation/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a failure mode" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Retire" })).toBeNull();
  });
});
