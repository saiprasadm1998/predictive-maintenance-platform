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

    await page.goto("/admin");
    await page.getByRole("link", { name: "API keys" }).click();
    await page.getByRole("textbox", { name: "Name", exact: true }).fill("Gateway site A");
    await page.getByRole("combobox", { name: "Scope" }).selectOption("ingest");
    await page.getByRole("button", { name: "Issue key" }).click();

    const once = page.getByRole("region", { name: /copy it now/ });
    await expect(once.getByLabel("The new key")).toHaveText("pmp_a1b2c3d4_the-secret-part");
    await once.getByRole("button", { name: "Copy" }).click();
    await expect(once.getByRole("button", { name: "Copied" })).toBeVisible();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
      "pmp_a1b2c3d4_the-secret-part",
    );
    await once.getByRole("button", { name: "I have stored it" }).click();
    await expect(page.getByText("the-secret-part")).toHaveCount(0);

    const table = page.getByRole("table", { name: "API keys" });
    await expect(table).toContainText("a1b2c3d4…");
    await table.getByRole("button", { name: "Revoke Gateway site A" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Revoke" }).click();
    await expect(table).toContainText("Revoked");
    expect(calls).toEqual(["POST /api-keys", "POST /api-keys/1/revoke"]);
  });
});
