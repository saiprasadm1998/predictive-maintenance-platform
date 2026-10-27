import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ModelDetail, Tag, TrainingData } from "../../api/types";
import { type Call, MODELS, fakeApi, sessionRoutes } from "../../test/fakeApi";
import { renderApp } from "../../test/renderApp";
import {
  alertRules,
  applyTemplate,
  draftFromModel,
  furthestStep,
  newDraft,
  stepProblems,
  toDefinition,
  trainingTrend,
} from "./builderModel";

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

const NOW = new Date("2026-10-21T10:00:00Z");

function tag(id: number, name: string, role: string | null): Tag {
  return {
    id,
    source: "gw",
    source_name: name,
    asset_id: 6,
    asset_code: "K-101",
    description: `${name} description`,
    unit: "°C",
    range_lo: 0,
    range_hi: 200,
    interval_s: 60,
    role,
  };
}

const TAGS = [tag(11, "K101.TI1.PV", "de_bearing_temp"), tag(12, "K101.TI2.PV", null)];

function version(id: number, n: number, status: string) {
  return {
    id,
    version: n,
    status,
    algorithm: "median",
    created_at: "2026-10-01T00:00:00Z",
    status_changed_at: null,
    sensors: [
      { tag_id: 11, source_name: "K101.TI1.PV", description: "", required: true },
      { tag_id: 12, source_name: "K101.TI2.PV", description: "", required: false },
    ],
    params: { cycle_s: 30, seed: 42 },
    error: null,
    training_periods: [{ start: "2026-05-01T00:00:00Z", end: "2026-08-01T00:00:00Z" }],
    validation_period: { start: "2026-08-01T00:00:00Z", end: "2026-09-01T00:00:00Z" },
    mode_filters: ["K101.TI2.PV > 10"],
    metrics: { training_cycles: 1000, training_retained: 900 },
  };
}

function detail(versions: ReturnType<typeof version>[]): ModelDetail {
  return {
    id: 9,
    asset_code: "K-101",
    name: "main",
    description: "whole machine",
    latest: versions[versions.length - 1]!,
    in_service: null,
    runtime: null,
    alerts_30d: 0,
    versions,
    alert_rules: [
      { id: 1, kind: "di", tag_id: null, warning: 12, alert: 20, state: "Normal" },
      { id: 2, kind: "sensor", tag_id: 11, warning: 3, alert: 6, state: "Normal" },
    ],
  };
}

