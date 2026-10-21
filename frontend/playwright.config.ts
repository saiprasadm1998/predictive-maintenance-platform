import { defineConfig, devices } from "@playwright/test";

/**
 * Browser journeys (plan 6.2 onwards): the production build, served by `vite preview`, with
 * the REST API answered by fixtures in e2e/mockApi.ts, so they run anywhere without a
 * database. Run with `make fe-e2e` (first time: `npx playwright install chromium`).
 */
const port = 4173;

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    launchOptions: process.env.PMP_E2E_CHROMIUM
      ? { executablePath: process.env.PMP_E2E_CHROMIUM }
      : {},
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
  ],
  webServer: {
    command: `npm run build && npx vite preview --host 127.0.0.1 --port ${port} --strictPort`,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
