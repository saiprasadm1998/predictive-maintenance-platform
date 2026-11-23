import { expect, test } from "@playwright/test";

import { mockApi } from "./mockApi";

test.describe("SCR-01 overview, 500 assets", () => {
  test("loads in under 2 seconds (plan 6.2)", async ({ page }) => {
    await mockApi(page);
    const started = Date.now();
    await page.goto("/fleet");
    const summary = page.getByRole("region", { name: "Fleet summary" });
    await expect(summary.getByRole("link", { name: "Equipment monitored 500" })).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Equipment needing attention" }).getByRole("table"),
    ).toBeVisible();
    const elapsed = Date.now() - started;
    console.log(`overview with 500 assets ready in ${elapsed} ms`);
    expect(elapsed).toBeLessThan(2000);
  });

  test("journey: overview → unit → equipment", async ({ page }) => {
    await mockApi(page, { sites: 1, units: 2, perUnit: 5 });
    await page.goto("/fleet");
    await page
      .getByRole("navigation", { name: "Predictive Maintenance" })
      .getByRole("link", { name: "Unit view" })
      .click();
    await expect(page.getByRole("heading", { level: 1, name: "Unit 0.0" })).toBeVisible();
    await page
      .getByRole("region", { name: "Equipment in the unit" })
      .getByRole("link", { name: /S0U0E3 Pump S0U0E3/ })
      .click();
    await expect(page).toHaveURL(/\/assets\/\d+/);
    await expect(page.getByRole("heading", { level: 1, name: "Pump S0U0E3" })).toBeVisible();
  });

  test("an equipment's analysis is one click from the overview, or found by search (NFR-USE-01)", async ({
    page,
  }) => {
    await mockApi(page, { sites: 1, units: 2, perUnit: 5 });
    await page.goto("/fleet");
    await page
      .getByRole("region", { name: "Equipment needing attention" })
      .getByRole("link", { name: "S0U0E4 →" })
      .click();
    await expect(page.getByRole("heading", { level: 1, name: "Pump S0U0E4" })).toBeVisible();

    await page.goto("/fleet");
    await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
    await page.keyboard.press("/");
    await page.keyboard.type("S0U0E2");
    await expect(page.getByRole("option", { name: /S0U0E2/ })).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { level: 1, name: "Pump S0U0E2" })).toBeVisible();
  });

  test("a summary figure opens the equipment list filtered by band", async ({ page }) => {
    await mockApi(page, { sites: 1, units: 2, perUnit: 6 });
    await page.goto("/fleet");
    await page.getByRole("link", { name: /^In watch \d+/ }).click();
    await expect(page).toHaveURL(/\/equipment\?band=Watch/);
    await expect(page.getByRole("heading", { level: 1, name: "Equipment" })).toBeVisible();
    const rows = page.getByRole("table").getByRole("row");
    await expect(rows.filter({ hasText: "Watch" }).first()).toBeVisible();
    await expect(rows.filter({ hasText: "Healthy" })).toHaveCount(0);
  });
});
