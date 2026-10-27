import { type Route, expect, test } from "@playwright/test";

import { mockApi } from "./mockApi";

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

/**
 * The model-building part of the web role, as a small state machine: a saved definition
 * becomes a Draft, training runs as a job that reports progress, ends Validated, and the
 * version can then be deployed. The rest of the API comes from mockApi.
 */
async function mockBuilder(page: Parameters<typeof mockApi>[0], asset: string) {
  const tags = ["TI1", "PI2", "FI3"].map((name, i) => ({
    id: 900 + i,
    source: "gw",
    source_name: `${asset}.${name}.PV`,
    asset_id: 1,
    asset_code: asset,
    description: `${name} sensor`,
    unit: "°C",
    range_lo: 0,
    range_hi: 200,
    interval_s: 60,
    role: i < 2 ? `role_${i}` : null,
  }));
  const day = 86_400_000;
  const start = Date.now() - 120 * day;
  let status = "Draft";
  let polls = 0;
  const calls: string[] = [];
  const bodies: { exclusion_periods?: unknown[] }[] = []; // training-data previews
  const model = () => {
    const v = {
      id: 77,
      version: 1,
      status,
      algorithm: "median",
      created_at: new Date().toISOString(),
      status_changed_at: new Date().toISOString(),
      sensors: tags.slice(0, 2).map((t, i) => ({
        tag_id: t.id,
        source_name: t.source_name,
        description: t.description,
        required: i === 0,
      })),
      params: { cycle_s: 60, seed: 42 },
      error: null,
      training_periods: [],
      validation_period: null,
      mode_filters: [],
      metrics:
        status === "Validated" || status === "Deployed"
          ? {
              training_cycles: 129_600,
              training_retained: 120_000,
              validation_cycles: 43_200,
              validation: {
                cycles: 43_000,
                di_percentiles: { P50: 6.2, P95: 11.5, P99: 15.0, "P99.9": 19.0 },
                outside_envelope: 0.003,
                proposed: { di_warning: 18, di_alert: 28.5, sensor_warning: 3, sensor_alert: 5 },
                alerts: 1,
                alerts_per_week: 0.23,
                warning: null,
                sensors: {},
              },
            }
          : null,
    };
    return {
      id: 500,
      asset_code: asset,
      name: "bearings",
      description: "",
      latest: v,
      in_service: status === "Deployed" ? v : null,
      runtime: null,
      alerts_30d: 0,
      versions: [v],
      alert_rules: [{ id: 1, kind: "di", tag_id: null, warning: 15, alert: 25, state: "Normal" }],
    };
  };
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/v1", "");
    const method = route.request().method();
    if (method !== "GET") calls.push(`${method} ${path}`);
    if (path === "/tags") return json(route, { items: tags, next_cursor: null });
    if (method === "POST" && path === "/models/training-data") {
      const body = route.request().postDataJSON() as { exclusion_periods?: unknown[] };
      const left = (body.exclusion_periods ?? []).length * 1_440; // a day per period, say
      bodies.push(body);
      return json(route, {
        cycle_s: 60,
        cycles: 129_600,
        retained: 119_700 - left,
        mode_removed: 9_000,
        quality_removed: 600,
        excluded_removed: left,
        outlier_removed: 180,
        multivariate_removed: 120,
        clusters: [70_000 - left, 49_700],
        blocked: null,
        sensors: tags.slice(0, 2).map((t) => ({
          source_name: t.source_name,
          description: t.description,
          required: false,
          usable_share: 0.99,
          flagged: false,
        })),
        bucket_s: 86_400,
        buckets: Array.from({ length: 90 }, (_, i) => new Date(start + i * day).toISOString()),
        excluded: Array.from({ length: 90 }, (_, i) => (i > 40 && i < 45 ? 1 : 0)),
        values: Object.fromEntries(
          tags
            .slice(0, 2)
            .map((t) => [
              t.source_name,
              Array.from({ length: 90 }, (_, i) => 80 + Math.sin(i / 5)),
            ]),
        ),
      });
    }
    if (method === "POST" && path === "/models") return json(route, model(), 201);
    if (method === "POST" && path === "/models/500/versions") {
      status = "Training";
      return json(route, { version: model().latest, job_id: 31 }, 202);
    }
    if (path === "/jobs/31") {
      polls += 1;
      const done = polls > 1;
      if (done) status = "Validated";
      return json(route, {
        id: 31,
        type: "model.train",
        status: done ? "succeeded" : "running",
        progress: done ? 100 : 60,
        attempts: 1,
        result: null,
        error: null,
        created_at: new Date().toISOString(),
        finished_at: null,
      });
    }
    if (path === "/models/500") return json(route, model());
    if (method === "PUT" && path === "/models/500/alert-rules") return json(route, model());
    if (method === "POST" && path === "/versions/77/deploy") {
      status = "Deployed";
      return json(route, model());
    }
    if (path === "/models/500/scores") {
      const now = new Date().toISOString();
      return json(route, {
        start: now,
        end: now,
        raw: true,
        bucket_s: null,
        source: "score",
        ts: [],
        min: { di: [], health: [] },
        max: { di: [], health: [] },
      });
    }
    if (path.startsWith("/models/500/")) return json(route, []);
    return route.fallback();
  });
  return { calls, bodies };
}

