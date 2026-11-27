import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  globalSetup: "./tests/local-stack",
  outputDir: "./test-results/playwright",
  workers: 1,
  timeout: 45_000,
  use: {
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
});
