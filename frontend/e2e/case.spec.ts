import { expect, test } from "@playwright/test";

import { mockCases } from "./caseMock";
import { mockApi } from "./mockApi";

test.describe("SCR-05 and SCR-09 cases", () => {
  test("journey (AC-06 rehearsal): detect, diagnose, act and close", async ({ page }) => {
    const { alerts } = await mockApi(page, { sites: 1, units: 2, perUnit: 6 });
    await mockCases(page, alerts);
    const alert = alerts[0]!;

    // Detect: the alert list shows the alert; its asset opens on the alert's window.
    await page.goto("/alerts");
    const row = page.getByRole("row", { name: new RegExp(alert.asset_code) }).first();
    await row.getByRole("link", { name: new RegExp(alert.asset_code) }).click();
    await expect(page).toHaveURL(new RegExp(`/assets/${alert.asset_id}\\?.*alert=${alert.id}`));

    // Diagnose: failure modes ranked by match and the forecast.
    await page.getByRole("link", { name: /Diagnose/ }).click();
    const modes = page.getByRole("list", { name: "Failure modes ranked by match" });
    await expect(modes.getByRole("button", { name: /Seal leak: 82/ })).toBeVisible();
    await expect(page.getByText("Urgency: HIGH")).toBeVisible();

    // Act: a case from the asset's open alert, with its snapshot.
    await page.getByRole("button", { name: "Create case…" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel(/Title/).fill("Seal leak suspected");
    await dialog.getByRole("button", { name: "Create case" }).click();
    await expect(page.getByRole("heading", { name: "C-0001 · Seal leak suspected" })).toBeVisible();
    const snapshot = page.getByRole("region", { name: "Snapshot at creation" });
    await expect(snapshot.getByText("82 %")).toBeVisible();
    const stepper = page.getByRole("list", { name: "Case status" });
    await expect(stepper.locator('[aria-current="step"]')).toHaveText("Open");

    const assignee = page.getByLabel("Assignee");
    await expect(assignee.locator("option", { hasText: "Max Maintenance" })).toBeAttached();
    await assignee.selectOption({ label: "Max Maintenance" });
    await expect(stepper.locator('[aria-current="step"]')).toHaveText("Investigating");
    const add = page.getByRole("form", { name: "Add activity" });
    await add.getByRole("radio", { name: "Action" }).check();
    await add.getByLabel("What to do").fill("Replace the mechanical seal");
    await add.getByLabel("Owner").selectOption({ label: "Max Maintenance" });
    await add.getByRole("button", { name: "Add action" }).click();
    await expect(stepper.locator('[aria-current="step"]')).toHaveText("Action required");
    await page.getByRole("button", { name: "Mark done" }).click();
    await expect(stepper.locator('[aria-current="step"]')).toHaveText("Monitoring");

    // Close: a true finding with its confirmed failure mode.
    const closure = page.getByRole("form", { name: "Close case" });
    await closure.getByLabel("Outcome").selectOption("true_finding");
    await expect(closure.getByRole("button", { name: "Close case" })).toBeDisabled();
    await closure.getByLabel(/Confirmed mode/).selectOption({ label: "Seal leak" });
    await closure.getByLabel(/Lessons learned/).fill("Seal wear shows in TI1 a week ahead");
    await closure.getByRole("button", { name: "Close case" }).click();
    await expect(stepper.locator('[aria-current="step"]')).toHaveText("Closed");
    await expect(page.getByText("True finding", { exact: true })).toBeVisible();

    // The case list keeps it, closed, with its outcome.
    await page.goto("/cases");
    await expect(page.getByRole("row", { name: /C-0001.*Closed.*True finding/ })).toBeVisible();
  });
});
