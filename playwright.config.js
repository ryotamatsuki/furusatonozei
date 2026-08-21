const { defineConfig, devices } = require("@playwright/test");

const externalBaseURL = process.env.BASE_URL;

module.exports = defineConfig({
  testDir: "./tests/e2e",
  testMatch: "**/*.spec.js",
  timeout: 60_000,
  expect: {
    timeout: 15_000,
  },
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
    ["junit", { outputFile: "test-results/e2e.xml" }],
  ],
  use: {
    baseURL: externalBaseURL || "http://127.0.0.1:4173",
    headless: true,
    locale: "ja-JP",
    timezoneId: "Asia/Tokyo",
    serviceWorkers: "block",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop",
      testMatch: "**/dashboard.spec.js",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "mobile",
      testMatch: "**/mobile.spec.js",
      use: { ...devices["Pixel 7"] },
    },
  ],
  ...(externalBaseURL
    ? {}
    : {
        webServer: {
          command: "python -m http.server 4173 --bind 127.0.0.1",
          url: "http://127.0.0.1:4173/index.html",
          reuseExistingServer: !process.env.CI,
          timeout: 30_000,
        },
      }),
});