test.describe("SCR-06 model builder", () => {
  test("journey: define, train, validate and deploy a model entirely in the UI (AC-02 rehearsal)", async ({
    page,
  }) => {
    await mockApi(page, { sites: 1, units: 1, perUnit: 2 });
    const { calls, bodies } = await mockBuilder(page, "S0U0E1");
    await page.goto("/models");
    await page.getByRole("link", { name: "New model" }).click();

    // 1 Asset and sensors
    await page.getByRole("combobox", { name: "Asset", exact: true }).selectOption("S0U0E1");
    await page.getByLabel("Model name").fill("bearings");
    await page.getByRole("button", { name: /Apply asset-type template \(2 tags\)/ }).click();
    await page.getByRole("checkbox", { name: "S0U0E1.TI1.PV required" }).check();
    await page.getByRole("button", { name: "Next →" }).click();

    // 2 Periods: the defaults (the last 120 to 30 days, then the last 30) are valid
    await expect(page.getByRole("group", { name: "Training period 1" })).toBeVisible();
    await page.getByRole("button", { name: "Next →" }).click();

    // 3 Cleanse: the effect of each rule, then training starts
    const summary = page.getByRole("table", { name: "Training data summary" });
    await expect(summary).toContainText("92.4 %"); // after outliers and multivariate
    const rules = page.getByRole("table", { name: "Cleansing rules applied" });
    await expect(rules).toContainText("6.9 % removed");
    await expect(summary).toContainText("2 operating clusters");

    // Drag across the trend to leave a period out of training (UC-05 step 5).
    const trend = page.getByRole("slider", { name: /Training data · .* drag across the trend/ });
    const box = (await trend.boundingBox())!;
    await page.mouse.move(box.x + box.width * 0.4, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.5, box.y + box.height / 2, { steps: 5 });
    await page.mouse.up();
    await expect(page.getByRole("group", { name: "Excluded period 1" })).toBeVisible();
    await expect(rules.getByRole("row", { name: /Excluded on the trend/ })).toContainText(
      "1 period",
    );
    await expect(rules.getByRole("row", { name: /Excluded on the trend/ })).toContainText(
      "1.1 % removed",
    );
    expect(bodies.at(-1)?.exclusion_periods).toHaveLength(1);
    await page.getByRole("button", { name: "Train model →" }).click();

    // 4 Train and validate: progress, then the result
    await expect(page.getByText("Training: 60 %")).toBeVisible();
    await expect(page.getByRole("table", { name: "Training and validation" })).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByRole("table", { name: "Validation report" })).toContainText(
      "DI warning 18 %, alert 28.5 %",
    );
    await page.getByRole("button", { name: "Next →" }).click();

    // 5 Alert limits: tighten the DI alert limit and add a sensor rule
    await page.getByRole("spinbutton", { name: "DI alert (%)" }).fill("22");
    await page.getByRole("checkbox", { name: "|z| rule on S0U0E1.TI1.PV" }).check();
    await page.getByRole("button", { name: "Next →" }).click();

    // 6 Deploy, confirmed
    await expect(page.getByRole("table", { name: /S0U0E1 \/ bearings version 1/ })).toContainText(
      "warning 18 %, alert 22 %", // the proposed warning, the alert tightened by hand
    );
    await page.getByRole("button", { name: "Deploy version 1" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Deploy" }).click();
    await expect(page).toHaveURL(/\/models\/500\/versions\/1/);
    await expect(page.getByRole("heading", { level: 1, name: "v1" })).toBeVisible();

    expect(calls).toEqual([
      "POST /models/training-data",
      "POST /models/training-data", // again with the excluded period
      "POST /models",
      "POST /models/500/versions",
      "PUT /models/500/alert-rules",
      "POST /versions/77/deploy",
    ]);
  });
});
