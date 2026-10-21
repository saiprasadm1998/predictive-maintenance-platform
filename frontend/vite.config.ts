/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the browser talks only to Vite (port 5173); /api is passed on to the
// web role, so the session cookie and the CSRF header work without any CORS setup.
const api = process.env.PMP_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: api, changeOrigin: false },
    },
  },
  build: {
    outDir: "dist",
    // Not "assets": /assets/:id is the asset analysis route, and the web role serves the build.
    assetsDir: "static",
    sourcemap: true,
    // The chart library (ECharts) is one chunk of about 580 kB (195 kB compressed), loaded
    // only by screens with charts.
    chunkSizeWarningLimit: 700,
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"], // e2e/ is Playwright's
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    restoreMocks: true,
  },
});