describe("builder rules (UC-05)", () => {
  it("checks each step before Next", () => {
    const draft = newDraft("", NOW);
    expect(stepProblems(1, draft)).toEqual(["Choose the asset", "Select at least one sensor"]);
    const overlapping = {
      ...draft,
      training: [{ start: "2026-06-01T00:00", end: "2026-09-01T00:00" }],
      validation: { start: "2026-08-01T00:00", end: "2026-10-01T00:00" },
      cycleS: 5,
    };
    expect(stepProblems(2, overlapping)).toEqual([
      "Training period 1 overlaps the validation period",
      "The scoring cycle must be a whole number of seconds, at least 10",
    ]);
    expect(stepProblems(2, { ...draft, training: [{ start: "", end: "" }] })).toEqual([
      "Training period 1 needs a start and an end",
    ]);
    expect(stepProblems(2, draft)).toEqual([]);
    expect(stepProblems(5, { ...draft, di: { warning: 30, alert: 20, n: 4, m: 3 } })).toEqual([
      "DI limits need 0 < warning < alert",
      "Persistence needs whole numbers with 1 ≤ n ≤ m",
    ]);
  });

  it("starts a new version from the latest version and the model's limits", () => {
    const draft = draftFromModel(detail([version(3, 1, "Deployed")]), NOW);
    expect(draft.sensors).toEqual([
      { tag: "K101.TI1.PV", required: true },
      { tag: "K101.TI2.PV", required: false },
    ]);
    expect(draft.cycleS).toBe(30);
    expect(draft.modeFilters).toEqual(["K101.TI2.PV > 10"]);
    expect(draft.di).toEqual({ warning: 12, alert: 20, n: 3, m: 5 });
    expect(draft.sensorRules).toEqual([{ tag: "K101.TI1.PV", warning: 3, alert: 6 }]);
    const definition = toDefinition(draft, false);
    expect(definition.training_periods).toEqual([
      { start: "2026-05-01T00:00:00.000Z", end: "2026-08-01T00:00:00.000Z" },
    ]);
    expect(definition.params).toEqual({ cycle_s: 30 });
    expect(definition).not.toHaveProperty("alert_rules");
    expect(toDefinition(draft, true).alert_rules).toEqual(alertRules(draft));
  });

  it("applies the asset-type template: every role-mapped tag", () => {
    const draft = { ...newDraft("K-101", NOW), sensors: [{ tag: "K101.TI1.PV", required: true }] };
    expect(applyTemplate(draft, TAGS).sensors).toEqual([{ tag: "K101.TI1.PV", required: true }]);
  });

  it("knows how far a saved model can go", () => {
    const draft = draftFromModel(detail([version(3, 1, "Deployed")]), NOW);
    expect(furthestStep(undefined, newDraft("", NOW))).toBe(1);
    expect(furthestStep(detail([version(3, 1, "Training")]), draft)).toBe(4);
    expect(furthestStep(detail([version(3, 1, "Validated")]), draft)).toBe(6);
    expect(furthestStep(detail([version(3, 1, "Deployed")]), draft)).toBe(3);
  });

  it("draws the training data broken across gaps, shading mostly excluded buckets", () => {
    const data = {
      bucket_s: 3600,
      buckets: ["2026-06-01T00:00:00Z", "2026-06-01T01:00:00Z", "2026-06-01T05:00:00Z"],
      excluded: [0.9, 0.6, 0],
      values: { A: [1, 2, 3] },
    } as unknown as TrainingData;
    const trend = trainingTrend(data, "A");
    const h = (n: number) => Date.parse("2026-06-01T00:00:00Z") + n * 3_600_000;
    expect(trend.points).toEqual([
      [h(0), 1],
      [h(1), 2],
      [h(2), null],
      [h(5), 3],
    ]);
    expect(trend.excluded).toEqual([{ from: h(0), to: h(2), reason: "Excluded from training" }]);
    expect([trend.from, trend.to]).toEqual([h(0), h(6)]);
  });
});

const PREVIEW: TrainingData = {
  cycle_s: 60,
  cycles: 10_000,
  retained: 7_800,
  mode_removed: 2_000,
  quality_removed: 150,
  excluded_removed: 0,
  outlier_removed: 40,
  multivariate_removed: 10,
  clusters: [5_000, 2_500, 300],
  blocked: null,
  sensors: [
    {
      source_name: "K101.TI1.PV",
      description: "",
      required: true,
      usable_share: 0.99,
      flagged: false,
    },
  ],
  bucket_s: 3600,
  buckets: ["2026-06-01T00:00:00Z", "2026-06-01T01:00:00Z"],
  excluded: [0, 1],
  values: { "K101.TI1.PV": [80, 81] },
};

