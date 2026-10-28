import { expect, test } from "@playwright/test";

import { mockApi } from "./mockApi";

test.describe("SCR-03 asset analysis", () => {
  test("a sensor trend is one click from the fleet overview (NFR-USE-01: at most three)", async ({
    page,
  }) => {
    await mockApi(page, { sites: 1, units: 1, perUnit: 3 });
    await page.goto("/fleet");
    await page
      .getByRole("table")
      .getByRole("link", { name: /Pump S0U0E1/ })
      .click(); // 1
    await expect(page.getByRole("figure", { name: /TI1 sensor 1: actual/ })).toBeVisible();
    await expect(page.getByRole("table", { name: /Sensors at the latest cycle/ })).toBeVisible();

    // A click on the DI chart shows the contributors at that time (plan 6.7c).
    const di = page.getByRole("slider", { name: /Deviation Index/ });
    const box = (await di.boundingBox())!;
    await page.mouse.click(box.x + box.width * 0.5, box.y + box.height / 2);
    await expect(page).toHaveURL(/[?&]at=\d{4}-/);
    await expect(page.getByRole("heading", { name: /Top contributors at / })).toBeVisible();
    await page.getByRole("button", { name: "Back to the latest cycle" }).click();
    await expect(page.getByRole("heading", { name: "Top contributors now" })).toBeVisible();

    // Diagnostics (plan 8.2): failure modes ranked by match, symptoms and tasks.
    await page.getByRole("link", { name: /Diagnose/ }).click();
    const modes = page.getByRole("list", { name: "Failure modes ranked by match" });
    await expect(modes.getByRole("button", { name: /Seal leak: 82/ })).toBeVisible();
    await expect(page.getByText("Inspect the mechanical seal")).toBeVisible();
  });

  test("journey: from an alert to its asset with the alert's window selected", async ({ page }) => {
    const { alerts } = await mockApi(page, { sites: 1, units: 2, perUnit: 6 });
    const alert = alerts[0]!;
    await page.goto(`/assets/${alert.asset_id}?alert=${alert.id}`);
    await expect(page).toHaveURL(/from=.*&to=|to=.*&from=/);
    const url = new URL(page.url());
    const from = Date.parse(url.searchParams.get("from")!);
    expect(Date.parse(alert.raised_at) - from).toBe(12 * 3_600_000); // half a day before
    await expect(page.getByRole("button", { name: /Time range: .* – / })).toBeVisible();
    await expect(page.getByText("P1 · active · unack")).toBeVisible();
  });
});
