import { execFile } from "node:child_process";
import { readFileSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { promisify } from "node:util";
import { expect, test, type Page, type Route } from "@playwright/test";

const fixtures = resolve(__dirname, "../../../docs/fixtures");
const exec = promisify(execFile);
const source = readFileSync(resolve(fixtures, "core.trade"), "utf8");

async function createStrategy(page: Page, name: string, strategy: string) {
  await page.goto("/strategies");
  await page.getByRole("button", { name: "New strategy", exact: true }).click();
  await page.getByLabel("Strategy name").fill(name);
  await page.getByRole("button", { name: "Create strategy", exact: true }).click();
  const editor = page.getByRole("textbox", { name: "Strategy source" });
  await editor.fill(strategy);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Revision saved.")).toBeVisible();
  return editor;
}

function origin() {
  const value = process.env.TRADELANG_TEST_ORIGIN;
  if (!value) throw new Error("The isolated TradeLang test stack is unavailable");
  return value;
}

test.use({ baseURL: async ({}, use) => { await use(origin()); } });
const datasetPicker = (page: Page) => page.getByRole("combobox", { name: "Dataset", exact: true });
const runButton = (page: Page) => page.getByRole("button", { name: "Run backtest", exact: true });
const openRunLink = (page: Page) => page.getByRole("link", { name: /^Open run(?: ·|$)/ }).first();
const sourceView = (page: Page) => page.getByRole("link", { name: "Source", exact: true });

async function submit(page: Page) {
  const sourceUrl = page.url();
  const editor = page.getByRole("textbox", { name: "Strategy source" });
  for (let attempt = 0; ; attempt++) {
    const validation = page.waitForResponse((response) =>
      new URL(response.url()).pathname === "/api/v1/strategies/validate" &&
      response.request().method() === "POST");
    await editor.press("Control+Shift+Enter");
    const response = await validation;
    if (response.status() !== 429 || attempt >= 2) {
      expect(response.ok()).toBe(true);
      break;
    }
    const retry = Number(response.headers()["retry-after"]);
    expect(retry).toBeGreaterThan(0);
    expect(retry).toBeLessThanOrEqual(60);
    await delay(retry * 1000);
  }
  await expect(page.getByText("Strategy and dataset validated.")).toBeVisible();
  await editor.press("Control+Enter");
  await expect(page.getByRole("status").filter({ hasText: "Backtest submitted for revision" })).toBeVisible();
  expect(page.url()).toBe(sourceUrl);
  await openRunLink(page).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Closed trades" })).toBeVisible({ timeout: 20_000 });
  return new URL(page.url()).searchParams.get("run")!;
}

async function importFixture(page: Page, filename: string, symbol = "TESTUSDT",
  csv = readFileSync(resolve(fixtures, "core.csv")), timeframe = "1d") {
  const response = await page.request.post("/api/v1/datasets/import", {
    headers: { Origin: origin() },
    multipart: {
      file: { name: filename, mimeType: "text/csv", buffer: csv },
      metadata: JSON.stringify({
        symbol, quote_currency: "USDT", timeframe, calendar: "24x7",
        timestamp_convention: "bar_open", price_basis: "raw_spot", volume_unit: "base_quantity", gap_policy: "reject",
      }),
    },
  });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).dataset.id as string;
}

function gate() {
  let open!: () => void;
  const wait = new Promise<void>((resolve) => { open = resolve; });
  return { wait, open };
}

test("open the terminal shell and recover from empty and unavailable lists", async ({ page }) => {
  for (const [route, message] of [
    ["/", "No strategies yet"], ["/datasets", "No datasets yet"],
    ["/runs", "No backtests yet"], ["/compare", "Select two to four succeeded runs"],
  ]) {
    await page.goto(route);
    await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
    await expect(page.getByRole("heading", { name: message })).toBeVisible();
    expect(await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link").count()).toBe(4);
  }
  const delayed = gate();
  const fail = async (route: Route) => {
    await delayed.wait;
    await route.fulfill({ status: 503 });
  };
  await page.route("**/api/v1/datasets", fail);
  await page.goto("/datasets");
  await expect(page.getByRole("status")).toContainText("Loading");
  delayed.open();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("The local API is unavailable");
  await page.unroute("**/api/v1/datasets", fail);
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("heading", { name: "No datasets yet" })).toBeVisible();
});

test("use dataset metadata for strategies without market or timeframe declarations", async ({ page }) => {
  const first = await importFixture(page, "inference.csv", "INFERUSDT");
  const second = await importFixture(page, "other-market.csv", "ALTINFERUSDT");
  await page.goto("/strategies");
  await page.getByRole("button", { name: "New strategy", exact: true }).click();
  await page.getByLabel("Start from").selectOption("EMA Crossover");
  await page.getByRole("button", { name: "Create strategy", exact: true }).click();
  const editor = page.getByRole("textbox", { name: "Strategy source" });
  await expect(editor).toContainText("EMA Crossover");
  await expect(editor).not.toContainText(/\b(?:market|timeframe)\s/);
  await editor.fill(source.replace("market TESTUSDT\ntimeframe 1d\n", ""));
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Revision saved.")).toBeVisible();

  await datasetPicker(page).selectOption(first);
  await editor.press("Control+Shift+Enter");
  await expect(runButton(page)).toBeEnabled();
  await datasetPicker(page).selectOption(second);
  await expect(runButton(page)).toBeDisabled();

  const id = await submit(page);
  const response = await page.request.get(`/api/v1/backtests/${id}`);
  expect(response.ok()).toBeTruthy();
  const run = await response.json();
  expect(run.status).toBe("succeeded");
  expect(run.configuration).toMatchObject({ market: "ALTINFERUSDT", timeframe_seconds: 86400 });
  expect(run.summary).toMatchObject({ symbol: "ALTINFERUSDT", timeframe: "1d" });
});

test("resolve DSL 2 overrides and ignore an unused profile declaration", async ({ page }) => {
  const candles = readFileSync(resolve(fixtures, "core.csv"), "utf8").replace("98,100,10", "98,100,11");
  const dataset = await importFixture(page, "dsl2.csv", "TESTUSDT", Buffer.from(candles));
  const parameterized = "tradelang 2\n" + source
    .replace("entry:", [
      "param limit: price = 115 price range [100 price, 130 price]",
      "param enabled: bool = false",
      "param period: count = 2 range [1 count, 3 count]",
      "let unused = VPROFILE(4, 1 price, 0.7).poc",
      "entry:",
    ].join("\n"))
    .replace("when true", "when enabled and close >= SMA(period)")
    .replace("close >= 112 price", "close >= limit");
  await createStrategy(page, "Parameterized exits", parameterized);
  await datasetPicker(page).selectOption(dataset);
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Volume Profile dataset" })).toHaveCount(0);
  await page.getByRole("spinbutton", { name: /^limit/ }).fill("110");
  await page.getByRole("spinbutton", { name: /^period/ }).fill("1");
  await page.getByRole("combobox", { name: "enabled", exact: true }).selectOption("true");
  await expect(runButton(page)).toBeDisabled();
  const id = await submit(page);
  const run = await (await page.request.get(`/api/v1/backtests/${id}`)).json();
  expect(run.configuration).toMatchObject({ parameters: { enabled: true, limit: 110, period: 1 } });
  expect(run.summary.metrics.closed_trades).toBe(1);
  const details = page.locator("details").filter({ has: page.getByText("Run details", { exact: true }) });
  await details.getByText("Run details", { exact: true }).click();
  await expect(details.getByText("Parameter limit", { exact: true })).toBeVisible();
});

test("duplicate a run preset and vary a period without changing the saved source", async ({ page }) => {
  const candles = readFileSync(resolve(fixtures, "core.csv"), "utf8").replace("98,100,10", "98,100,12");
  const dataset = await importFixture(page, "preset-candles.csv", "TESTUSDT", Buffer.from(candles));
  const parameterized = "tradelang 2\n" + source
    .replace("entry:", "param period: count = 2 range [1 count, 3 count]\nentry:")
    .replace("when true", "when close >= SMA(period)");
  await createStrategy(page, "Preset experiment", parameterized);
  await datasetPicker(page).selectOption(dataset);
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
  const name = page.getByRole("textbox", { name: "Preset name", exact: true });
  const menu = page.getByRole("combobox", { name: "Run preset", exact: true });
  await page.getByRole("spinbutton", { name: "Starting capital", exact: true }).fill("2000");
  await page.getByRole("spinbutton", { name: "Fee (bps per side)", exact: true }).fill("15");
  await name.fill("Core baseline");
  await page.getByRole("button", { name: "Save as preset" }).click();
  await expect(page.getByText("Run preset saved.")).toBeVisible();
  const originalPreset = await menu.inputValue();
  expect(originalPreset).not.toBe("");
  await page.getByRole("spinbutton", { name: /^period/ }).fill("1");
  await name.fill("Fast variant");
  await page.getByRole("button", { name: "Save as preset" }).click();
  await expect(page.getByText("Run preset saved.")).toBeVisible();
  await expect(menu).not.toHaveValue(originalPreset);
  await expect(datasetPicker(page)).toHaveValue(dataset);
  await expect(runButton(page)).toBeDisabled();
  const id = await submit(page);
  const run = await (await page.request.get(`/api/v1/backtests/${id}`)).json();
  expect(run.strategy_revision).toBe(2);
  expect(run.dataset_id).toBe(dataset);
  expect(run.configuration).toMatchObject({
    capital: 2000, fee_rate: 0.0015, parameters: { period: 1 },
    preset: { name: "Fast variant", revision: 1 },
    effective: { origins: { capital: "preset", "parameters.period": "preset" } },
  });
  await page.getByText("Run details", { exact: true }).click();
  await expect(page.getByText("Fast variant · revision 1", { exact: true })).toBeVisible();
});

