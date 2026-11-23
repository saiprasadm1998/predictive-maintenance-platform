import { type Route, expect, test } from "@playwright/test";

import { mockApi } from "./mockApi";

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

test.describe("SCR-14 administration", () => {
  test("journey: issue an API key, copy it once, then revoke it", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await mockApi(page, { sites: 1, units: 1, perUnit: 2 });
    type Key = {
      id: number;
      prefix: string;
      name: string;
      scope: string;
      revoked_at: string | null;
    };
    const keys: Key[] = [];
    const calls: string[] = [];
    await page.route("**/api/v1/api-keys**", (route) => {
      const method = route.request().method();
      const path = new URL(route.request().url()).pathname;
      if (method === "GET")
        return json(
          route,
          keys.map((k) => ({ ...k, created_at: new Date().toISOString(), last_used_at: null })),
        );
      calls.push(`${method} ${path.replace("/api/v1", "")}`);
      if (path.endsWith("/revoke")) {
        keys[0]!.revoked_at = new Date().toISOString();
        return route.fulfill({ status: 204 });
      }
      const body = route.request().postDataJSON() as { name: string; scope: string };
      keys.push({
        id: 1,
        prefix: "a1b2c3d4",
        name: body.name,
        scope: body.scope,
        revoked_at: null,
      });
      return json(route, { id: 1, key: "pmp_a1b2c3d4_the-secret-part", prefix: "a1b2c3d4" }, 201);
    });

    await page.goto("/system/users?tab=keys");
    await page.getByRole("button", { name: "Issue a key" }).click();
    const issue = page.getByRole("dialog", { name: "Issue an API key" });
    await issue.getByLabel("Name").fill("Gateway site A");
    await issue.getByLabel("Scope").selectOption("ingest");
    await issue.getByRole("button", { name: "Issue key" }).click();

    const once = page.getByRole("dialog", { name: "Key shown once" });
    await expect(once.getByLabel("API key")).toHaveValue("pmp_a1b2c3d4_the-secret-part");
    await once.getByRole("button", { name: "Copy" }).click();
    await expect(once.getByRole("button", { name: "Copied" })).toBeVisible();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
      "pmp_a1b2c3d4_the-secret-part",
    );
    await once.getByRole("button", { name: "Done" }).click();
    await expect(page.getByText("the-secret-part")).toHaveCount(0);

    const row = page.getByRole("row", { name: /Gateway site A/ });
    await expect(row).toContainText("a1b2c3d4");
    await row.getByRole("button", { name: "Revoke" }).click();
    await page
      .getByRole("dialog", { name: "Revoke Gateway site A?" })
      .getByRole("button", { name: "Revoke" })
      .click();
    await expect(row).toContainText("Revoked");
    expect(calls).toEqual(["POST /api-keys", "POST /api-keys/1/revoke"]);
  });
});
