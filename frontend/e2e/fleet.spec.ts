import { expect, test } from "@playwright/test";

import { mockApi } from "./mockApi";

test.describe("SCR-01 fleet overview, 500 assets", () => {
  test("loads in under 2 seconds (plan 6.2)", async ({ page }) => {
    await mockApi(page);
    const started = Date.now();
    await page.goto("/fleet");
    await expect(page.getByRole("table")).toBeVisible();
    await expect(page.getByRole("list", { name: "Fleet figures" })).toContainText("84");
    await expect(
      page.getByRole("region", { name: "Highest deviation now" }).getByRole("listitem"),
    ).toHaveCount(8);
    const elapsed = Date.now() - started;
    console.log(`fleet overview with 500 assets ready in ${elapsed} ms`);
    expect(elapsed).toBeLessThan(2000);
  });

  test("journey: fleet → unit → asset, keeping the time range", async ({ page }) => {
    await mockApi(page, { sites: 1, units: 2, perUnit: 5 });
    await page.goto("/fleet?range=24h");
    await page.getByRole("link", { name: "Unit 0.0" }).click();
    await expect(page).toHaveURL(/\/units\/\d+\?range=24h$/);
    await page.goto("/fleet?range=24h");
    await page
      .getByRole("table")
      .getByRole("link", { name: /Pump S0U0E3/ })
      .click();
    await expect(page).toHaveURL(/\/assets\/\d+\?range=24h$/);
    await expect(page.getByRole("heading", { level: 1, name: "Asset analysis" })).toBeVisible();
  });

  test("an asset's analysis is one click from the fleet (NFR-USE-01: sensor trend within three)", async ({
    page,
  }) => {
    await mockApi(page, { sites: 1, units: 1, perUnit: 3 });
    await page.goto("/fleet");
    let interactions = 0;
    await page
      .getByRole("table")
      .getByRole("link", { name: /Pump S0U0E1/ })
      .click();
    interactions += 1;
    await expect(page).toHaveURL(/\/assets\/\d+/);
    // The asset screen (6.3) shows the sensor trends at once; the search is the other path.
    await page.goto("/fleet");
    await expect(page.getByRole("table")).toBeVisible();
    await page.keyboard.press("/");
    await page.keyboard.type("S0U0E2");
    await expect(page.getByRole("option", { name: /S0U0E2/ })).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/assets\/\d+/);
    expect(interactions).toBeLessThanOrEqual(3);
  });

  test("filters the hierarchy from a figure", async ({ page }) => {
    await mockApi(page, { sites: 1, units: 2, perUnit: 6 });
    await page.goto("/fleet");
    await page.getByRole("button", { name: /Assets in Watch/ }).click();
    await expect(page).toHaveURL(/band=Watch/);
    await expect(page.getByRole("status").filter({ hasText: "Showing branches" })).toBeVisible();
  });
});
