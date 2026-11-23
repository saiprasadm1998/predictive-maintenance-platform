import { expect, test } from "@playwright/test";

import { mockCases } from "./caseMock";
import { mockApi } from "./mockApi";

test.describe("SCR-05 and SCR-09 cases", () => {
  test("journey (AC-06 rehearsal): detect, diagnose, act and close", async ({ page }) => {
    const { alerts } = await mockApi(page, { sites: 1, units: 2, perUnit: 6 });
    await mockCases(page, alerts);
    const alert = alerts[0]!;

    // Detect: the alert opens its equipment.
    await page.goto("/alerts");
    await page
      .getByRole("row", { name: /^Select alert A-1 / })
      .getByRole("link", { name: new RegExp(alert.asset_code) })
      .click();
    await expect(page).toHaveURL(new RegExp(`/assets/${alert.asset_id}\\?alert=${alert.id}`));

    // Diagnose: failure modes ranked by match and the time to limit.
    const tabs = page.getByRole("tablist", { name: "Analysis" });
    await tabs.getByRole("tab", { name: "Diagnosis" }).click();
    await expect(page.getByRole("button", { name: /Seal leak .* 82 %/ })).toBeVisible();
    await tabs.getByRole("tab", { name: "Time to limit" }).click();
    await expect(page.getByText(/median 5\.0 d/)).toBeVisible();

    // Act: a case from the alert, with its frozen snapshot.
    await page.goto("/alerts");
    await page.getByRole("checkbox", { name: "Select alert A-1" }).check();
    await page.getByRole("button", { name: "Create case", exact: true }).click();
    const create = page.getByRole("dialog", { name: "Create case" });
    await create.getByLabel("Title").fill("Seal leak suspected");
    await create.getByRole("button", { name: "Create case" }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: "C-0001 Seal leak suspected" }),
    ).toBeVisible();
    await expect(page.getByRole("definition").filter({ hasText: "Seal leak, 82 %" })).toBeVisible();
    await expect(page.getByRole("definition").filter({ hasText: "TI-1 60 %" })).toBeVisible();

    const status = page.getByRole("list", { name: "Case status" });
    await page.getByLabel("Assignee").selectOption({ label: "Max Maintenance" });
    await page.getByRole("button", { name: "Save fields" }).click();
    await expect(status.getByRole("listitem").first()).toHaveText(/✓\s*Open/);

    const activity = page.getByRole("region", { name: "Activity" });
    await activity.getByRole("tab", { name: "Action" }).click();
    await activity.getByLabel("New entry").fill("Replace the mechanical seal");
    await activity.getByLabel("Owner").selectOption({ label: "Max Maintenance" });
    await activity.getByRole("button", { name: "Add" }).click();
    const actions = page.getByRole("region", { name: "Actions" });
    await expect(actions).toContainText("Replace the mechanical seal");

    // Close: a true finding with its confirmed failure mode.
    await page.getByRole("button", { name: "Close case" }).click();
    const close = page.getByRole("dialog", { name: "Close case C-0001" });
    await close.getByLabel(/Outcome/).selectOption("true_finding");
    await close.getByLabel("Confirmed failure mode").selectOption({ label: "Seal leak" });
    await close.getByLabel("Lessons learned").fill("Seal wear shows in TI1 a week ahead");
    await close.getByRole("button", { name: "Close case" }).click();
    await expect(close).toBeHidden();
    await expect(status.getByRole("listitem").last()).toHaveText(/Closed/);

    // The case list keeps it, closed, with its outcome.
    await page.goto("/cases");
    await expect(page.getByRole("row", { name: /C-0001.*Closed.*True finding/ })).toBeVisible();
  });
});
