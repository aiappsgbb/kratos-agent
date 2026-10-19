import { defineConfig, devices } from "@playwright/test";

// Deterministic end-to-end tests: the full local stack (hosted agent, backend,
// Next.js + CopilotKit runtime) against the scripted mock model. No login, no
// cost. Ports 3000/5567/8000/8088/10000 must be free.
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 60_000 },
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:3000",
    timezoneId: "UTC",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: {
    command: "node ../../scripts/dev-local.mjs --mock",
    url: "http://127.0.0.1:3000/config.json",
    timeout: 300_000,
    reuseExistingServer: false,
    stdout: "pipe",
  },
});
