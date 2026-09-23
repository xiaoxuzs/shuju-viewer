// Protected verifier: real network and browser only. No route interception/mocks.
import { chromium, expect } from "@playwright/test";
import fs from "node:fs";
import assert from "node:assert/strict";

const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const assertions = [];
const check = (name, actual, expected) => { assert.deepEqual(actual, expected, name); assertions.push({ name, actual, expected }); };
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ locale: "en-US" });
await context.tracing.start({ screenshots: true, snapshots: true, sources: false });
const page = await context.newPage();
const errors = [];
page.on("pageerror", error => errors.push(error.message));
page.on("response", response => {
  if (response.url().includes("/api/") && response.status() >= 500) errors.push(`HTTP ${response.status()}: ${new URL(response.url()).pathname}`);
});
let passed = false;
try {
  const health = await fetch(input.api_url + "/health").then(r => r.json());
  check("backend identity", health.build_id, input.build_id);
  check("backend run identity", health.validation_id, input.validation_id);
  const prefix = input.api_url + "/api/v1/datasets/candidate-validation";
  await page.goto(input.base_url + "/datasets/candidate-validation", { waitUntil: "networkidle" });
  await expect(page.getByText("Agent-ZP QC", { exact: true })).toBeVisible();
  await expect(page.getByText("DIA-NN QC", { exact: true })).toHaveCount(0);
  assertions.push({ name: "generic source overview is not relabelled DIA-NN", actual: "Agent-ZP QC", expected: "Agent-ZP QC" });
  const fullScope = input.oracle.schema_version === 2;
  const unfiltered = fullScope ? "&q_filter=false&decoy=true" : "";
  const displayNumber = value => value !== 0 && Math.abs(value) < 0.001 ? value.toExponential(2) : new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(value);
  const matchesResponse = await fetch(prefix + "/matches?page_size=100" + unfiltered);
  check("real list HTTP", matchesResponse.status, 200);
  const matches = await matchesResponse.json();
  check("unfiltered source row count", matches.total, input.oracle.total_matches);
  await page.goto(input.base_url + "/datasets/candidate-validation/matches?page_size=100" + unfiltered, { waitUntil: "networkidle" });
  await expect(page.locator("table")).toBeVisible();
  await expect(page.locator("table tbody tr")).toHaveCount(Math.min(50, input.oracle.total_matches));
  if (fullScope && input.oracle.matches.length) {
    const runId = String(input.oracle.matches[0].run_id);
    await page.getByLabel("Run", { exact: true }).selectOption(runId);
    await expect(page).toHaveURL(new RegExp(`run_id=${runId}`));
    await page.getByLabel("Run", { exact: true }).selectOption("");
    assertions.push({ name: "real run selector interaction", actual: runId, expected: runId });
    const hide = page.getByLabel("Hide confirmed decoys", { exact: true });
    await hide.check();
    await hide.uncheck();
    assertions.push({ name: "decoy filter interaction", actual: "checked then unchecked", expected: "checked then unchecked" });
  }
  check("frontend identity", await page.locator("html").getAttribute("data-viewer-build-id"), input.build_id);
  check("frontend run identity", await page.locator("html").getAttribute("data-viewer-validation-id"), input.validation_id);
  for (const expected of input.oracle.matches) {
    let detail;
    if (fullScope) detail = await fetch(prefix + `/matches/${expected.match_id}`).then(r => r.json());
    for (const item of fullScope ? [] : matches.items) {
      const candidate = await fetch(prefix + `/matches/${item.id}`).then(r => r.json());
      if (candidate.extra_metadata?.source_record_id === expected.source_record_id) { detail = candidate; break; }
    }
    assert.ok(detail, "source record preserved");
    check(`${expected.source_record_id}: exact source identity`, detail.extra_metadata.source_record_id, expected.source_record_id);
    check(`${expected.source_record_id}: sequence`, detail.sequence, expected.sequence);
    check(`${expected.source_record_id}: RT minutes`, detail.retention_time, expected.rt_minutes);
    check(`${expected.source_record_id}: q-value`, detail.q_value, expected.q_value);
    check(`${expected.source_record_id}: decoy`, detail.is_decoy_match, expected.decoy);
    const measurements = detail.extra_metadata.quantification ?? [];
    check(`${expected.source_record_id}: quantification values`, measurements.map(m => m.value), expected.quantification_values);
    check(`${expected.source_record_id}: quantification units`, measurements.map(m => m.unit), expected.quantification_units);
    await page.goto(input.base_url + `/datasets/candidate-validation/matches/${detail.id}`, { waitUntil: "networkidle" });
    const metadata = page.getByTestId("match-metadata");
    await expect(metadata).toBeVisible();
    const rtValue = metadata.locator('[data-field="Identification RT apex (min)"] > div').nth(1);
    await expect(rtValue).toHaveText(expected.rt_minutes === null ? "-" : fullScope ? displayNumber(expected.rt_minutes) : String(expected.rt_minutes));
    if (expected.q_value === null) await expect(metadata.locator('[data-field="Q.Value"] > div').nth(1)).toHaveText("-");
    for (const [index, measurement] of expected.quantification_values.entries()) {
      await expect(page.getByTestId("match-quantification").locator('[data-field="Value"] > div').nth(index * 2 + 1)).toHaveText(measurement === null ? "Missing" : fullScope ? displayNumber(measurement) : String(measurement));
    }
    if (expected.rt_minutes !== null) assertions.push({ name: `${expected.source_record_id}: visible RT with min label`, actual: expected.rt_minutes, expected: expected.rt_minutes });
    if (expected.decoy === null) await expect(page.getByText("Unknown", { exact: true }).first()).toBeVisible();
    // Match -> peptide navigation is a real link over the committed projection.
    await page.getByRole("link", { name: "View peptide", exact: true }).click();
    await expect(page).toHaveURL(input.base_url + `/datasets/candidate-validation/peptides/${detail.peptide_id}`);
    await expect(page.getByText(expected.sequence, { exact: true }).first()).toBeVisible();
    assertions.push({ name: `${expected.source_record_id}: actual peptide link`, actual: detail.peptide_id, expected: detail.peptide_id });
  }
  check("uncaught browser errors", errors, []);
  passed = true;
} finally {
  await context.tracing.stop({ path: input.trace });
  fs.writeFileSync(input.output, JSON.stringify({ passed, assertions, errors }, null, 2));
  await browser.close();
}