test("save and run submit the captured source and data through concurrent edits", async ({ page }) => {
  const original = readFileSync(resolve(fixtures, "core.csv"), "utf8");
  const first = await importFixture(page, "captured-candles.csv", "TESTUSDT", Buffer.from(original.replace("98,100,10", "98,100,13")));
  const later = await importFixture(page, "next-candles.csv", "TESTUSDT", Buffer.from(original.replace("98,100,10", "98,100,14")));
  const editor = await createStrategy(page, "Capture run", source);
  const draft = "# Captured strategy\n" + source;
  const newer = "# Keep editing\n" + source;
  await datasetPicker(page).selectOption(first);
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
  const fee = page.getByRole("spinbutton", { name: "Fee (bps per side)", exact: true });
  await fee.fill("5");
  await editor.fill(draft);
  const preflight = gate();
  const save = gate();
  const validating = page.waitForRequest((request) => request.url().endsWith("/strategies/validate"));
  const saving = page.waitForRequest((request) => request.method() === "PUT" && request.url().includes("/strategies/"));
  await page.route("**/api/v1/strategies/validate", async (route) => {
    await preflight.wait;
    await route.continue();
  });
  await page.route("**/api/v1/strategies/*", async (route) => {
    if (route.request().method() === "PUT") await save.wait;
    await route.continue();
  });
  const ready = page.getByRole("button", { name: "Save and run", exact: true });
  await expect(ready).toBeEnabled();
  const submitted = page.waitForResponse((response) => response.url().endsWith("/api/v1/backtests") && response.status() === 202);
  await editor.press("Control+Alt+Enter");
  expect((await validating).postDataJSON()).toMatchObject({ source: draft, dataset_id: first, settings: { fee_bps: 5 } });
  await datasetPicker(page).selectOption(later);
  await fee.fill("15");
  preflight.open();
  expect((await saving).postDataJSON().source).toBe(draft);
  await editor.fill(newer);
  save.open();
  const run = await (await submitted).json();
  expect(run.dataset_id).toBe(first);
  expect(run.strategy_revision).toBe(3);
  expect(run.configuration.fee_rate).toBe(0.0005);
  await expect(page.getByText("Revision 3 · Unsaved changes")).toBeVisible();
  await expect(editor).toContainText("# Keep editing");
  await expect(datasetPicker(page)).toHaveValue(later);
  await expect(fee).toHaveValue("15");
  await openRunLink(page).click();
  await expect(page.getByRole("heading", { name: "Closed trades" })).toBeVisible({ timeout: 20_000 });
  const recorded = await page.request.get(`/api/v1/backtests/${run.id}/artifacts/source.trade`);
  expect(await recorded.text()).toBe(draft);
});

test("retry save and run after worker failure and a lost submission response", async ({ page }) => {
  const original = readFileSync(resolve(fixtures, "core.csv"), "utf8");
  const dataset = await importFixture(page, "retry-candles.csv", "TESTUSDT", Buffer.from(original.replace("98,100,10", "98,100,15")));
  const editor = await createStrategy(page, "Retry captured run", source);
  const draft = "# Save once\n" + source;
  await datasetPicker(page).selectOption(dataset);
  await editor.fill(draft);
  const keys: string[] = [];
  let accepted: undefined | string;
  await page.route("**/api/v1/backtests", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    keys.push((await route.request().allHeaders())["idempotency-key"]);
    if (keys.length === 1) {
      await route.fulfill({ status: 503, json: {
        error: { code: "E_WORKER", message: "The backtest worker is unavailable.", diagnostics: [] },
      } });
    } else if (keys.length === 2) {
      const answer = await route.fetch();
      expect(answer.status()).toBe(202);
      accepted = (await answer.json()).id;
      await route.abort();
    } else {
      await route.continue();
    }
  });
  const action = page.getByRole("button", { name: "Save and run", exact: true });
  await action.click();
  await expect(page.getByText("Revision 3 saved. Retry the run when ready.")).toBeVisible();
  await expect(page.getByRole("alert").getByText("The backtest worker is unavailable.")).toBeVisible();
  await expect(editor).toBeFocused();
  const retry = page.getByRole("button", { name: "Retry captured run", exact: true });
  await editor.fill("# Later work\n" + source);
  await retry.click();
  await expect(page.getByRole("alert").filter({ hasText: "The local API is unavailable." })).toBeVisible();
  await retry.click();
  await expect(page.getByRole("status").filter({ hasText: "Backtest submitted for revision 3" })).toBeVisible();
  await expect(editor).toContainText("# Later work");
  expect(keys).toHaveLength(3);
  expect(new Set(keys).size).toBe(1);
  expect(accepted).toBeDefined();
  await openRunLink(page).click();
  await expect(page).toHaveURL(new RegExp(`run=${accepted}`));
  const record = new URL(page.url()).pathname.split("/").at(-1);
  const runs = await (await page.request.get(`/api/v1/backtests?strategy_id=${record}`)).json();
  expect(runs.items.map((run: { id: string; strategy_revision: number }) => [run.id, run.strategy_revision]))
    .toEqual([[accepted, 3]]);
});

test("a stale save-and-run precondition preserves the draft and submits no run", async ({ page }) => {
  const original = readFileSync(resolve(fixtures, "core.csv"), "utf8");
  const dataset = await importFixture(page, "stale-candles.csv", "TESTUSDT", Buffer.from(original.replace("98,100,10", "98,100,16")));
  const editor = await createStrategy(page, "Conflicting combined save", source);
  const endpoint = `/api/v1${new URL(page.url()).pathname}`;
  const previous = await (await page.request.get(endpoint)).json();
  const remote = "# Concurrent revision\n" + source;
  const edited = await page.request.put(endpoint, {
    headers: { Origin: origin(), "If-Match": previous.etag },
    data: { source: remote, name: previous.name, expected_revision: previous.current_revision },
  });
  expect(edited.status()).toBe(200);
  await datasetPicker(page).selectOption(dataset);
  await editor.fill("# Keep this draft\n" + source);
  await page.getByRole("button", { name: "Save and run", exact: true }).click();
  await expect(page.getByRole("alert").getByText("The strategy changed since it was read")).toBeVisible();
  await expect(editor).toContainText("# Keep this draft");
  const runs = await (await page.request.get(`/api/v1/backtests?strategy_id=${previous.id}`)).json();
  expect(runs.items).toEqual([]);
  expect((await (await page.request.get(endpoint)).json()).current_source).toBe(remote);
});

