import { type Route, expect, test } from "@playwright/test";

import { mockApi } from "./mockApi";

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

const ASSETS_CSV = "code,name,level,parent,criticality,asset_type,description\n";

test.describe("SCR-13 registry and import", () => {
  test("journey: validate registry files, read the report, then import them", async ({ page }) => {
    await mockApi(page, { sites: 1, units: 1, perUnit: 2 });
    const sent: string[] = [];
    await page.route("**/api/v1/tags/import**", (route) => {
      const url = new URL(route.request().url());
      const dryRun = url.searchParams.get("dry_run") === "true";
      const body = route.request().postData() ?? "";
      sent.push(
        `${dryRun ? "validate" : "import"}:${body.includes("tags.csv") ? "tags" : "assets"}`,
      );
      if (body.includes("tags.csv"))
        return json(route, {
          committed: false,
          dry_run: true,
          counts: {},
          problems: [
            { sheet: "tags", line: 3, column: "asset", message: "asset 'X-9' does not exist" },
          ],
        });
      return json(route, {
        committed: !dryRun,
        dry_run: dryRun,
        counts: { assets: { created: 2, updated: 1, unchanged: 0 } },
        problems: [],
      });
    });

    await page.goto("/admin");
    await page.getByRole("link", { name: "Registry and import" }).click();
    await page.getByRole("link", { name: "Registry import" }).click();
    const files = page.getByLabel("Files");
    await files.setInputFiles({ name: "tags.csv", mimeType: "text/csv", buffer: Buffer.from("x") });
    await page.getByRole("button", { name: "Validate" }).click();
    const report = page.getByRole("table", { name: "Validation report" });
    await expect(report).toContainText("asset 'X-9' does not exist");
    await expect(page.getByRole("button", { name: "Import" })).toBeDisabled();

    await files.setInputFiles({
      name: "assets.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(ASSETS_CSV),
    });
    await page.getByRole("button", { name: "Validate" }).click();
    await expect(page.getByRole("table", { name: "Changes the import will make" })).toContainText(
      "2 created, 1 updated",
    );
    await page.getByRole("button", { name: "Import" }).click();
    await expect(page.getByText("Imported.")).toBeVisible();
    expect(sent).toEqual(["validate:tags", "validate:assets", "import:assets"]);
  });

  test("journey: preview a history file, then import the same upload", async ({ page }) => {
    await mockApi(page, { sites: 1, units: 1, perUnit: 2 });
    const report = (preview: boolean) => ({
      layout: "long",
      preview,
      rows_read: 1442,
      loaded: preview ? 0 : 1440,
      duplicates: 0,
      rejected: 2,
      overlap: 0,
      reconciles: true,
      rejected_by_reason: { invalid_timestamp: 1, unregistered_tag: 1 },
      unmapped_tags: { "NEW.PV": 1 },
      tags_found: 1,
      first_ts: "2026-10-20T00:00:00Z",
      last_ts: "2026-10-20T23:59:00Z",
      problems: [{ row: 7, reason: "invalid_timestamp", detail: "'yesterday'" }],
    });
    const polls: Record<number, number> = {};
    const steps: string[] = [];
    await page.route("**/api/v1/ingest/backfill**", (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/load")) {
        steps.push(`load ${path.split("/")[5]}`);
        return json(route, { job_id: 2, upload_id: "a".repeat(32), preview: false }, 202);
      }
      steps.push("upload");
      return json(route, { job_id: 1, upload_id: "a".repeat(32), preview: true }, 202);
    });
    await page.route("**/api/v1/jobs/*", (route) => {
      const id = Number(new URL(route.request().url()).pathname.split("/").pop());
      polls[id] = (polls[id] ?? 0) + 1;
      const done = polls[id] > 1;
      return json(route, {
        id,
        type: "ingest.backfill",
        status: done ? "succeeded" : "running",
        progress: done ? 100 : 50,
        attempts: 1,
        result: done ? report(id === 1) : null,
        error: null,
        created_at: new Date().toISOString(),
        finished_at: null,
      });
    });

    await page.goto("/admin/registry?tab=history");
    await page.getByLabel("File", { exact: true }).setInputFiles({
      name: "history.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("ts,tag,value\n"),
    });
    await page.getByRole("combobox", { name: "Source (gateway)" }).fill("gw-site-a-01");
    await page.getByRole("button", { name: "Preview" }).click();
    await expect(page.getByRole("heading", { name: "Preview (nothing stored)" })).toBeVisible();
    await expect(page.getByText("1,440 (0 already stored)")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Timestamp not readable: 1/).first()).toBeVisible();
    await page.getByRole("button", { name: "Import" }).click();
    await expect(page.getByText("✔ yes")).toBeVisible({ timeout: 10_000 });
    expect(steps).toEqual(["upload", `load ${"a".repeat(32)}`]);
  });
});
