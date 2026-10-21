import { expect, test } from "@playwright/test";

import { mockApi } from "./mockApi";

test.describe("SCR-02 alert list", () => {
  test("journey: acknowledge one alert, shelve two, then open an asset on its alert window", async ({
    page,
  }) => {
    await mockApi(page, { sites: 1, units: 2, perUnit: 6 });
    await page.goto("/alerts");
    const table = page.getByRole("table", { name: "Alerts" });
    const rows = table.getByRole("row");
    await expect(rows).toHaveCount(1 + 2); // header and two Alert assets in this fleet

    await table.getByRole("checkbox", { name: /^Select alert 1 / }).check();
    await page.getByRole("button", { name: "Acknowledge", exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Acknowledge" }).click();
    await expect(rows.nth(1)).toContainText("Active · ack");

    await table.getByRole("checkbox", { name: "Select all alerts shown" }).check();
    await page.getByRole("button", { name: "Shelve…" }).click();
    const dialog = page.getByRole("dialog", { name: "Shelve 2 alerts" });
    await expect(dialog.getByRole("button", { name: "Shelve" })).toBeDisabled();
    await dialog.getByLabel("For").selectOption("240");
    await dialog.getByLabel(/Reason/).fill("pump swap on unit 0");
    await dialog.getByRole("button", { name: "Shelve" }).click();
    await expect(rows.nth(1)).toContainText(/Shelved · 3 h 5\d min left|Shelved · 4 h left/);
    await expect(rows.nth(2)).toContainText("Shelved");

    await rows.nth(1).getByRole("link").click();
    await expect(page).toHaveURL(/\/assets\/\d+\?.*from=/);
  });

  test("filters live in the URL, so a link reopens the same list", async ({ page }) => {
    await mockApi(page, { sites: 1, units: 1, perUnit: 6 });
    await page.goto("/alerts?priority=P1&state=Active-Unacknowledged");
    await expect(page.getByRole("button", { name: /Priority: P1/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /State: Active · unack/ })).toBeVisible();
  });
});