test("import, validate, save, run, inspect, and compare real backtests", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto("/datasets");
  await page.getByRole("button", { name: "Import dataset", exact: true }).click();
  const file = page.getByLabel("File", { exact: true });
  await file.setInputFiles({ name: "invalid-candles.csv", mimeType: "text/csv", buffer: Buffer.from("invalid,columns\n1,2\n") });
  await page.getByLabel("Symbol").fill("TESTUSDT");
  await page.getByLabel("Quote currency").fill("USDT");
  await page.getByLabel("Timeframe").fill("1d");
  await page.getByRole("button", { name: "Import dataset", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("Symbol")).toHaveValue("TESTUSDT");
  await file.setInputFiles(resolve(fixtures, "core.csv"));
  await page.getByRole("button", { name: "Import dataset", exact: true }).click();
  await expect(page.getByText("Dataset imported.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "First and last candles" })).toBeVisible();

  const editor = await createStrategy(page, "Golden fixture", source);
  await page.getByRole("combobox", { name: "Dataset", exact: true }).selectOption({ label: "core.csv · TESTUSDT · 1d" });
  await page.getByRole("button", { name: "Explain strategy", exact: true }).click();
  await expect(page.getByText(/including entry fee/)).toBeVisible();
  await page.getByRole("tab", { name: "Assumptions", exact: true }).click();
  await expect(page.getByText("Retained series estimate", { exact: true })).toBeVisible();
  await expect(page.getByText("1,024.00 MiB", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Explain", exact: true }).click();
  await editor.press("ArrowUp");
  await editor.press("End");
  const selection = () => editor.evaluate(() => {
    const selected = window.getSelection();
    return [selected?.anchorNode?.parentElement?.closest(".cm-line")?.textContent, selected?.anchorOffset];
  });
  const position = await selection();
  expect(position[0]).toBeTruthy();
  const firstRun = await submit(page);
  await expect(page.getByRole("heading", { name: "Golden fixture" })).toBeFocused();
  await expect(page.locator(".metrics").getByText("1,090.91 USDT", { exact: true })).toBeVisible();
  await page.getByText("Run details", { exact: true }).click();
  await expect(page.getByText("Minimum resident storage", { exact: true })).toBeVisible();
  await expect(page.getByText("1,024.00 MiB", { exact: true })).toBeVisible();
  await page.getByText("Run details", { exact: true }).click();
  await page.getByText("Download exports", { exact: true }).click();
  const csvExport = page.getByRole("link", { name: "Full equity CSV", exact: true });
  await expect(csvExport).toHaveAttribute("href", `/api/v1/backtests/${firstRun}/artifacts/equity.csv`);
  const fullEquity = await page.request.get((await csvExport.getAttribute("href"))!);
  expect(fullEquity.ok()).toBeTruthy();
  expect((await fullEquity.text()).trim().split("\n")).toHaveLength(5);
  await page.getByText("Download exports", { exact: true }).click();
  const firstTrade = page.getByRole("button", { name: "T000001", exact: true });
  await firstTrade.click();
  await page.getByRole("combobox", { name: "Exit reason", exact: true }).selectOption("signal_exit");
  await expect(firstTrade).toHaveAttribute("aria-pressed", "true");
  const trade = page.getByRole("complementary", { name: "Trade details" });
  await expect(trade.getByText("Next bar open", { exact: true })).toBeVisible();
  await expect(trade.getByText("120.00 USDT", { exact: true }).first()).toBeVisible();
  await trade.getByText("Prices, quantity, and costs", { exact: true }).click();
  await expect(trade.getByText("110.00 USDT", { exact: true }).last()).toBeVisible();
  await trade.getByRole("button", { name: "View linked events" }).click();
  await expect(trade.getByText("Fill · Signal exit", { exact: true })).toBeVisible();
  await trade.getByRole("button", { name: "Inspect entry candle" }).click();
  const decision = page.getByRole("region", { name: "Candle decision" });
  await expect(decision.getByText("True · Order queued")).toBeVisible();
  await decision.getByText("Entry expression samples", { exact: true }).click();
  await expect(decision.getByText("entry.condition", { exact: true })).toBeVisible();
  await trade.getByRole("button", { name: "Inspect fill candle" }).click();
  await expect(decision.getByText("Cash before fill", { exact: true })).toBeVisible();
  await expect(decision.getByText("1,000.00 USDT", { exact: true }).first()).toBeVisible();
  await page.getByRole("link", { name: "Source", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(editor).toBeFocused();
  await expect(page.locator(".recharts-wrapper")).toHaveCount(0);
  expect(await selection()).toEqual(position);
  await page.goBack();
  await expect(page.getByRole("button", { name: "T000001", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.goForward();
  await expect(editor).toBeFocused();
  const backtest = page.getByRole("link", { name: "Backtest", exact: true });
  await backtest.click();
  await expect(backtest).toHaveAttribute("aria-current", "page");
  await page.reload();
  await expect(page.getByRole("heading", { name: "Closed trades" })).toBeVisible();
  await firstTrade.click();
  await page.getByRole("combobox", { name: "Exit reason", exact: true }).selectOption("stop_gap");
  await expect(page.getByText("Selection cleared after changing the exit filter.")).toBeVisible();
  await expect(trade.getByText("Select a closed trade to inspect its fills.")).toBeVisible();

  await createStrategy(page, "Zero trades", source.replace("when true", "when false"));
  await page.getByRole("combobox", { name: "Dataset", exact: true }).selectOption({ label: "core.csv · TESTUSDT · 1d" });
  const secondRun = await submit(page);
  await expect(page.getByText("No closed trades.")).toBeVisible();
  await page.getByRole("link", { name: "Runs", exact: true }).click();
  await page.getByRole("checkbox", { name: /Select Golden fixture/ }).check();
  await page.getByRole("checkbox", { name: /Select Zero trades/ }).check();
  await page.getByRole("link", { name: "Compare 2 runs" }).click();
  await expect(page.getByRole("heading", { name: "Full-run metrics" })).toBeVisible();
  await expect(page.getByText(/Exact timestamps/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Equity · Index 100" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Golden fixture · rev/ })).toHaveAttribute("href", `/runs/${firstRun}`);
  const baseline = page.getByLabel("Baseline run");
  const usedBaseline = await baseline.inputValue();
  const alternate = usedBaseline === secondRun ? firstRun : secondRun;
  let comparisonReads = 0;
  page.on("request", (request) => { if (request.url().includes("/api/v1/backtests/compare?")) comparisonReads++; });
  await baseline.selectOption(alternate);
  await expect(page).toHaveURL(new RegExp(`baseline=${alternate}`));
  await expect(page.getByRole("columnheader").nth(1)).toContainText("Baseline");
  await expect(page.getByText(alternate === firstRun ? "−9.09 pp" : "+9.09 pp", { exact: true })).toBeVisible();
  expect(comparisonReads).toBe(0);
  await page.goBack();
  await expect(baseline).toHaveValue(usedBaseline);
  await page.goForward();
  await expect(baseline).toHaveValue(alternate);
  await page.reload();
  await expect(baseline).toHaveValue(alternate);
  await page.getByRole("link", { name: "Change runs" }).click();
  await expect(page).toHaveURL(new RegExp(`baseline=${alternate}`));
  await page.getByRole("link", { name: "Compare 2 runs" }).click();
  await expect(baseline).toHaveValue(alternate);
  await page.goto("/");
  await expect(page).toHaveURL(/\/strategies$/);
  expect(pageErrors).toEqual([]);
});

test("save invalid text and reach its diagnostic with the keyboard", async ({ page }) => {
  const invalid = "# Unicode ñ ☀\n" + source.replace("when true", "when )");
  const editor = await createStrategy(page, "Invalid draft", invalid);
  await editor.focus();
  await page.keyboard.press("Control+Shift+Enter");
  await expect(page.getByText("Validation found 1 error.")).toBeVisible();
  const diagnostic = page.getByRole("button", { name: /^Line 6 ·/ });
  await diagnostic.focus();
  await page.keyboard.press("Enter");
  await expect(editor).toBeFocused();
  await expect(page.getByRole("button", { name: "Run backtest", exact: true })).toBeDisabled();
  expect(await editor.evaluate(() => window.getSelection()?.toString())).toBe(")");
  await page.keyboard.press("Control+Alt+Period");
  await expect(page.getByRole("button", { name: "Hide dock" })).toBeFocused();
  const problems = page.getByRole("tab", { name: /^Problems/ });
  await problems.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Runs", exact: true })).toBeFocused();
  await expect(page.getByRole("tab", { name: "Runs", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.reload();
  await expect(page.getByRole("textbox", { name: "Strategy source" })).toContainText("when )");
});

test("recover errors and apply a casing fix to the exact draft", async ({ page }) => {
  const broken = ("# Café 🧪\n" + source
    .replace("entry:", "let avg = ema(2)\nlet period = SMA(0)\nentry:")
    .replace("when true", "when close > avg")).replaceAll("\n", "\r\n");
  const created = await page.request.post("/api/v1/strategies", {
    headers: { Origin: origin() },
    data: { name: "Draft checks", source: "\ufeff" + broken },
  });
  expect(created.status()).toBe(201);
  const id = (await created.json()).id;
  await page.goto(`/strategies/${id}`);
  const editor = page.getByRole("textbox", { name: "Strategy source" });
  await expect(page.getByRole("tab", { name: "Problems · 2" })).toBeVisible();
  await expect(page.getByText("error · E202_PERIOD")).toBeVisible();
  const apply = page.getByRole("button", { name: "Apply fix to line 5" });
  await apply.focus();
  await page.keyboard.press("Enter");
  await expect(editor).toBeFocused();
  await expect(editor).toContainText("let avg = EMA(2)");
  await expect(page.getByText("error · E101_SYNTAX")).toHaveCount(0);
  await expect(runButton(page)).toBeDisabled();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Revision saved.")).toBeVisible();
  const saved = await (await page.request.get(`/api/v1/strategies/${id}`)).json();
  expect(saved.current_source).toBe("\ufeff" + broken.replace("ema(2)", "EMA(2)"));
});

test("complete a record alias and show the active nested function signature", async ({ page }) => {
  const editor = await createStrategy(page, "Record completion", "tradelang 2\n" + source
    .replace("entry:", "let result = MACD(2, 3, 2)\nlet alias = result\nentry:")
    .replace("when true", "when alias.line > alias.signal"));
  const lint = page.waitForResponse((response) => response.url().endsWith("/strategies/draft-check") &&
    response.request().postDataJSON().source.endsWith("alias."));
  await editor.fill("tradelang 2\nstrategy \"Record completion\"\nlet result = MACD(2, 3, 2)\nlet alias = result\nentry:\n  when alias.");
  expect((await (await lint).json()).records).toHaveLength(2);
  await editor.press("Control+End");
  await editor.press("Control+Space");
  const fields = page.getByRole("listbox");
  await expect(fields.getByRole("option")).toHaveCount(3);
  await expect(fields.getByRole("option", { name: "signal", exact: true })).toBeVisible();
  // CodeMirror's completion keymap ignores input for 75 ms after opening.
  await page.waitForTimeout(100);
  await editor.press("Enter");
  await expect(editor).toContainText(/when alias\.(line|histogram|signal)/);
  await editor.fill("tradelang 2\nstrategy \"Nested signature\"\nentry:\n  when available(MACD(2, ");
  await editor.press("Control+End");
  const hint = page.getByRole("note", { name: "Function signature" });
  await expect(hint).toContainText("MACD(fast, slow, signal)");
  await expect(hint).toContainText("slow · 1–10,000 bars");
  await expect(hint).toContainText("source defaults to close");
  await editor.fill("tradelang 2\nstrategy \"Nested record\"\nentry:\n  when MACD((2 + 0), 3, 2).");
  await editor.press("Control+End");
  await editor.press("Control+Space");
  await expect(fields.getByRole("option")).toHaveCount(3);
  await expect(fields.getByRole("option", { name: "histogram", exact: true })).toBeVisible();
});

test("ignore an earlier draft check when the source changes", async ({ page }) => {
  const pending = gate();
  const stale = "let invalid = SMA(0)";
  await page.route("**/api/v1/strategies/draft-check", async (route) => {
    if (route.request().postData()?.includes(stale)) {
      const response = await route.fetch();
      await pending.wait;
      await route.fulfill({ response }).catch(() => {});
    } else await route.continue();
  });
  const editor = await createStrategy(page, "Draft response race", source);
  const requested = page.waitForRequest((request) => request.url().endsWith("/draft-check") &&
    Boolean(request.postData()?.includes(stale)));
  await editor.fill(source.replace("entry:", stale + "\nentry:"));
  await requested;
  const fresh = source.replace("when true", "when clsoe > 0");
  const response = page.waitForResponse((item) => item.url().endsWith("/draft-check") &&
    item.request().postDataJSON().source === fresh);
  await editor.fill(fresh);
  await response;
  await expect(page.getByText("error · E102_UNKNOWN_NAME")).toBeVisible();
  pending.open();
  await expect(page.getByText("error · E202_PERIOD")).toHaveCount(0);
  await expect(page.getByText("error · E102_UNKNOWN_NAME")).toBeVisible();
  await expect(runButton(page)).toBeDisabled();
});

test("recover dirty drafts, edits during Save, and stale revision conflicts", async ({ page }) => {
  const editor = await createStrategy(page, "Draft recovery", source);
  const strategyPath = new URL(page.url()).pathname;
  const requestPath = "/api/v1" + strategyPath;
  const routePattern = "**" + requestPath;
  const base = await (await page.request.get(requestPath)).json();
  const savedWhileEditing = source + "# snapshot saved during a later edit\n";
  const stillEditing = savedWhileEditing + "# newer local edit\n";
  const held = gate();
  const saveArrived = gate();
  const delayedSave = async (route: Route) => {
    if (route.request().method() !== "PUT") return route.continue();
    saveArrived.open();
    await held.wait;
    await route.continue();
  };
  await page.route(routePattern, delayedSave);
  await editor.fill(savedWhileEditing);
  await editor.press("Meta+s");
  await saveArrived.wait;
  await editor.fill(stillEditing);
  held.open();
  await expect(page.getByText("Revision saved. New edits are unsaved.")).toBeVisible();
  await page.unroute(routePattern, delayedSave);
  await page.reload();
  await expect(page.getByRole("region", { name: "Recovered draft" })).toBeVisible();
  await page.getByRole("button", { name: "Restore draft" }).click();
  await expect(editor).toContainText("# newer local edit");
  await expect(editor).toBeFocused();
  const updated = await (await page.request.get(requestPath)).json();
  expect(updated.current_source).toBe(savedWhileEditing);
  expect(updated.current_revision).toBe(base.current_revision + 1);

  const remote = source + "# saved in another tab\n";
  const competing = await page.request.put(requestPath, {
    headers: { Origin: origin(), "If-Match": updated.etag },
    data: { name: updated.name, source: remote, expected_revision: updated.current_revision },
  });
  expect(competing.ok()).toBeTruthy();
  await editor.press("Control+s");
  await expect(page.getByRole("button", { name: "Keep local source and load latest revision" })).toBeVisible();
  await expect(editor).toContainText("# newer local edit");
  await page.reload();
  await expect(page.getByText(/saved revision changed since this draft/)).toBeVisible();
  await page.getByText("Review recovered source", { exact: true }).click();
  await expect(page.getByRole("region", { name: "Recovered draft" })).toContainText("# newer local edit");
  await page.getByRole("button", { name: "Discard draft" }).click();
  await expect(editor).toContainText("# saved in another tab");
  await page.reload();
  await expect(editor).toContainText("# saved in another tab");
  await expect(page.getByRole("region", { name: "Recovered draft" })).toHaveCount(0);
});

test("superseded validation cannot arm Run for another dataset or draft", async ({ page }) => {
  const first = await importFixture(page, "first.csv");
  const second = await importFixture(page, "second.csv", "OTHERUSDT");
  const editor = await createStrategy(page, "Validation identity", source);
  const release = gate();
  const responded = gate();
  let requestCount = 0;
  await page.route("**/api/v1/strategies/validate", async (route) => {
    requestCount++;
    if (requestCount !== 1) return route.continue();
    const response = await route.fetch();
    expect((await response.json()).data_compatible).toBe(true);
    responded.open();
    await release.wait;
    await route.fulfill({ response }).catch(() => {});
  });
  await datasetPicker(page).selectOption(first);
  await editor.press("Control+Shift+Enter");
  await responded.wait;
  await datasetPicker(page).selectOption(second);
  release.open();
  await expect(runButton(page)).toBeDisabled();
  await editor.press("Control+Shift+Enter");
  await expect(page.getByText(/Validated with second.csv/)).toBeVisible();
  await expect(runButton(page)).toBeDisabled();
  await datasetPicker(page).selectOption(first);
  await editor.press("Meta+Shift+Enter");
  await expect(runButton(page)).toBeEnabled();
  await editor.press("End");
  await editor.press("Space");
  await expect(runButton(page)).toBeDisabled();
});

test("retry an unacknowledged submission and share status with the collapsed dock", async ({ page }) => {
  const dataset = await importFixture(page, "retry.csv");
  const editor = await createStrategy(page, "Retry terminal", source);
  await datasetPicker(page).selectOption(dataset);
  await page.getByRole("button", { name: "Hide dock" }).click();
  await editor.press("Meta+Shift+Enter");
  await expect(runButton(page)).toBeEnabled();
  const posts: string[] = [];
  let id = "";
  let reads = 0;
  const sent = gate();
  const release = gate();
  await page.route("**/api/v1/backtests", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    posts.push(route.request().headers()["idempotency-key"]);
    const response = await route.fetch();
    expect(response.status()).toBe(202);
    const run = await response.json();
    if (posts.length === 1) {
      id = run.id;
      sent.open();
      await release.wait;
      await route.abort("connectionreset");
    } else {
      expect(run.id).toBe(id);
      await route.fulfill({ response, json: { ...run, status: "queued", summary: null } });
    }
  });
  await page.route("**/api/v1/backtests/*", async (route) => {
    if (new URL(route.request().url()).pathname !== `/api/v1/backtests/${id}`) return route.continue();
    reads++;
    if (reads === 1) return route.fulfill({ status: 503 });
    await route.continue();
  });
  await editor.press("Meta+Enter");
  await sent.wait;
  await editor.press("Meta+Enter");
  release.open();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("The local API is unavailable");
  await page.reload();
  await datasetPicker(page).selectOption(dataset);
  await editor.press("Meta+Shift+Enter");
  await expect(runButton(page)).toBeEnabled();
  await editor.press("Meta+Enter");
  await expect(openRunLink(page)).toBeVisible();
  expect(posts).toHaveLength(2);
  expect(posts[0]).toHaveLength(36);
  expect(posts[0]).toBe(posts[1]);
  await openRunLink(page).click();
  await expect(page.getByText("Showing the last known run status.")).toBeVisible();
  await expect.poll(async () => {
    const response = await page.request.get(`/api/v1/backtests/${id}`);
    return (await response.json()).status;
  }, { timeout: 20_000 }).toBe("succeeded");
  expect(reads).toBe(1);
  await page.getByRole("button", { name: "Retry status" }).click();
  await expect(page.getByRole("heading", { name: "Closed trades" })).toBeVisible({ timeout: 20_000 });
  await sourceView(page).click();
  await expect(editor).toBeFocused();
  await expect(page.getByText("Succeeded", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Show dock" })).toBeVisible();
  expect(reads).toBe(2);
});

test("keep display preferences and recover invalid or mismatched workspace links", async ({ page }) => {
  const editor = await createStrategy(page, "Workspace routing", source);
  const route = new URL(page.url()).pathname;
  const dataset = await importFixture(page, "workspace.csv");
  await datasetPicker(page).selectOption(dataset);
  const id = await submit(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByLabel("Theme").selectOption("light");
  await page.getByRole("button", { name: "Collapse navigation labels" }).click();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.getByRole("button", { name: "Expand navigation labels" })).toBeVisible();
  await page.goto(route + "?run=bad-id");
  await expect(page.getByRole("heading", { name: "Run link is invalid" })).toBeVisible();
  await page.getByRole("link", { name: "Return to source" }).click();
  await expect(editor).toBeVisible();
  await createStrategy(page, "Other workspace", source);
  await page.goto(new URL(page.url()).pathname + "?run=" + id);
  await expect(page.getByRole("heading", { name: "This run belongs to another strategy" })).toBeVisible();
  await page.getByRole("link", { name: "Open standalone run" }).click();
  await expect(page).toHaveURL(new RegExp("/runs/" + id + "$"));
  await page.getByRole("link", { name: "View strategy" }).click();
  await expect(page.getByText(/Read-only/)).toBeVisible();
  await expect(page.locator(".cm-content")).toHaveAttribute("aria-readonly", "true");
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Strategies" }).first()).toBeVisible();
});

test("compare full-run deltas pairwise across overlapping and incompatible runs", async ({ page }) => {
  const primary = await importFixture(page, "comparison.csv");
  const alternate = await importFixture(page, "comparison-alt.csv", "ALTUSDT");
  async function start(name: string, text: string, dataset_id = primary) {
    const created = await page.request.post("/api/v1/strategies", {
      headers: { Origin: origin() }, data: { name, source: text },
    });
    expect(created.status()).toBe(201);
    const strategy = await created.json();
    const run = await page.request.post("/api/v1/backtests", {
      headers: { Origin: origin() },
      data: { dataset_id, strategy_id: strategy.id, strategy_revision: strategy.current_revision },
    });
    expect(run.status()).toBe(202);
    return (await run.json()).id as string;
  }
  const baseline = await start("Full window", source);
  const capital = await start("Different capital", source.replace("1000 USDT", "1500 USDT")
    .replace("fee 0 bps", "fee 10 bps"));
  const short = await start("Short window", source.replace("to 2024-01-03", "to 2024-01-02"));
  const incompatible = await start("Incompatible market", source.replace("market TESTUSDT", "market ALTUSDT"), alternate);
  for (const id of [baseline, capital, short, incompatible]) {
    await expect.poll(async () => {
      const response = await page.request.get("/api/v1/backtests/" + id);
      return (await response.json()).status;
    }, { timeout: 15_000 }).toBe("succeeded");
  }

  await page.goto(`/compare?ids=${capital},${short},${baseline}&baseline=${baseline}`);
  const metrics = page.getByRole("region", { name: "Headline metrics" });
  await expect(metrics.getByRole("columnheader").nth(1)).toContainText("Full window");
  await expect(page.getByText(/Common timestamps only/)).toBeVisible();
  await expect(metrics.getByRole("row", { name: /^Total return/ }).getByRole("cell").nth(1)).toContainText("−0.22 pp");
  await expect(metrics.getByRole("row", { name: /^Final equity/ }).getByRole("cell").nth(1)).toContainText("Starting capital differs.");
  await expect(metrics.getByRole("row", { name: /^Total return/ }).getByRole("cell").nth(2)).toContainText("Full-run windows differ.");
  await expect(page.getByRole("heading", { name: "Equity · Index 100" })).toBeVisible();

  await page.goto(`/compare?ids=${capital},${incompatible},${short},${baseline}&baseline=${baseline}`);
  await expect(page.getByText("Overlay unavailable", { exact: true })).toBeVisible();
  await expect(metrics.getByRole("row", { name: /^Total return/ }).getByRole("cell").nth(1)).toContainText("−0.22 pp");
  await expect(metrics.getByRole("row", { name: /^Total return/ }).getByRole("cell").nth(2)).toContainText("Market differs.");
  await expect(page.getByRole("heading", { name: "Equity · Index 100" })).toHaveCount(0);
  const common = page.getByRole("region", { name: "Common-start benchmark" });
  await expect(common.getByRole("heading", { name: "Equity · Common-window index" })).toBeVisible();
  const returns = common.getByRole("region", { name: "Common-window returns" });
  await expect(returns.getByRole("row", { name: /Buy-and-hold reference/ })).toContainText("1.82%");
  await expect(returns.getByRole("row", { name: /Short window/ })).toBeVisible();
  await expect(returns.getByRole("row", { name: /Incompatible market/ })).toHaveCount(0);
  await expect(common.getByText(/Fee or slippage rates differ/).first()).toBeVisible();
  await common.getByText("View common-window chart data").click();
  await expect(common.getByRole("region", { name: "Common-window chart data" }).getByRole("row").nth(1))
    .toContainText("initial");
  await page.getByRole("link", { name: "Change runs" }).click();
  await page.getByRole("button", { name: "Remove Full window" }).click();
  await page.getByRole("link", { name: "Compare 3 runs" }).click();
  await expect(page.getByLabel("Baseline run")).toHaveValue(capital);
  expect(new URL(page.url()).searchParams.has("baseline")).toBe(false);
});

test("reflow long strategy and dataset labels with no horizontal page scrolling", async ({ page }) => {
  const dataset = await importFixture(page, "hourly-sample-".repeat(10) + ".csv", "LONGUSDT");
  const editor = await createStrategy(page, "Long strategy " + "unbrokenname".repeat(8), source);
  await datasetPicker(page).selectOption(dataset);
  for (const width of [1440, 1280, 1024, 390, 720]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await expect(editor).toBeVisible();
    await expect(runButton(page)).toBeVisible();
    await expect(page.getByRole("tab", { name: "Problems" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBe(0);
  }
  await page.getByText("Data", { exact: true }).click();
  await expect(page.getByText(/hourly-sample-hourly-sample-/).last()).toBeVisible();
});

test("changing the lower-timeframe dataset invalidates pending Volume Profile inspection", async ({ page }) => {
  const candles = (hours: number[], prices: number[], weights: number[]) => Buffer.from(
    "timestamp,open,high,low,close,volume\n" +
    hours.map((hour, index) => {
      const value = prices[index];
      return `2024-01-01T${String(hour).padStart(2, "0")}:00:00Z,${value},${value},${value},${value},${weights[index]}`;
    }).join("\n") + "\n",
  );
  const parent = candles([0, 8, 16], [102, 110, 109], [9, 3, 4]);
  const lower = candles([0, 4, 8, 12, 16, 20], [100.2, 101.2, 100.9, 102.2, 104.2, 106.2], [3, 6, 0, 3, 2, 2]);
  const primary = await importFixture(page, "parent-8h.csv", "PROFILEUSDT", parent, "8h");
  const profile = await importFixture(page, "profile-4h.csv", "PROFILEUSDT", lower, "4h");
  const badProfile = await importFixture(page, "profile-other-market.csv", "OTHERPROFILEUSDT", lower, "4h");
  const strategy = source.replace("market TESTUSDT", "market PROFILEUSDT").replace("timeframe 1d", "timeframe 8h")
    .replace("entry:\n  when true", "let point = VPROFILE(2, 1 price, 0.7).poc\nentry:\n  when close > point")
    .replace("to 2024-01-03", "to 2024-01-01");
  const editor = await createStrategy(page, "Volume Profile identity", strategy);
  const profilePicker = page.getByRole("combobox", { name: "Volume Profile dataset" });
  await datasetPicker(page).selectOption(primary);
  await profilePicker.selectOption(profile);
  const responded = gate();
  const release = gate();
  let validateCount = 0;
  await page.route("**/api/v1/strategies/validate", async (route) => {
    validateCount++;
    if (validateCount !== 1) return route.continue();
    expect(route.request().postDataJSON().profile_dataset_id).toBe(profile);
    const response = await route.fetch();
    expect((await response.json()).data_compatible).toBe(true);
    responded.open();
    await release.wait;
    await route.fulfill({ response }).catch(() => {});
  });
  await editor.press("Control+Shift+Enter");
  await responded.wait;
  await profilePicker.selectOption(badProfile);
  release.open();
  await expect(runButton(page)).toBeDisabled();
  await editor.press("Control+Shift+Enter");
  await expect(page.getByText("Validated with parent-8h.csv + profile-other-market.csv")).toBeVisible();
  await expect(runButton(page)).toBeDisabled();
  await profilePicker.selectOption(profile);
  await editor.press("Control+Shift+Enter");
  await expect(runButton(page)).toBeEnabled();
});

test("duplicate, archive, and reopen a saved strategy revision", async ({ page }) => {
  await createStrategy(page, "Archive candidate", source);
  const sourcePath = new URL(page.url()).pathname;
  await page.goto("/strategies");
  await page.getByRole("button", { name: "Archive candidate", exact: true }).click();
  await page.getByRole("button", { name: "Duplicate" }).click();
  await expect(page.getByRole("heading", { name: "Archive candidate copy" })).toBeVisible();
  await expect(page.getByText("Revision 1 · Saved", { exact: true })).toBeVisible();

  await page.goto("/strategies");
  await page.getByRole("button", { name: "Archive candidate", exact: true }).click();
  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: "Archive", exact: true }).click();
  await expect(page.getByRole("button", { name: "Archive candidate", exact: true })).toHaveCount(0);
  await page.goto(sourcePath);
  await expect(page.getByRole("heading", { name: "Strategy unavailable" })).toBeVisible();
  await page.goto(sourcePath + "/revisions/2");
  await expect(page.getByText(/Read-only/)).toBeVisible();
  await expect(page.locator(".cm-content")).toContainText("Golden next-open ledger");
});

test("run MACD variants, inspect decisions, compare warmups, and replay the selected bundle", async ({ page }) => {
  const fixture = readFileSync(resolve(fixtures, "macd-v2.trade"), "utf8");
  const csv = readFileSync(resolve(fixtures, "macd-v2.csv"));
  const dataset = await importFixture(page, "macd-reference.csv", "TESTUSDT", csv);
  await createStrategy(page, "MACD reference workflow", fixture);
  await datasetPicker(page).selectOption(dataset);
  await page.getByRole("button", { name: "Explain strategy", exact: true }).click();
  await expect(page.getByText("Explanation ready.")).toBeVisible();
  await page.getByText("Source and dataset details", { exact: true }).click();
  await expect(page.getByText(/macd field readiness · line at 2, signal at 3/)).toBeVisible();
  const baseline = await submit(page);
  await sourceView(page).click();
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
  await page.getByRole("spinbutton", { name: /^slow/ }).fill("4");
  await page.getByRole("spinbutton", { name: "Fee (bps per side)", exact: true }).fill("0");
  const variant = await submit(page);

  const url = `/api/v1/backtests/${variant}`;
  const quiet = await (await page.request.get(`${url}/bars/6`)).json();
  const signal = await (await page.request.get(`${url}/bars/7`)).json();
  const filled = await (await page.request.get(`${url}/bars/8`)).json();
  expect(quiet.entry.outcome).toBe("false");
  expect(signal.entry.outcome).toBe("order_queued");
  expect(filled.events.find((event: { kind: string }) => event.kind === "fill").data.fill_price).toBe(21);
  const manifest = await (await page.request.get(`${url}/artifacts/manifest.json`)).json();
  expect(manifest.parameter_overrides).toEqual({ slow: 4 });
  await page.goto(`/compare?ids=${baseline},${variant}`);
  await expect(page.getByRole("region", { name: "Common-start benchmark" })
    .getByRole("heading", { name: "Equity · Common-window index" })).toBeVisible();
  const comparison = await (await page.request.get(`/api/v1/backtests/compare?ids=${baseline},${variant}`)).json();
  expect(comparison.runs.map((run: { benchmark_entry_at: string }) => run.benchmark_entry_at))
    .toEqual(["2024-01-06T00:00:00Z", "2024-01-07T00:00:00Z"]);
  expect(comparison.common_benchmark.cohorts[0].start_at).toBe("2024-01-07T00:00:00Z");

  const library = process.env.TRADELANG_TEST_LIBRARY;
  if (!library) throw new Error("The isolated library is unavailable");
  const bundle = resolve(library, "runs", variant);
  const temporary = await mkdtemp(resolve(tmpdir(), "tradelang-macd-replay-"));
  try {
    const { stdout } = await exec("tradelang", [
      "backtest", resolve(bundle, "source.trade"),
      "--run-config", resolve(bundle, "run-config.json"),
      "--out", resolve(temporary, "replay"), "--json",
    ], { timeout: 15_000 });
    const replay = JSON.parse(stdout).result;
    expect(replay.run_fingerprint).toBe(manifest.run_fingerprint);
    expect(replay.result_digest).toBe(manifest.result_digest);
  } finally {
    await rm(temporary, { recursive: true });
  }
});

test("bind a higher-timeframe feed and replay its primary fills through the CLI", async ({ page }) => {
  const directory = resolve(fixtures, "feeds");
  const primary = resolve(directory, "primary.csv");
  const higher = resolve(directory, "trend.csv");
  const feedSource = readFileSync(resolve(directory, "trend.trade"), "utf8");
  const data = await importFixture(page, "trend-primary.csv", "TESTUSDT", readFileSync(primary), "1h");
  const trend = await importFixture(page, "trend-candles.csv", "TESTUSDT", readFileSync(higher), "4h");
  const wrongMarket = await importFixture(page, "trend-wrong.csv", "OTHERUSDT", readFileSync(higher), "4h");
  await createStrategy(page, "Named higher timeframe", feedSource);
  await datasetPicker(page).selectOption(data);
  const selector = page.getByRole("combobox", { name: "Feed trend", exact: true });
  await expect(selector).toBeVisible();
  await selector.selectOption(wrongMarket);
  await page.getByRole("button", { name: "Validate", exact: true }).click();
  await expect(page.getByText(/Feed trend must match the primary dataset's symbol/)).toBeVisible();
  await expect(runButton(page)).toBeDisabled();
  await selector.selectOption(trend);
  const id = await submit(page);
  const url = `/api/v1/backtests/${id}`;
  const before = await (await page.request.get(`${url}/bars/6`)).json();
  expect(before.entry.outcome).toBe("unavailable");
  expect(before.entry.expression.samples.some((sample: { unavailable_reason?: string }) =>
    sample.unavailable_reason === "feed_insufficient_history")).toBe(true);
  const after = await (await page.request.get(`${url}/bars/7`)).json();
  expect(after.entry.outcome).toBe("order_queued");
  expect(after.entry.expression.samples).toEqual(expect.arrayContaining([
    expect.objectContaining({ feed: "trend", clock: "trend", value: 105, observed_at: "2024-01-01T08:00:00Z" }),
  ]));
  const manifest = await (await page.request.get(`${url}/artifacts/manifest.json`)).json();
  expect(manifest.schema_version).toBe(4);
  expect(manifest.feed_inputs[0]).toMatchObject({ name: "trend", policy: "completed_close_v1" });
  await page.getByText("Run details", { exact: true }).click();
  await expect(page.getByText(/trend · 14400s/)).toBeVisible();
  await page.getByText("Download exports", { exact: true }).click();
  await expect(page.getByRole("link", { name: "Replay configuration" })).toHaveAttribute(
    "href", `${url}/artifacts/run-config.json`,
  );

  const library = process.env.TRADELANG_TEST_LIBRARY;
  if (!library) throw new Error("The isolated library is unavailable");
  const bundle = resolve(library, "runs", id);
  const temporary = await mkdtemp(resolve(tmpdir(), "tradelang-feed-replay-"));
  try {
    for (const [output, overrides] of [
      ["bundled", []],
      ["equivalent-csv", ["--data", primary, "--feed", `trend=${higher}`]],
    ] as const) {
      const { stdout } = await exec("tradelang", [
        "backtest", resolve(bundle, "source.trade"), "--run-config", resolve(bundle, "run-config.json"),
        ...overrides, "--out", resolve(temporary, output), "--json",
      ], { timeout: 15_000 });
      const replay = JSON.parse(stdout).result;
      expect(replay.run_fingerprint).toBe(manifest.run_fingerprint);
      expect(replay.result_digest).toBe(manifest.result_digest);
    }
  } finally {
    await rm(temporary, { recursive: true });
  }

  await createStrategy(page, "Shorter feed max age", feedSource.replace("max_age 8h", "max_age 3h"));
  await datasetPicker(page).selectOption(data);
  await selector.selectOption(trend);
  const variant = await submit(page);
  await page.goto(`/compare?ids=${id},${variant}`);
  await page.getByText("Run inputs", { exact: true }).click();
  const feedRow = page.getByRole("row").filter({ hasText: "Higher-timeframe feeds" });
  await expect(feedRow).toContainText("max age 28800s · completed_close_v1");
  await expect(feedRow).toContainText("max age 10800s · completed_close_v1");
});

test("audit a stop-sized entry and replay its allocation override", async ({ page }) => {
  const fixture = resolve(fixtures, "risk-sizing", "stop-risk.trade");
  const candles = readFileSync(resolve(fixtures, "risk-sizing", "stop-risk.csv"));
  const dataset = await importFixture(page, "stop-risk.csv", "TESTUSDT", candles);
  await createStrategy(page, "Stop risk reference", readFileSync(fixture, "utf8"));
  await datasetPicker(page).selectOption(dataset);
  await page.getByRole("button", { name: "Explain strategy", exact: true }).click();
  await expect(page.getByText("Explanation ready.")).toBeVisible();
  await page.getByText("Source and dataset details", { exact: true }).click();
  await expect(page.getByText(/An opening gap can exceed the modeled loss/)).toBeVisible();
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
  await page.getByRole("spinbutton", { name: /^allocation_limit/ }).fill("0.15");
  const id = await submit(page);
  const url = `/api/v1/backtests/${id}`;
  const result = await (await page.request.get(`${url}/bars/1`)).json();
  expect(result.entry_fill.allocation_expression.value).toBe(0.15);
  expect(result.risk_sizing).toMatchObject({
    entry_open: 100, entry_fill_price: 101, risk_budget: 20,
    binding_constraint: "allocation", allocation_limit: 150,
  });
  expect(result.risk_sizing.quantity).toBeCloseTo(150 / 102.01, 10);
  expect(result.risk_sizing.loss_per_unit).toBeCloseTo(12.91891, 8);
  expect(result.risk_sizing.modeled_loss).toBeLessThan(20);
  await page.getByRole("button", { name: "T000001", exact: true }).click();
  await page.getByRole("button", { name: "Inspect fill candle" }).click();
  const decision = page.getByRole("region", { name: "Candle decision" });
  await decision.getByText("Stop-based sizing", { exact: true }).click();
  await expect(decision.getByText("Binding constraint", { exact: true })).toBeVisible();
  await expect(decision.getByText("Allocation", { exact: true })).toBeVisible();
  await expect(decision.getByText("12.91891", { exact: true })).toBeVisible();
  await page.getByText("Download exports", { exact: true }).click();
  await expect(page.getByRole("link", { name: "Replay configuration" })).toHaveAttribute(
    "href", `${url}/artifacts/run-config.json`,
  );
  const manifest = await (await page.request.get(`${url}/artifacts/manifest.json`)).json();
  expect(manifest).toMatchObject({
    dsl_version: 4, semantics_version: "4.0.0", parameter_overrides: { allocation_limit: 0.15 },
  });

  const library = process.env.TRADELANG_TEST_LIBRARY;
  if (!library) throw new Error("The isolated library is unavailable");
  const bundle = resolve(library, "runs", id);
  const temporary = await mkdtemp(resolve(tmpdir(), "tradelang-risk-replay-"));
  try {
    const { stdout } = await exec("tradelang", [
      "backtest", resolve(bundle, "source.trade"), "--run-config", resolve(bundle, "run-config.json"),
      "--out", resolve(temporary, "replay"), "--json",
    ], { timeout: 15_000 });
    const replay = JSON.parse(stdout).result;
    expect(replay.run_fingerprint).toBe(manifest.run_fingerprint);
    expect(replay.result_digest).toBe(manifest.result_digest);
  } finally {
    await rm(temporary, { recursive: true });
  }
});

test("inspect and replay a timed exit with a next-open trail activation", async ({ page }) => {
  const directory = resolve(fixtures, "ordered-exits");
  const candles = readFileSync(resolve(directory, "ordered.csv"));
  const dataset = await importFixture(page, "ordered-exits.csv", "TESTUSDT", candles);
  await createStrategy(page, "Ordered exits reference", readFileSync(resolve(directory, "ordered.trade"), "utf8"));
  await datasetPicker(page).selectOption(dataset);
  await page.getByRole("button", { name: "Explain strategy", exact: true }).click();
  await expect(page.getByText("Explanation ready.")).toBeVisible();
  await page.getByText("Source and dataset details", { exact: true }).click();
  await expect(page.getByText(/first true rule in source order/)).toBeVisible();
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
  await page.getByRole("spinbutton", { name: /^hold_bars/ }).fill("1");
  const id = await submit(page);
  const url = `/api/v1/backtests/${id}`;
  const signal = await (await page.request.get(`${url}/bars/1`)).json();
  expect(signal.holding_closes).toBe(1);
  expect(signal.exit.outcome).toBe("order_queued");
  expect(signal.exit_rules.map((rule: { name: string; outcome: string }) => [rule.name, rule.outcome])).toEqual([
    ["slow_confirmation", "unavailable"], ["profit", "false"], ["timeout", "selected"],
  ]);
  expect(signal.trail_updates[0]).toMatchObject({ trigger_price: 110, effective_open_at: null });
  const opened = await (await page.request.get(`${url}/bars/2`)).json();
  expect(opened.trail_updates[0].effective_open_at).toBe("2024-01-03T00:00:00Z");
  expect(opened.events.map((event: { kind: string }) => event.kind)).toEqual(["trail_activated", "fill"]);
  expect(opened.events[1].data).toMatchObject({ fill_price: 114, trace: { exit_rule: { name: "timeout" } } });

  await page.getByRole("button", { name: "T000001", exact: true }).click();
  await expect(page.getByRole("complementary", { name: "Trade details" }).getByText("timeout", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Inspect fill candle" }).click();
  const decision = page.getByRole("region", { name: "Candle decision" });
  await decision.getByText("Ordered exit rules", { exact: true }).click();
  await expect(decision.getByText("timeout · Triggered exit", { exact: true })).toBeVisible();
  await decision.getByText("Trailing stop changes", { exact: true }).click();
  await expect(decision.getByText("Queued for next open", { exact: true })).toBeVisible();
  const manifest = await (await page.request.get(`${url}/artifacts/manifest.json`)).json();
  expect(manifest).toMatchObject({
    dsl_version: 5, semantics_version: "5.0.0", decision_inspection: { schema_version: 2 },
  });
  const library = process.env.TRADELANG_TEST_LIBRARY;
  if (!library) throw new Error("The isolated library is unavailable");
  const bundle = resolve(library, "runs", id);
  const temporary = await mkdtemp(resolve(tmpdir(), "tradelang-ordered-replay-"));
  try {
    const { stdout } = await exec("tradelang", [
      "backtest", resolve(bundle, "source.trade"), "--run-config", resolve(bundle, "run-config.json"),
      "--out", resolve(temporary, "replay"), "--json",
    ], { timeout: 15_000 });
    const replay = JSON.parse(stdout).result;
    expect(replay.run_fingerprint).toBe(manifest.run_fingerprint);
    expect(replay.result_digest).toBe(manifest.result_digest);
  } finally {
    await rm(temporary, { recursive: true });
  }
});

test("reconcile open and closed position fill ledgers and replay the full cycle", async ({ page }) => {
  test.slow();
  const directory = resolve(fixtures, "position-ledger");
  const strategy = readFileSync(resolve(directory, "position.trade"), "utf8");
  const dataset = await importFixture(page, "position-ledger.csv", "TESTUSDT", readFileSync(resolve(directory, "position.csv")));
  await createStrategy(page, "Position cycle reference", strategy);
  await datasetPicker(page).selectOption(dataset);
  await page.getByRole("button", { name: "Run settings", exact: true }).click();
  await page.getByRole("spinbutton", { name: /^first_fraction/ }).fill("0.25");
  const id = await submit(page);
  const url = `/api/v1/backtests/${id}`;
  const run = await (await page.request.get(url)).json();
  expect(run.summary.final_equity).toBeCloseTo(2101.225, 10);
  expect(run.summary.metrics.closed_trades).toBe(1);
  expect(run.summary.position_accounting.fill_count).toBe(5);
  const sale = await (await page.request.get(`${url}/bars/1`)).json();
  expect(sale.exit_rules[0].sale_expression.value).toBe(0.25);
  await page.getByRole("button", { name: "T000001", exact: true }).click();
  const closed = page.getByRole("complementary", { name: "Trade details" });
  await closed.getByText("Position fill ledger", { exact: true }).click();
  const ledger = closed.getByRole("table", { name: "Position fills" });
  const added = ledger.getByRole("row").filter({ hasText: "F00000004" });
  await expect(added).toContainText("Scale in");
  await expect(added).toContainText("700.00 USDT");
  await expect(added).toContainText("1,361.20 USDT");
  await expect(ledger.getByRole("row")).toHaveCount(6);
  const manifest = await (await page.request.get(`${url}/artifacts/manifest.json`)).json();
  expect(manifest).toMatchObject({ semantics_version: "6.0.0", position_ledger: { artifact: "events.jsonl" } });
  const library = process.env.TRADELANG_TEST_LIBRARY;
  if (!library) throw new Error("The isolated library is unavailable");
  const bundle = resolve(library, "runs", id);
  const temporary = await mkdtemp(resolve(tmpdir(), "tradelang-position-replay-"));
  try {
    const { stdout } = await exec("tradelang", [
      "backtest", resolve(bundle, "source.trade"), "--run-config", resolve(bundle, "run-config.json"),
      "--out", resolve(temporary, "replay"), "--json",
    ], { timeout: 15_000 });
    const replay = JSON.parse(stdout).result;
    expect(replay.run_fingerprint).toBe(manifest.run_fingerprint);
    expect(replay.result_digest).toBe(manifest.result_digest);
  } finally {
    await rm(temporary, { recursive: true });
  }
  await createStrategy(page, "Open after two trims", strategy.replace("to 2024-01-06", "to 2024-01-04"));
  await datasetPicker(page).selectOption(dataset);
  await submit(page);
  await page.getByRole("button", { name: "View open position", exact: true }).click();
  const open = page.getByRole("complementary", { name: "Open position" });
  await expect(open.getByText("68.20 USDT", { exact: true })).toBeVisible();
  await open.getByText("Position fill ledger", { exact: true }).click();
  await expect(open.getByRole("row").filter({ hasText: "F00000003" })).toContainText("450.00 USDT");
});

test("import, inspect, compare, and replay split-reference session data", async ({ page }) => {
  test.slow();
  const directory = resolve(fixtures, "exchange");
  const text = readFileSync(resolve(directory, "session.trade"), "utf8");
  await page.goto("/datasets");
  await page.getByRole("button", { name: "Import dataset", exact: true }).click();
  await page.getByLabel("File", { exact: true }).setInputFiles(resolve(directory, "session.csv"));
  await page.getByLabel("Metadata JSON", { exact: true }).setInputFiles(resolve(directory, "session.json"));
  await page.getByRole("button", { name: "Import dataset", exact: true }).click();
  const details = page.getByRole("complementary", { name: "Dataset details" });
  await expect(details.getByText("No missing candles", { exact: true })).toBeVisible();
  await expect(details.getByText(/XNYS · 2024-core-fixture-1/)).toBeVisible();
  await expect(details.getByText("Split reference", { exact: true })).toBeVisible();
  const listed = await (await page.request.get("/api/v1/datasets")).json();
  const dataset = listed.items.find((item: { filename: string }) => item.filename === "session.csv").id;
  await createStrategy(page, "Exchange reference", text);
  await datasetPicker(page).selectOption(dataset);
  const id = await submit(page);
  const url = `/api/v1/backtests/${id}`;
  const shortened = await (await page.request.get(`${url}/bars/1`)).json();
  expect(shortened.close_at).toBe("2024-11-29T18:00:00Z");
  expect(shortened.events.find((event: { kind: string }) => event.kind === "fill").observed_at).toBe("2024-11-29T14:30:00Z");
  const split = await (await page.request.get(`${url}/bars/2`)).json();
  expect(split.split_factor).toBe(2);
  expect(split.exit.expression.samples).toEqual(expect.arrayContaining([
    expect.objectContaining({ value: 110, observed_at: "2024-12-02T21:00:00Z" }),
  ]));
  const manifest = await (await page.request.get(`${url}/artifacts/manifest.json`)).json();
  expect(manifest).toMatchObject({ semantics_version: "7.0.0", decision_inspection: { schema_version: 3 } });
  const library = process.env.TRADELANG_TEST_LIBRARY;
  if (!library) throw new Error("The isolated library is unavailable");
  const bundle = resolve(library, "runs", id);
  const temporary = await mkdtemp(resolve(tmpdir(), "tradelang-session-replay-"));
  try {
    const { stdout } = await exec("tradelang", [
      "backtest", resolve(bundle, "source.trade"), "--run-config", resolve(bundle, "run-config.json"),
      "--out", resolve(temporary, "replay"), "--json",
    ], { timeout: 15_000 });
    const replay = JSON.parse(stdout).result;
    expect(replay.run_fingerprint).toBe(manifest.run_fingerprint);
    expect(replay.result_digest).toBe(manifest.result_digest);
    expect(replay.summary.final_equity).toBe(1200);
  } finally {
    await rm(temporary, { recursive: true });
  }
  await createStrategy(page, "Shortened session window", text.replace("to 2024-12-03", "to 2024-11-29"));
  await datasetPicker(page).selectOption(dataset);
  const shorter = await submit(page);
  const compared = await (await page.request.get(`/api/v1/backtests/compare?ids=${id},${shorter}`)).json();
  expect(compared.common_benchmark.cohorts[0]).toMatchObject({
    start_at: "2024-11-29T14:30:00Z", end_at: "2024-11-29T18:00:00Z",
  });
});

test("inspect and replay a borrowed-asset short with collateral and financing", async ({ page }) => {
  test.slow();
  const directory = resolve(fixtures, "short");
  const imported = await page.request.post("/api/v1/datasets/import", {
    headers: { Origin: origin() },
    multipart: {
      file: {
        name: "short-round-trip.csv", mimeType: "text/csv",
        buffer: readFileSync(resolve(directory, "round-trip.csv")),
      },
      metadata: readFileSync(resolve(directory, "round-trip.json"), "utf8"),
    },
  });
  expect(imported.ok()).toBe(true);
  const dataset = (await imported.json()).dataset.id;
  const strategy = readFileSync(resolve(directory, "round-trip.trade"), "utf8");
  await createStrategy(page, "Borrowed-asset reference", strategy);
  await datasetPicker(page).selectOption(dataset);
  const id = await submit(page);
  const url = `/api/v1/backtests/${id}`;
  const run = await (await page.request.get(url)).json();
  expect(run.summary).toMatchObject({
    final_equity: 1035.5,
    costs: { total_borrow_cost: 5, total_fees: 9.5 },
    short_accounting: { reserved_cash: 0, insolvent: false, liquidations: 0 },
  });
  const signal = await (await page.request.get(`${url}/bars/0`)).json();
  expect(signal.entry.outcome).toBe("order_queued");
  const holding = await (await page.request.get(`${url}/bars/1`)).json();
  expect(holding.exit.outcome).toBe("order_queued");
  const entry = holding.events.find((event: { kind: string }) => event.kind === "fill");
  expect(entry.data).toMatchObject({ side: "short", quantity_after: -5, margin: { reserved_cash: 750 } });
  const trades = await (await page.request.get(`${url}/trades`)).json();
  expect(trades.items[0]).toMatchObject({
    direction: "short", initial_collateral: 250, borrow_cost: 5, net_pnl: 35.5,
  });
  await page.getByRole("button", { name: "T000001", exact: true }).click();
  const details = page.getByRole("complementary", { name: "Trade details" });
  await details.getByText("Position fill ledger", { exact: true }).click();
  const ledger = details.getByRole("table", { name: "Position fills" });
  await expect(ledger.getByRole("row").filter({ hasText: "F00000001" })).toContainText("-5");
  const cover = ledger.getByRole("row").filter({ hasText: "F00000002" });
  await expect(cover).toContainText("35.50 USD");
  await expect(cover.getByRole("cell", { name: "5.00 USD", exact: true })).toBeVisible();
  await page.getByText("Download exports", { exact: true }).click();
  await expect(page.getByRole("link", { name: "Replay configuration" })).toBeVisible();
  const manifest = await (await page.request.get(`${url}/artifacts/manifest.json`)).json();
  expect(manifest).toMatchObject({ semantics_version: "8.0.0", position_ledger: { schema_version: 2 } });
  const library = process.env.TRADELANG_TEST_LIBRARY;
  if (!library) throw new Error("The isolated library is unavailable");
  const bundle = resolve(library, "runs", id);
  const temporary = await mkdtemp(resolve(tmpdir(), "tradelang-short-replay-"));
  try {
    const { stdout } = await exec("tradelang", [
      "backtest", resolve(bundle, "source.trade"), "--run-config", resolve(bundle, "run-config.json"),
      "--out", resolve(temporary, "replay"), "--json",
    ], { timeout: 15_000 });
    const replay = JSON.parse(stdout).result;
    expect(replay.run_fingerprint).toBe(manifest.run_fingerprint);
    expect(replay.result_digest).toBe(manifest.result_digest);
  } finally {
    await rm(temporary, { recursive: true });
  }
});

test("explain a saved portfolio's asset priority", async ({ page }) => {
  const source = readFileSync(resolve(fixtures, "portfolio", "priority.trade"), "utf8");
  await createStrategy(page, "Shared portfolio fixture", source);
  await page.getByRole("button", { name: "Explain strategy", exact: true }).click();
  await expect(page.getByText("Commitment order · alpha, beta.", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Assumptions", exact: true }).click();
  await expect(page.getByText("Asset priority", { exact: true })).toBeVisible();
  await expect(page.getByText("alpha, beta", { exact: true })).toBeVisible();
});

test("select portfolio assets, run and inspect shared cash", async ({ page }) => {
  test.slow();
  const directory = resolve(fixtures, "portfolio");
  const assetIds: Record<string, string> = {};
  const strategyEndpoints: Record<string, string> = {};
  for (const name of ["alpha", "beta"]) {
    const imported = await page.request.post("/api/v1/datasets/import", {
      headers: { Origin: origin() },
      multipart: {
        file: { name: `${name}-portfolio.csv`, mimeType: "text/csv", buffer: readFileSync(resolve(directory, `${name}.csv`)) },
        metadata: readFileSync(resolve(directory, `${name}-metadata.json`), "utf8"),
      },
    });
    expect(imported.ok()).toBe(true);
    assetIds[name] = (await imported.json()).dataset.id;
    await createStrategy(page, `Portfolio ${name}`, readFileSync(resolve(directory, `${name}.trade`), "utf8"));
    strategyEndpoints[name] = `/api/v1${new URL(page.url()).pathname}`;
  }
  await createStrategy(page, "Shared portfolio run", readFileSync(resolve(directory, "priority.trade"), "utf8"));
  for (const name of ["alpha", "beta"]) {
    await page.getByLabel(`Strategy for ${name}`).selectOption({ label: `Portfolio ${name} · revision 2` });
    await page.getByLabel(`Dataset for ${name}`, { exact: true }).selectOption(assetIds[name]);
  }
  await page.getByText("Run settings for beta").click();
  await page.getByLabel("Fee bps for beta").fill("25");
  await page.getByRole("button", { name: "Validate", exact: true }).click();
  await expect(page.getByText("Strategy and dataset validated.")).toBeVisible({ timeout: 15000 });
  await expect(page.getByText("Validated with 2 portfolio assets")).toBeVisible();
  const alphaEndpoint = strategyEndpoints.alpha;
  const alphaRevision = await (await page.request.get(alphaEndpoint)).json();
  const alphaEdit = await page.request.put(alphaEndpoint, {
    headers: { Origin: origin(), "If-Match": alphaRevision.etag },
    data: {
      source: alphaRevision.current_source.replace("when close == 100 price", "when false"),
      name: alphaRevision.name,
      expected_revision: 2,
    },
  });
  expect(alphaEdit.status()).toBe(200);
  await page.getByRole("button", { name: "Switch strategy", exact: true }).click();
  const alphaPicker = page.getByLabel("Strategy for alpha");
  await expect(alphaPicker.locator("option").filter({ hasText: "Portfolio alpha · revision 3" })).toBeAttached();
  await expect(alphaPicker.locator("option:checked")).toHaveText("Portfolio alpha · revision 2");
  await page.getByRole("button", { name: "Run backtest", exact: true }).click();
  await expect(page.getByText(/Backtest submitted for revision/)).toBeVisible();
  await openRunLink(page).click();
  await expect(page.getByRole("heading", { name: "Portfolio results" })).toBeVisible({ timeout: 20000 });
  await expect(page.getByText("1,150.00 USD", { exact: true })).toBeVisible();
  const eventTable = page.getByRole("table", { name: "Portfolio events" });
  await expect(eventTable.getByRole("row").filter({ hasText: "Entry rejected · Insufficient cash" }).first()).toContainText("beta");
  await expect(page.getByText("No closed trades.", { exact: true })).toBeVisible();
  await page.getByLabel("Inspect asset").selectOption("beta");
  const inspector = page.getByRole("region", { name: "Candle decision" });
  await expect(inspector.getByLabel("Dataset bar index")).toBeEmpty();
  await inspector.getByLabel("Dataset bar index").fill("1");
  await inspector.getByRole("button", { name: "Inspect candle" }).click();
  await inspector.getByText("Candle events").click();
  await expect(inspector.getByText("Entry rejected · Insufficient cash")).toBeVisible();
  await page.getByText("Download exports").click();
  await expect(page.getByRole("link", { name: "Replay configuration" })).toBeVisible();
  const firstId = new URL(page.url()).searchParams.get("run")!;
  const savedConfig = await (await page.request.get(`/api/v1/backtests/${firstId}/artifacts/run-config.json`)).json();
  expect(savedConfig.assets.beta.settings.fee_bps).toBe(25);
  const library = process.env.TRADELANG_TEST_LIBRARY;
  if (!library) throw new Error("The isolated library is unavailable");
  const bundle = resolve(library, "runs", firstId);
  const temporary = await mkdtemp(resolve(tmpdir(), "tradelang-portfolio-settings-replay-"));
  try {
    const manifest = await (await page.request.get(`/api/v1/backtests/${firstId}/artifacts/manifest.json`)).json();
    const { stdout } = await exec("tradelang", [
      "backtest", resolve(bundle, "source.trade"), "--run-config", resolve(bundle, "run-config.json"),
      "--out", resolve(temporary, "replay"), "--json",
    ], { timeout: 15000 });
    const replay = JSON.parse(stdout).result;
    expect(replay.run_fingerprint).toBe(manifest.run_fingerprint);
    expect(replay.result_digest).toBe(manifest.result_digest);
  } finally {
    await rm(temporary, { recursive: true });
  }
  const firstRun = await (await page.request.get(`/api/v1/backtests/${firstId}`)).json();
  expect(firstRun.configuration.portfolio_assets[0]).toMatchObject({ asset: "alpha", strategy_revision: 2 });
  await page.getByRole("link", { name: "Open standalone run" }).click();
  await expect(page.getByRole("link", { name: "Open strategy workspace" }))
    .toHaveAttribute("href", `/strategies/${firstRun.strategy_id}?run=${firstId}`);
  const repeated = await page.request.post("/api/v1/backtests", {
    headers: { Origin: origin() },
    data: {
      strategy_id: firstRun.strategy_id,
      strategy_revision: firstRun.strategy_revision,
      portfolio_assets: Object.fromEntries(firstRun.configuration.portfolio_assets.map((asset: {
        asset: string; strategy_id: string; strategy_revision: number; dataset_id: string;
      }) => [asset.asset, {
        strategy_id: asset.strategy_id, strategy_revision: asset.strategy_revision, dataset_id: asset.dataset_id,
      }])),
    },
  });
  expect(repeated.status()).toBe(202);
  const secondId = (await repeated.json()).id;
  await expect.poll(async () => (await (await page.request.get(`/api/v1/backtests/${secondId}`)).json()).status,
    { timeout: 20000 }).toBe("succeeded");
  await page.goto(`/compare?ids=${firstId},${secondId}`);
  await expect(page.getByText("Exact timestamps")).toBeVisible();
  await expect(page.getByText("The common-start reference is unavailable for portfolio runs.")).toBeVisible();
});