describe("SCR-06 model builder", () => {
  beforeEach(() => window.localStorage.clear());

  it("builds a new model to training: sensors, periods, cleansing, then the job", async () => {
    const routes = sessionRoutes(true);
    let saved: ModelDetail = detail([version(30, 1, "Draft")]);
    routes["GET /tags"] = () => ({ status: 200, body: { items: TAGS, next_cursor: null } });
    routes["GET /models"] = () => ({ status: 200, body: [] });
    routes["POST /models/training-data"] = () => ({ status: 200, body: PREVIEW });
    routes["POST /models"] = () => ({ status: 201, body: saved });
    routes["POST /models/9/versions"] = () => {
      saved = detail([version(30, 1, "Training")]);
      return { status: 202, body: { version: saved.latest, job_id: 5 } };
    };
    routes["GET /models/9"] = () => ({ status: 200, body: saved });
    routes["GET /jobs/5"] = () => ({
      status: 200,
      body: { id: 5, type: "model.train", status: "running", progress: 40 },
    });
    const { calls } = fakeApi(routes);
    const user = userEvent.setup();
    renderApp("/models/new/build/1?asset=K-101");

    const next = await screen.findByRole("button", { name: "Next →" });
    await user.click(next);
    expect(await screen.findByText("Select at least one sensor")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Apply asset-type template \(1 tags\)/ }));
    await user.click(screen.getByRole("checkbox", { name: "K101.TI1.PV required" }));
    await user.click(next);

    await screen.findByRole("group", { name: "Validation period (hold-out)" });
    await user.click(screen.getByRole("button", { name: "Next →" }));

    const summary = await screen.findByRole("table", { name: "Training data summary" });
    expect(within(summary).getByText(/78\.0 %/)).toBeInTheDocument();
    const rules = screen.getByRole("table", { name: "Cleansing rules applied" });
    expect(within(rules).getByText("20.0 % removed")).toBeInTheDocument();
    expect(within(rules).getByText("0.4 % removed")).toBeInTheDocument(); // outliers
    expect(within(summary).getByText(/3 operating clusters: 64 %, 32 %, 4 %/)).toBeInTheDocument();
    expect(within(summary).getByText(/Cluster 3 holds under 5 %/)).toBeInTheDocument();

    // A period left out by its times (the keyboard route to dragging on the trend).
    await user.click(screen.getByRole("button", { name: "Add an excluded period" }));
    expect(screen.getByRole("group", { name: "Excluded period 1" })).toBeInTheDocument();
    await waitFor(() =>
      expect(
        calls.some(
          (c: Call) =>
            c.path === "/models/training-data" &&
            (c.body as { exclusion_periods: unknown[] }).exclusion_periods.length === 1,
        ),
      ).toBe(true),
    );
    await user.click(screen.getByRole("button", { name: "Train model →" }));

    expect(await screen.findByText("Training: 40 %")).toBeInTheDocument();
    const save = calls.find((c: Call) => c.method === "POST" && c.path === "/models")!;
    expect(save.body).toMatchObject({
      asset: "K-101",
      name: "main",
      sensors: [{ tag: "K101.TI1.PV", required: true }],
      alert_rules: { di: { warning: 15, alert: 25 } }, // nothing in service: saved now
    });
    expect((save.body as { exclusion_periods: unknown[] }).exclusion_periods).toHaveLength(1);
    // The draft moved to the saved model, so it survives leaving the page.
    expect(window.localStorage.getItem("pmp.builder.1.9")).toContain('"jobId":5');
    expect(window.localStorage.getItem("pmp.builder.1.new")).toBeNull();
  });

  it("does not let a new model take an existing model's name", async () => {
    const routes = sessionRoutes(true);
    routes["GET /tags"] = () => ({ status: 200, body: { items: TAGS, next_cursor: null } });
    routes["GET /models"] = () => ({
      status: 200,
      body: MODELS.map((m) => ({ ...m, name: "main" })),
    });
    fakeApi(routes);
    renderApp("/models/new/build/1?asset=K-101");
    expect(
      await screen.findByText(/K-101 already has a model named “main”. Choose another name/),
    ).toBeInTheDocument();
  });

  it("deploys a validated version after confirming, saving the limits first when one is in service", async () => {
    const routes = sessionRoutes(true);
    const model = detail([version(3, 1, "Deployed"), version(4, 2, "Validated")]);
    routes["GET /models/9"] = () => ({ status: 200, body: model });
    routes["PUT /models/9/alert-rules"] = () => ({ status: 200, body: model });
    routes["POST /versions/4/deploy"] = () => ({ status: 200, body: model });
    const { calls } = fakeApi(routes);
    const user = userEvent.setup();
    renderApp("/models/9/build/6");

    await user.click(await screen.findByRole("button", { name: "Deploy version 2" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("version 1 is superseded");
    await user.click(within(dialog).getByRole("button", { name: "Deploy" }));
    await waitFor(() =>
      expect(calls.map((c) => `${c.method} ${c.path}`)).toContain("POST /versions/4/deploy"),
    );
    const order = calls.map((c) => `${c.method} ${c.path}`);
    expect(order.indexOf("PUT /models/9/alert-rules")).toBeLessThan(
      order.indexOf("POST /versions/4/deploy"),
    );
    expect(await screen.findByRole("heading", { level: 1, name: "v2" })).toBeInTheDocument();
  });
});
