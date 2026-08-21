const { test, expect } = require("@playwright/test");
const fs = require("node:fs");
const path = require("node:path");

const manifest = JSON.parse(
  fs.readFileSync(
    path.resolve(__dirname, "../../data/source_manifest.json"),
    "utf8",
  ),
);
const latestYear = Math.max(...Object.keys(manifest.sources).map(Number));

test("keeps the latest-year controls and history readable on a phone viewport", async ({ page }) => {
  const consoleErrors = [];
  const pageErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.goto("./index.html", { waitUntil: "domcontentloaded" });
  await expect(page.locator("#fiscalYear")).toHaveValue(String(latestYear));
  await expect(page.locator("#historyMunicipality option")).toHaveCount(1741);
  await page.locator('.tab-btn[data-tab="history"]').click();
  await expect(page.locator("#historyTitle")).toBeVisible();
  await expect(page.locator("#historyReceivedChart svg")).toBeVisible();
  await expect(page.locator("#historyBalanceChart svg")).toBeVisible();

  const layout = await page.evaluate(() => ({
    viewportWidth: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    bodyWidth: document.body.scrollWidth,
  }));
  expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth + 2);
  expect(layout.bodyWidth).toBeLessThanOrEqual(layout.viewportWidth + 2);
  await expect(page.locator("body")).not.toContainText(/\b(?:NaN|Infinity|-Infinity|undefined|null)\b/);
  expect(pageErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
