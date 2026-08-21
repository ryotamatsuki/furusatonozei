const { test, expect } = require("@playwright/test");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "../..");
const manifest = JSON.parse(
  fs.readFileSync(path.join(root, "data/source_manifest.json"), "utf8"),
);
const processed = JSON.parse(
  fs.readFileSync(path.join(root, "data/processed/furusato_data.json"), "utf8"),
);
const years = Object.keys(manifest.sources)
  .map(Number)
  .sort((a, b) => a - b);
const latestYear = years.at(-1);
const yearLabel = (year) => manifest.sources[String(year)].receipt_fiscal_year_label;
const latestRecords = processed.years[String(latestYear)].records;
const recordLabel = (record) => `${record.prefecture} ${record.municipality}`;
const topReceipt = [...latestRecords].sort(
  (a, b) => b.received - a.received,
)[0];
const smallReceipt = [...latestRecords].sort(
  (a, b) => a.received - b.received,
)[0];
const negativeReference = latestRecords.find(
  (record) => record.balance_with_75pct_reference < 0,
);

function diagnosticsFor(page) {
  const diagnostics = {
    consoleErrors: [],
    pageErrors: [],
    failedRequests: [],
    fatalResponses: [],
  };
  page.on("console", (message) => {
    if (message.type() === "error") diagnostics.consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => diagnostics.pageErrors.push(error.message));
  page.on("requestfailed", (request) => {
    if (!request.url().endsWith("/favicon.ico")) {
      diagnostics.failedRequests.push({
        method: request.method(),
        url: request.url(),
        error: request.failure()?.errorText || "request failed",
      });
    }
  });
  page.on("response", (response) => {
    if (response.status() >= 400 && !response.url().endsWith("/favicon.ico")) {
      diagnostics.fatalResponses.push({ status: response.status(), url: response.url() });
    }
  });
  return diagnostics;
}

async function openDashboard(page) {
  const diagnostics = diagnosticsFor(page);
  await page.goto("./index.html", { waitUntil: "domcontentloaded" });
  await expect(page.locator("#historyMunicipality option")).toHaveCount(1741);
  await expect(page.locator("#historyTable tbody tr")).toHaveCount(years.length);
  return diagnostics;
}

function assertBrowserClean(diagnostics) {
  expect(diagnostics.pageErrors, JSON.stringify(diagnostics)).toEqual([]);
  expect(diagnostics.consoleErrors, JSON.stringify(diagnostics)).toEqual([]);
  expect(diagnostics.failedRequests, JSON.stringify(diagnostics)).toEqual([]);
  expect(diagnostics.fatalResponses, JSON.stringify(diagnostics)).toEqual([]);
}

async function assertNoInvalidNumbers(page) {
  const bodyText = await page.locator("body").innerText();
  expect(bodyText).not.toMatch(/\b(?:NaN|Infinity|-Infinity|undefined|null)\b/);
}

async function waitForMap(page) {
  await page.waitForFunction(
    () =>
      Boolean(
        window.__fzMap &&
          window.__fzMap.loaded() &&
          window.__fzMap.isStyleLoaded(),
      ),
    null,
    { timeout: 45_000 },
  );
  await expect(page.locator("#map canvas").first()).toBeVisible();
  await expect(page.locator("#mapError")).toBeHidden();
}

test("loads the latest year and exposes the complete six-year selector", async ({ page }) => {
  const diagnostics = await openDashboard(page);

  await expect(page.locator("#fiscalYear")).toHaveValue(String(latestYear));
  await expect(page.locator("#fiscalYear option")).toHaveCount(years.length);
  expect(await page.locator("#fiscalYear option").evaluateAll((options) => options.map((option) => Number(option.value)))).toEqual(years);
  await expect(page.locator("#historySelectedYear")).toContainText(yearLabel(latestYear));
  await assertNoInvalidNumbers(page);
  assertBrowserClean(diagnostics);
});

test("switches every fiscal year and keeps derived indicators finite", async ({ page }) => {
  const diagnostics = await openDashboard(page);
  const rankingByYear = [];

  for (const year of years) {
    await page.locator("#fiscalYear").selectOption(String(year));
    await page.waitForFunction((expected) => window.__fzFiscalYear === expected, year);
    await expect(page.locator("#historySelectedYear")).toContainText(yearLabel(year));
    await expect(page.locator("#historyTable tbody tr")).toHaveCount(years.length);
    rankingByYear.push(await page.locator("#rankHigh").innerText());
    await assertNoInvalidNumbers(page);
  }

  expect(new Set(rankingByYear).size).toBeGreaterThan(1);
  await expect(page.locator("#historySummary")).toContainText(
    `${yearLabel(years[0])}→${yearLabel(latestYear)} 増減率`,
  );
  await expect(page.locator("#historySummary")).not.toContainText("5年");
  assertBrowserClean(diagnostics);
});

test("renders municipality detail, both trend charts, rates, and analysis charts", async ({ page }) => {
  const diagnostics = await openDashboard(page);

  await page.locator('.tab-btn[data-tab="history"]').click();
  const municipality = page.locator("#historyMunicipality");
  await municipality.selectOption({ label: "愛媛県 松山市" });
  await expect(page.locator("#historyTitle")).toHaveText("愛媛県松山市");
  await expect(page.locator("#historyTable tbody tr")).toHaveCount(years.length);
  await expect(page.locator("#historyReceivedChart svg")).toBeVisible();
  await expect(page.locator("#historyBalanceChart svg")).toBeVisible();
  await expect(page.locator("#historySummary .summary-card")).toHaveCount(6);
  await assertNoInvalidNumbers(page);

  await page.locator('.tab-btn[data-tab="distribution"]').click();
  await page.waitForFunction(
    () => document.querySelectorAll("#distSummary .summary-card").length > 0,
    null,
    { timeout: 20_000 },
  );
  await expect(page.locator("#distChart")).toBeVisible();
  await expect(page.locator("#distSummary .summary-card")).not.toHaveCount(0);

  await page.locator('.tab-btn[data-tab="features"]').click();
  await page.waitForFunction(
    () => document.querySelectorAll("#featureSummary .summary-card").length > 0,
    null,
    { timeout: 20_000 },
  );
  await expect(page.locator("#scatterChart")).toBeVisible();
  await expect(page.locator("#groupChart")).toBeVisible();
  await assertNoInvalidNumbers(page);
  assertBrowserClean(diagnostics);
});

test("spot-checks five representative municipalities in the history selector", async ({ page }) => {
  const diagnostics = await openDashboard(page);
  await page.locator('.tab-btn[data-tab="history"]').click();
  const labels = [
    recordLabel(topReceipt),
    recordLabel(smallReceipt),
    recordLabel(negativeReference),
    "愛媛県 松山市",
    "東京都 世田谷区",
  ];

  for (const label of [...new Set(labels)]) {
    await page.locator("#historyMunicipality").selectOption({ label });
    await expect(page.locator("#historyTitle")).toHaveText(label.replace(" ", ""));
    await expect(page.locator("#historyTable tbody tr")).toHaveCount(years.length);
  }
  await assertNoInvalidNumbers(page);
  assertBrowserClean(diagnostics);
});

test("loads the map and opens a municipality popup from a rendered boundary", async ({ page }) => {
  const diagnostics = await openDashboard(page);
  await waitForMap(page);

  const hit = await page.evaluate(() => {
    const map = window.__fzMap;
    const features = map.queryRenderedFeatures({ layers: ["n03-fill"] });
    const feature = features.find((candidate) => candidate.geometry?.coordinates);
    if (!feature) return null;
    const points = [];
    const walk = (value) => {
      if (
        Array.isArray(value) &&
        value.length >= 2 &&
        typeof value[0] === "number" &&
        typeof value[1] === "number"
      ) {
        points.push(value);
      } else if (Array.isArray(value)) {
        value.forEach(walk);
      }
    };
    walk(feature.geometry.coordinates);
    if (!points.length) return null;
    const lng = points.reduce((sum, point) => sum + point[0], 0) / points.length;
    const lat = points.reduce((sum, point) => sum + point[1], 0) / points.length;
    const screen = map.project([lng, lat]);
    const rect = map.getContainer().getBoundingClientRect();
    return { x: rect.left + screen.x, y: rect.top + screen.y };
  });

  expect(hit).not.toBeNull();
  await page.mouse.click(hit.x, hit.y);
  const clickedPopup = page.locator(".maplibregl-popup").last();
  const clickedPopupContent = page.locator(".maplibregl-popup-content").last();
  await expect(clickedPopup).toBeVisible({ timeout: 10_000 });
  await expect(clickedPopupContent).toContainText("財政影響参考額");
  await expect(clickedPopupContent).toContainText("実質収支ではありません");
  assertBrowserClean(diagnostics);
});
