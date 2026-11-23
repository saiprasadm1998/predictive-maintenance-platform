import { expect, test } from "@playwright/test";

import { mockApi } from "./mockApi";

test.describe("SCR-03 equipment analysis", () => {
  test("journey: trends, diagnosis, time to limit and sensors of one equipment (NFR-USE-01)", async ({
    page,
  }) => {
    await mockApi(page, { sites: 1, units: 1, perUnit: 3 });
    await page.goto("/fleet");
    await page
      .getByRole("region", { name: "S0U0E0 Pump S0U0E0" })
      .getByRole("link", { name: "Review →" })
      .click(); // 1
    await expect(page.getByRole("heading", { level: 1, name: "Pump S0U0E0" })).toBeVisible();
    await expect(page.getByRole("img", { name: /^Deviation Index, last/ })).toBeVisible();
    await expect(page.getByRole("img", { name: /TI1\.PV actual and predicted/ })).toBeVisible();

    // A contributor toggles its trend.
    await page.getByRole("button", { name: /^FI-3 sensor 3/ }).click();
    await expect(page.getByRole("img", { name: /FI3\.PV actual and predicted/ })).toBeVisible();

    const tabs = page.getByRole("tablist", { name: "Analysis" });
    await tabs.getByRole("tab", { name: "Diagnosis" }).click();
    await expect(page.getByRole("button", { name: /Seal leak .* 82 %/ })).toBeVisible();
    await expect(page.getByText("Inspect the mechanical seal")).toBeVisible();

    await tabs.getByRole("tab", { name: "Time to limit" }).click();
    await expect(page.getByText(/Reaches 25 in .* \(median 5\.0 d\)/)).toBeVisible();

    await tabs.getByRole("tab", { name: /Sensors/ }).click();
    const sensors = page.getByRole("row", { name: /^TI-1 sensor 1 / });
    await expect(sensors).toContainText("Good");
    await sensors.getByRole("link", { name: "Chart" }).click();
    await expect(tabs.getByRole("tab", { name: "Trends and contributors" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  test("journey: from an alert to its equipment", async ({ page }) => {
    const { alerts } = await mockApi(page, { sites: 1, units: 2, perUnit: 6 });
    const alert = alerts[0]!;
    await page.goto(`/assets/${alert.asset_id}?alert=${alert.id}`);
    await expect(
      page.getByRole("heading", { level: 1, name: `Pump ${alert.asset_code}` }),
    ).toBeVisible();
    await expect(
      page.getByRole("definition").filter({ hasText: "P1, unacknowledged" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: /^Acknowledge \(\d+\)/ })).toBeVisible();
  });
});

test.describe("NFR-PERF-03 trend rendering", () => {
  test("an equipment with 800-point trends renders in under 3 seconds", async ({ page }) => {
    const { leaves } = await mockApi(page, { sites: 1, units: 1, perUnit: 3 }, 800);
    const started = Date.now();
    await page.goto(`/assets/${leaves[0]!.id}`);
    await expect(page.getByRole("img", { name: /^Deviation Index, last/ })).toBeVisible();
    await expect(page.getByRole("img", { name: /actual and predicted/ })).toHaveCount(2);
    const elapsed = Date.now() - started;
    console.log(`equipment analysis with 800-point trends rendered in ${elapsed} ms`);
    expect(elapsed).toBeLessThan(3000);
  });
});
