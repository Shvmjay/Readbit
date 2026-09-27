import { defineConfig, devices } from "@playwright/test";

// Chromium path override for environments with a pre-installed browser (see README).
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_PATH || undefined;

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://localhost:3001",
    trace: "retain-on-failure",
    launchOptions: { executablePath },
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], launchOptions: { executablePath } }, testIgnore: /mobile\.spec\.ts/ },
    { name: "mobile", use: { ...devices["Pixel 7"], launchOptions: { executablePath } }, testMatch: /mobile\.spec\.ts/ },
  ],
  webServer: [
    { command: "bash ../../scripts/e2e-api.sh", url: "http://127.0.0.1:8001/ready", reuseExistingServer: false, timeout: 60_000 },
    { command: "npx next start -p 3001", url: "http://localhost:3001", env: { API_URL: "http://127.0.0.1:8001" }, reuseExistingServer: false, timeout: 120_000 },
  ],
});
