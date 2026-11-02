import { createRequire } from "node:module";

import { type Page, expect, test } from "@playwright/test";

import { mockCases } from "./caseMock";
import { mockApi } from "./mockApi";

/**
 * WCAG 2.1 AA check (plan 9.2): axe-core's WCAG 2.0 and 2.1 A and AA rules, colour contrast
 * included, run in the browser on every main screen with the light and the dark theme.
 * The unit tests check the sign-in page and the shell; this covers the screens' content.
 */
const axePath = createRequire(import.meta.url).resolve("axe-core/axe.min.js");

interface Violation {
  id: string;
  impact: string | null;
  help: string;
  nodes: { target: string[] }[];
}

async function violations(page: Page): Promise<string[]> {
  await page.addScriptTag({ path: axePath });
  const found = await page.evaluate(async () => {
    const axe = (window as unknown as { axe: { run: (...a: unknown[]) => Promise<unknown> } }).axe;
    const result = (await axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
    })) as { violations: Violation[] };
    return result.violations;
  });
  return found.map(
    (v) =>
      `${v.id} (${v.impact}): ${v.help} — ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
  );
}

test.describe("WCAG 2.1 AA (axe-core in the browser)", () => {
  for (const scheme of ["light", "dark"] as const) {
    test(`the main screens have no violations (${scheme} theme)`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      const { leaves, alerts } = await mockApi(page, { sites: 1, units: 2, perUnit: 6 });
      await mockCases(page, alerts);
      const asset = leaves[0]!.id;
      const screens: [string, string][] = [
        ["/fleet", "table"],
        [`/assets/${asset}`, "main"],
        [`/assets/${asset}/diagnostics`, "main"],
        ["/alerts", "table"],
        ["/cases", "main"],
        ["/models", "table"],
        ["/sensors", "main"],
        ["/library", "main"],
        ["/admin/registry", "main"],
        ["/models/1/build/1", "main"],
        ["/admin?tab=users", "main"],
        ["/admin?tab=notifications", "main"],
      ];
      const report: string[] = [];
      for (const [path, ready] of screens) {
        await page.goto(path);
        await expect(page.getByRole(ready as "main" | "table").first()).toBeVisible();
        await page.waitForLoadState("networkidle");
        for (const line of await violations(page)) report.push(`${path}: ${line}`);
      }
      expect(report, report.join("\n")).toEqual([]);
    });
  }
});
