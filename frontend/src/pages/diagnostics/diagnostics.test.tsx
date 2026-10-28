import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { FailureMode, ModeMatch } from "../../api/diagnostics";
import type { Forecast } from "../../api/forecasts";
import { ADMIN, type Call, TREE, fakeApi, sessionRoutes } from "../../test/fakeApi";
import { renderApp } from "../../test/renderApp";
import { codeFrom, scoreText, signed, sparkPaths } from "./diagnosticsModel";
import {
  fitValue,
  forecastBrief,
  forecastChart,
  intervalText,
  medianText,
  urgencyText,
} from "./forecastModel";

vi.mock("../../components/charting", () => ({
  echarts: {
    init: vi.fn(() => ({
      setOption: vi.fn(),
      dispatchAction: vi.fn(),
      resize: vi.fn(),
      dispose: vi.fn(),
      on: vi.fn(),
      off: vi.fn(),
      isDisposed: () => false,
      getZr: () => ({ on: vi.fn(), off: vi.fn() }),
    })),
    connect: vi.fn(),
  },
  chartColors: () => ({}),
}));

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
  r["GET /forecasts"] = () => ({ status: 200, body: [FORECAST] });
  r["GET /models/1/latest"] = () => ({
    status: 200,
    body: {
      version_id: 3,
      version: 3,
      ts: "2026-10-22T08:00:00Z",
      sensors: [
        {
          tag_id: 2,
          source_name: "K101.ZI1015.PV",
          description: "",
          unit: "µm",
          required: true,
          actual: 410,
          predicted: 380,
          residual: 30,
          z: 2,
          contribution: 40,
          dq_status: "Good",
          dq_rule: null,
          used: true,
          sigma: 15,
          warning: 3,
          alert: 5,
        },
      ],
    },
  });
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

const FORECAST: Forecast = {
  id: 9,
  model_id: 1,
  version_id: 3,
  alert_id: 4,
  target: "di",
  tag_id: null,
  tag: null,
  threshold_kind: "alert",
  threshold: 30,
  direction: "up",
  window_days: 7,
  at: "2026-10-22T08:00:00Z",
  fit: { method: "linear", params: { a: 20, b: 2 }, r2: 0.91 },
  points: 3,
  valid: true,
  reason: null,
  median_h: 120,
  lower_h: 100,
  upper_h: 140,
  crossing_at: "2026-10-27T08:00:00Z",
  urgency: "High",
  summary: "Reaches 30 in 4.2 d–5.8 d (median 5.0 d) at the current trend",
  series: [
    { ts: "2026-10-21T08:00:00Z", value: 18 },
    { ts: "2026-10-21T20:00:00Z", value: 19 },
    { ts: "2026-10-22T08:00:00Z", value: 20 },
  ],
  created_at: "2026-10-22T08:05:00Z",
  created_by: 1,
};

describe("forecast rules", () => {
  it("words times, intervals and urgency as the wireframes do", () => {
    expect([0.5, 18, 47.6, 156, 300].map(medianText)).toEqual([
      "now",
      "18 h",
      "48 h",
      "6.5 d",
      "13 d",
    ]);
    expect(intervalText(100, 220)).toBe("4–10 d");
    expect(intervalText(6, 30)).toBe("6–30 h");
    expect(intervalText(1000, null)).toBe("more than 42 d");
    expect(urgencyText("High", 100, 220)).toBe("High · 4–10 d");
    expect(urgencyText("None", null, null)).toBe("None");
    expect(urgencyText(null, null, null)).toBe("—");
    expect(forecastBrief(FORECAST)).toBe("High · 4–6 d to DI alert limit 30");
    expect(forecastBrief({ ...FORECAST, valid: false, lower_h: null })).toBe(
      "None · no trend to threshold",
    );
  });

  it("draws the projection, a cone through the interval and the median crossing", () => {
    expect(fitValue({ method: "exponential", params: { c: 40, a: 5, b: 0.3 }, r2: 1 }, 0)).toBe(45);
    const { data, from, to } = forecastChart(FORECAST);
    const at = Date.parse(FORECAST.at);
    expect(from).toBe(Date.parse("2026-10-21T08:00:00Z"));
    expect(to).toBeGreaterThan(at + 120 * 3_600_000); // beyond the median crossing
    expect(data.predicted![0]).toEqual([at, 20]);
    expect(data.markers).toEqual([{ t: at + 120 * 3_600_000, name: "Median crossing" }]);
    expect(data.limits).toEqual({ alert: [30] });
    // at the median crossing the cone spans the threshold: fast above, slow below
    const [, lo, hi] = data.band!.find(([t]) => t >= at + 120 * 3_600_000)!;
    expect(lo).toBeLessThan(30);
    expect(hi).toBeGreaterThan(30);
    expect(forecastChart({ ...FORECAST, valid: false }).data.predicted).toBeUndefined();
  });
});

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

  it("shows the newest forecast; only analysts and model engineers run one", async () => {
    fakeApi(routes());
    renderApp("/assets/6/diagnostics");
    expect(
      await screen.findByRole("heading", {
        name: "Time-to-threshold forecast · DI → alert limit 30 %",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Urgency: HIGH")).toBeInTheDocument();
    expect(
      screen.getByText(
        /median 5\.0 d · 80 % interval 4–6 d · method: linear fit, 7-day window, R² 0\.91/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("figure", { name: "Forecast of DI" })).toBeInTheDocument();
    expect(screen.getByText("Analysts and model engineers run forecasts.")).toBeInTheDocument();
  });

  it("runs a forecast on a sensor with a custom threshold", async () => {
    const r = routes();
    r["GET /auth/me"] = () => ({
      status: 200,
      body: {
        user: { ...ADMIN, roles: [{ role: "analyst", scope_asset_id: null }] },
        csrf_token: "c",
      },
    });
    r["POST /forecasts"] = () => ({
      status: 201,
      body: {
        ...FORECAST,
        id: 10,
        target: "actual",
        tag_id: 2,
        tag: "K101.ZI1015.PV",
        threshold_kind: "custom",
        threshold: 500,
        valid: false,
        reason: "No trend to threshold: fit quality R² 0.12 is below 0.5",
        median_h: null,
        lower_h: null,
        upper_h: null,
        urgency: "None",
        summary: "No trend to threshold: fit quality R² 0.12 is below 0.5",
      },
    });
    const { calls } = fakeApi(r);
    const user = userEvent.setup();
    renderApp("/assets/6/diagnostics");
    const form = await screen.findByRole("form", { name: "Run a forecast" });
    await within(form).findByRole("option", { name: "K101.ZI1015.PV actual" });
    await user.selectOptions(within(form).getByLabelText("Target"), "actual:2");
    expect(within(form).queryByLabelText("Value")).toBeNull();
    await user.type(within(form).getByLabelText("Threshold"), "500");
    await user.selectOptions(within(form).getByLabelText("Fit window"), "3");
    await user.click(within(form).getByRole("button", { name: "Run forecast" }));
    await waitFor(() =>
      expect(calls.find((c: Call) => c.method === "POST")?.body).toEqual({
        model_id: 1,
        target: "actual",
        tag_id: 2,
        threshold_kind: "custom",
        threshold: 500,
        window_days: 3,
      }),
    );
    expect(await screen.findByText("Urgency: NONE")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Time-to-threshold forecast · K101.ZI1015.PV → 500 µm" }),
    ).toBeInTheDocument();
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
