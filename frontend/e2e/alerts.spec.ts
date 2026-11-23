import { expect, test } from "@playwright/test";

import { mockApi } from "./mockApi";

test.describe("SCR-02 alert list", () => {
  test("journey: acknowledge one alert, shelve both, then open an equipment from its alert", async ({
    page,
  }) => {
    await mockApi(page, { sites: 1, units: 2, perUnit: 6 });
    await page.goto("/alerts");
    const queue = page.getByRole("region", { name: "Alert queue" });
    const rows = queue.getByRole("row", { name: /^Select alert A-/ });
    await expect(rows).toHaveCount(2); // the two Alert assets in this fleet

    await queue.getByRole("checkbox", { name: "Select alert A-1" }).check();
    await page.getByRole("button", { name: "Acknowledge", exact: true }).click();
    const ack = page.getByRole("dialog", { name: "Acknowledge 1 alert" });
    await ack.getByLabel(/Comment/).fill("Checked on the DCS");
    await ack.getByRole("button", { name: "Acknowledge" }).click();
    await expect(ack).toBeHidden();
    await expect(queue.getByRole("row", { name: /^Select alert A-1 / })).toContainText(
      "Acknowledged",
    );

    await queue.getByRole("checkbox", { name: "Select alert A-1" }).check();
    await queue.getByRole("checkbox", { name: "Select alert A-2" }).check();
    await page.getByRole("button", { name: "Shelve", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Shelve 2 alerts" });
    await dialog.getByRole("button", { name: "Shelve" }).click();
    await expect(dialog.getByText("Enter a reason to shelve.")).toBeVisible();
    await dialog.getByLabel("For").selectOption("240");
    await dialog.getByLabel(/Reason/).fill("pump swap on unit 0");
    await dialog.getByRole("button", { name: "Shelve" }).click();
    await expect(dialog).toBeHidden();

    await page.getByRole("button", { name: /^Shelved \d/ }).click();
    await expect(queue.getByRole("row", { name: /^Select alert A-/ })).toHaveCount(2);
    await expect(queue.getByRole("row", { name: /^Select alert A-1 / })).toContainText("Shelved");

    await queue
      .getByRole("row", { name: /^Select alert A-1 / })
      .getByRole("link")
      .click();
    await expect(page).toHaveURL(/\/assets\/\d+\?alert=1/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Pump");
  });

  test("filters live in the URL, so a link reopens the same list", async ({ page }) => {
    await mockApi(page, { sites: 1, units: 1, perUnit: 6 });
    await page.goto("/alerts?priority=P1&state=Active-Unacknowledged");
    await expect(page.getByRole("combobox", { name: "Priority" })).toHaveValue("P1");
    await expect(page.getByRole("combobox", { name: "State" })).not.toHaveValue("");
    await page.getByRole("combobox", { name: "Severity" }).selectOption("Alert");
    await expect(page).toHaveURL(/severity=Alert/);
    await page.reload();
    await expect(page.getByRole("combobox", { name: "Severity" })).toHaveValue("Alert");
  });
});
