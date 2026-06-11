import { expect, test, type Page, type Route } from "@playwright/test";

const dataset = {
  id: 39,
  slug: "demo",
  name: "DIA demo",
  description: null,
  source_path: "demo",
  capabilities: {},
  analysis_mode: "BOTTOM_UP",
  status: "ready",
  source_software: "DIA-NN",
  extra_metadata: {},
  bu_runs: [],
  created_at: "2026-06-07T00:00:00Z",
  updated_at: null,
  cutoffs: [],
};

function matchDetail(rawFormat: string, scanNumber: number | null | undefined = -1) {
  return {
    id: 1,
    run_id: 10,
    run_name: "run.mzML",
    peptide_id: 5,
    sequence: "PEPTIDE",
    modified_sequence: null,
    precursor_mz: 477.3051,
    precursor_charge: 2,
    retention_time: 92.46,
    experimental_mass: null,
    q_value: 0.001,
    score: 10,
    intensity: 1000,
    is_decoy_match: false,
    ...(scanNumber !== undefined ? { scan_number: scanNumber } : {}),
    protein_group: null,
    protein_accessions: [],
    genes: null,
    search_engine: "DIA-NN",
    spectrum_native_id: null,
    ms_level: 2,
    entity_type: "PEPTIDE",
    run: {
      run_id: 10,
      file_name: rawFormat === "mzml" ? "run.mzML" : "run.d",
      raw_format: rawFormat,
      file_path: rawFormat === "mzml" ? "run.mzML" : "run.d",
      diann_run_name: "run",
    },
    rt_window: { rt_start: 92.15, rt_stop: 93.08, rt_apex: 92.46, unit: "min" },
    proteins: [],
    diann: {},
    spectrum_links: {},
    extra_metadata: { rt_start: 92.15, rt_stop: 93.08 },
  };
}

const xic = {
  rt: [92, 93, 94],
  intensity: [10, 100, 20],
  precursor_mz: 477.3051,
  precursor_charge: 2,
  ppm: 10,
  rt_apex: 92.46,
  rt_start: 92.15,
  rt_stop: 93.08,
  unit_rt: "min",
  traces: [
    { label: "M", isotope_index: 0, target_mz: 477.3051, intensity: [10, 100, 20] },
    { label: "M+1", isotope_index: 1, target_mz: 477.8068, intensity: [4, 40, 8] },
    { label: "M+2", isotope_index: 2, target_mz: 478.3085, intensity: [2, 20, 4] },
  ],
};

function spectrum(scan: number, rt: number, msLevel: 1 | 2) {
  const matchedIons = [
    { ion_type: "b", position: 2, charge: 1, theo_mz: 125, exp_mz: 125, ppm: 0, intensity: 90 },
    { ion_type: "y", position: 3, charge: 1, theo_mz: 150, exp_mz: 150, ppm: 0, intensity: 80 },
    { ion_type: "y", position: 5, charge: 1, theo_mz: 175.119, exp_mz: 175.119, ppm: 0, intensity: 100 },
    { ion_type: "b", position: 4, charge: 1, theo_mz: 200, exp_mz: 200, ppm: 0, intensity: 70 },
    { ion_type: "y", position: 6, charge: 1, theo_mz: 225, exp_mz: 225, ppm: 0, intensity: 60 },
    { ion_type: "b", position: 6, charge: 1, theo_mz: 250, exp_mz: 250, ppm: 0, intensity: 50 },
    { ion_type: "y", position: 7, charge: 1, theo_mz: 275, exp_mz: 275, ppm: 0, intensity: 40 },
    { ion_type: "b", position: 8, charge: 1, theo_mz: 300, exp_mz: 300, ppm: 0, intensity: 30 },
    { ion_type: "y", position: 9, charge: 2, theo_mz: 325, exp_mz: 325, ppm: 0, intensity: 20 },
  ];
  return {
    scan,
    native_id: `scan=${scan}`,
    ms_level: msLevel,
    rt_seconds: rt * 60,
    rt_minutes: rt,
    mz: msLevel === 2 ? [100, ...matchedIons.map((ion) => ion.exp_mz), 350] : [400, 477.3051, 600],
    intensity: msLevel === 2 ? [20, ...matchedIons.map((ion) => ion.intensity), 10] : [10, 100, 20],
    precursor: msLevel === 2
      ? {
          selected_mz: 477.3051,
          charge: 2,
          isolation_target_mz: 478,
          isolation_lower: 6.5,
          isolation_upper: 6.5,
        }
      : null,
    matched_ions: msLevel === 2 ? matchedIons : [],
    markers: msLevel === 1 ? [{ mz: 477.3051, label: "precursor", charge: 2 }] : [],
  };
}

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockMzmlMatch(
  page: Page,
  matchDelayMs = 0,
  scanNumber: number | null | undefined = -1,
  productFailureMz?: number,
  productBatchStatus = 200,
  options: {
    endpointErrors?: Partial<Record<"xic" | "ms1" | "ms2" | "product", {
      status: number;
      detail: unknown;
    }>>;
    xicBody?: typeof xic;
    productNoSignal?: boolean;
  } = {},
) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/datasets/demo") return fulfillJson(route, dataset);
    if (url.pathname === "/api/v1/datasets/demo/matches/1") {
      if (matchDelayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, matchDelayMs));
      }
      return fulfillJson(route, matchDetail("mzml", scanNumber));
    }
    if (url.pathname.endsWith("/matches/1/xic")) {
      const failure = options.endpointErrors?.xic;
      if (failure) {
        return route.fulfill({
          status: failure.status,
          contentType: "application/json",
          body: JSON.stringify({ detail: failure.detail }),
        });
      }
      return fulfillJson(route, options.xicBody ?? xic);
    }
    if (url.pathname.endsWith("/matches/1/spectrum/ms1")) {
      const failure = options.endpointErrors?.ms1;
      if (failure) {
        return route.fulfill({
          status: failure.status,
          contentType: "application/json",
          body: JSON.stringify({ detail: failure.detail }),
        });
      }
      return fulfillJson(route, spectrum(500, 92.45, 1));
    }
    if (url.pathname.endsWith("/matches/1/spectrum/ms2")) {
      const failure = options.endpointErrors?.ms2;
      if (failure) {
        return route.fulfill({
          status: failure.status,
          contentType: "application/json",
          body: JSON.stringify({ detail: failure.detail }),
        });
      }
      return fulfillJson(route, url.searchParams.has("rt") ? spectrum(67727, 93.01, 2) : spectrum(67726, 92.46, 2));
    }
    if (url.pathname.endsWith("/matches/1/product-xics")) {
      const failure = options.endpointErrors?.product;
      if (failure) {
        return route.fulfill({
          status: failure.status,
          contentType: "application/json",
          body: JSON.stringify({ detail: failure.detail }),
        });
      }
      if (productBatchStatus >= 400) {
        return route.fulfill({ status: productBatchStatus, contentType: "application/json", body: "{}" });
      }
      const request = route.request().postDataJSON() as {
        tolerance_ppm: number;
        ions: Array<{
          id: string;
          ion: string;
          series: "b" | "y";
          position: number;
          charge: number;
          mz: number;
        }>;
      };
      return fulfillJson(route, {
        traces: request.ions.map((ion) => ({
          ...ion,
          tolerance_ppm: request.tolerance_ppm,
          status: ion.mz === productFailureMz ? "error" : options.productNoSignal ? "no_signal" : "ok",
          error: ion.mz === productFailureMz ? "failed" : null,
          points: ion.mz === productFailureMz
            ? []
            : options.productNoSignal
              ? [
                  { rt: 92.15, intensity: 0, scan: 67720 },
                  { rt: 92.46, intensity: 0, scan: 67726 },
                ]
            : [
                { rt: 92.15, intensity: 20, scan: 67720 },
                { rt: 92.46, intensity: 100, scan: 67726 },
              ],
        })),
      });
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });
}

async function clickMs2Peak(page: Page, scan: number, mz: number) {
  const svg = page.locator(`svg[aria-label^="MS2 scan #${scan}"]`).first();
  const box = await svg.boundingBox();
  if (!box) throw new Error("MS2 SVG has no bounding box");
  await svg.click({
    position: {
      x: 72 + (box.width - 92) * ((mz - 100) / 250),
      y: box.height - 60,
    },
  });
}

test("shows page loading while match details are pending", async ({ page }) => {
  await mockMzmlMatch(page, 500);
  await page.goto("/datasets/demo/matches/1");

  await expect(page.getByRole("status", { name: "Loading" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "PEPTIDE" })).toBeVisible();
  await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0);
});

test("shows a generic English error without exposing backend details", async ({ page }) => {
  const backendError = "\u540e\u7aef\u5185\u90e8\u9519\u8bef";
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/datasets/demo") return fulfillJson(route, dataset);
    if (url.pathname === "/api/v1/datasets/demo/matches/1") {
      return route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: backendError }),
      });
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });

  await page.goto("/datasets/demo/matches/1");

  await expect(page.getByText("Failed to load data.")).toBeVisible();
  await expect(page.getByText(backendError)).toHaveCount(0);
});

test("precursor XIC selects MS2 and matched ion toggles product XIC comparison", async ({ page }) => {
  await mockMzmlMatch(page);
  await page.goto("/datasets/demo/matches/1");

  await expect(page.getByRole("heading", { name: "Precursor XIC" })).toBeVisible();
  const productCard = page.getByTestId("product-ion-xic-card");
  await expect(productCard.getByRole("heading", { name: "Product ion XIC comparison" })).toBeVisible();
  await expect(productCard).toContainText(
    "Select product ions to display product XIC.",
  );
  await expect(page.getByText(/MS1 extracted ion chromatogram for the precursor/)).toBeVisible();
  await expect(page.getByTestId("ms2-current-rt")).toContainText("MS2 scan #67726");
  await expect(page.getByTestId("ms2-current-rt")).toContainText("MS2 scan RT: 92.4600 min");

  const xicSvg = page.locator('svg[aria-label="Retention Time (min) versus MS1 intensity at isotope m/z"]').first();
  const xicBox = await xicSvg.boundingBox();
  if (!xicBox) throw new Error("XIC SVG has no bounding box");
  const selectedMs2Request = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname.endsWith("/spectrum/ms2") && url.searchParams.get("rt") === "93";
  });
  await xicSvg.click({
    position: {
      x: 72 + (xicBox.width - 92) / 2,
      y: 24,
    },
  });
  await selectedMs2Request;
  await expect(page.getByText(/Current inspected RT: 93.0000 min from XIC selection/)).toBeVisible();
  await expect(page.getByTestId("ms2-current-rt")).toContainText("MS2 scan #67727");
  await expect(page.getByTestId("ms2-current-rt")).toContainText("MS2 scan RT: 93.0100 min");

  const productRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    if (!url.pathname.endsWith("/product-xics")) return false;
    const body = request.postDataJSON() as { ions: Array<{ mz: number }>; rt_window?: unknown };
    return body.rt_window === undefined && body.ions.some((ion) => ion.mz === 175.119);
  });
  await clickMs2Peak(page, 67727, 175.119);
  await productRequest;
  await expect(productCard.getByText("y5 175.1190 m/z")).toBeVisible();
  await expect(productCard.getByTestId("plot-series")).toHaveCount(1);

  const secondProductRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    if (!url.pathname.endsWith("/product-xics")) return false;
    return (request.postDataJSON() as { ions: Array<{ mz: number }> }).ions.some((ion) => ion.mz === 125);
  });
  await clickMs2Peak(page, 67727, 125);
  await secondProductRequest;
  await expect(productCard.getByTestId("plot-series")).toHaveCount(2);

  await productCard.getByRole("button", { name: "Remove y5 product ion XIC" }).click();
  await expect(productCard.getByText("b2 125.0000 m/z")).toBeVisible();
  await productCard.getByRole("button", { name: "Clear all" }).click();
  await expect(productCard).toContainText("Select product ions to display product XIC.");
});

test("adds top fragments, enforces the limit, and switches raw or normalized views", async ({ page }) => {
  await mockMzmlMatch(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("product-ion-xic-card");
  const mode = card.getByTestId("product-ion-y-axis-mode");
  await expect(mode.getByRole("button", { name: "Normalized" })).toHaveAttribute("aria-pressed", "true");

  await card.getByRole("button", { name: "Add top 3 fragments" }).click();
  await expect(card).toContainText("Selected product ions: 3 / 8");
  await expect(card.getByTestId("plot-series")).toHaveCount(3);
  await expect(page.getByTestId("live-fragment-row").filter({ has: page.locator('input:checked') })).toHaveCount(3);
  await expect(page.locator('[data-testid="matched-spectrum-peak"][data-product-ion-selected="true"]')).toHaveCount(3);

  await mode.getByRole("button", { name: "Raw intensity" }).click();
  await expect(mode.getByRole("button", { name: "Raw intensity" })).toHaveAttribute("aria-pressed", "true");
  await expect(card.locator('svg[aria-label="Retention Time (min) versus Intensity"]')).toBeVisible();
  await expect(page.getByTestId("live-fragment-row").filter({ has: page.locator('input:checked') })).toHaveCount(3);

  await card.getByRole("button", { name: "Add top 3 fragments" }).click();
  await card.getByRole("button", { name: "Add top 3 fragments" }).click();
  await expect(card).toContainText("Selected product ions: 8 / 8");
  await expect(card.getByRole("alert")).toContainText(
    "Maximum 8 product ions can be compared at once. Remove one before adding another.",
  );
  await expect(page.getByRole("checkbox", { checked: true })).toHaveCount(8);
  await expect(page.getByRole("checkbox", { checked: false })).toBeDisabled();

  await card.getByRole("button", { name: "Clear all" }).click();
  await expect(card).toContainText("Selected product ions: 0 / 8");
  await expect(card).toContainText("Select product ions to display product XIC.");
  await expect(page.getByRole("checkbox", { checked: true })).toHaveCount(0);
  await expect(page.locator('[data-testid="live-fragment-row"][data-product-ion-selected="true"]')).toHaveCount(0);
  await expect(page.locator('[data-testid="matched-spectrum-peak"][data-product-ion-selected="true"]')).toHaveCount(0);
});

test("keeps successful product ion traces when one query fails", async ({ page }) => {
  await mockMzmlMatch(page, 0, -1, 125);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("product-ion-xic-card");
  await card.getByRole("button", { name: "Add top 3 fragments" }).click();

  await expect(card.getByText("Failed to load product ion XIC for b2.")).toBeVisible();
  await expect(card.getByTestId("plot-series")).toHaveCount(2);
  await expect(page.getByRole("heading", { name: "Live mzML MS2 matching" })).toBeVisible();
});

test("live fragment checkbox synchronizes table, spectrum, chips, and removal", async ({ page }) => {
  await mockMzmlMatch(page);
  await page.goto("/datasets/demo/matches/1");

  await expect(page.getByRole("columnheader", { name: "Product XIC" })).toBeVisible();
  const row = page.getByTestId("live-fragment-row").filter({ hasText: "y5" });
  const addCheckbox = row.getByRole("checkbox", { name: "Add y5 to product ion XIC" });
  const batchRequest = page.waitForRequest((request) => request.url().endsWith("/product-xics"));
  await addCheckbox.check();
  await batchRequest;

  await expect(row).toHaveAttribute("data-product-ion-selected", "true");
  await expect(row.getByRole("checkbox", { name: "Remove y5 from product ion XIC" })).toBeChecked();
  const ionId = await row.getAttribute("data-product-ion-id");
  if (!ionId) throw new Error("Live fragment row has no product ion id");
  await expect(page.locator(`[data-testid="matched-spectrum-peak"][data-product-ion-id="${ionId}"]`))
    .toHaveAttribute("data-product-ion-selected", "true");
  const card = page.getByTestId("product-ion-xic-card");
  await expect(card.getByText("y5 175.1190 m/z")).toBeVisible();

  await card.getByRole("button", { name: "Remove y5 product ion XIC" }).click();
  await expect(row).toHaveAttribute("data-product-ion-selected", "false");
  await expect(row.getByRole("checkbox", { name: "Add y5 to product ion XIC" })).not.toBeChecked();
  await expect(page.locator(`[data-testid="matched-spectrum-peak"][data-product-ion-id="${ionId}"]`))
    .toHaveAttribute("data-product-ion-selected", "false");
});

test("batch request failure stays inside the product ion card", async ({ page }) => {
  await mockMzmlMatch(page, 0, -1, undefined, 500);
  await page.goto("/datasets/demo/matches/1");

  const row = page.getByTestId("live-fragment-row").filter({ hasText: "y5" });
  await row.getByRole("checkbox", { name: "Add y5 to product ion XIC" }).check();

  await expect(page.getByTestId("product-ion-xic-card")).toContainText("Failed to load product ion XIC.");
  await expect(page.getByRole("heading", { name: "Live mzML MS2 matching" })).toBeVisible();
});

test("scan-index missing XIC stays local and preserves its backfill command", async ({ page }) => {
  const command = "python scripts/backfill_mzml_scan_indexes.py --dataset-id 39 --run-id 10";
  await mockMzmlMatch(page, 0, -1, undefined, 200, {
    endpointErrors: {
      xic: {
        status: 409,
        detail: { error: "scan_index_missing", backfill_command: command },
      },
    },
  });
  await page.goto("/datasets/demo/matches/1");

  await expect(page.getByText("Derived scan index is not ready.")).toBeVisible();
  await expect(page.getByText(command)).toBeVisible();
  await expect(page.getByRole("heading", { name: "MS1 spectrum from mzML" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Live mzML MS2 matching" })).toBeVisible();
});

test("empty precursor XIC shows a no-signal state without hiding spectra", async ({ page }) => {
  await mockMzmlMatch(page, 0, -1, undefined, 200, {
    xicBody: {
      ...xic,
      intensity: [0, 0, 0],
      traces: xic.traces.map((trace) => ({ ...trace, intensity: [0, 0, 0] })),
    },
  });
  await page.goto("/datasets/demo/matches/1");

  await expect(page.getByText("No precursor signal in the selected range.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "MS1 spectrum from mzML" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Live mzML MS2 matching" })).toBeVisible();
});

test("product XIC stale state stays inside the product card", async ({ page }) => {
  const command = "python scripts/backfill_mzml_scan_indexes.py --dataset-id 39 --run-id 10";
  await mockMzmlMatch(page, 0, -1, undefined, 200, {
    endpointErrors: {
      product: {
        status: 409,
        detail: { error: "scan_index_stale", backfill_command: command },
      },
    },
  });
  await page.goto("/datasets/demo/matches/1");

  const row = page.getByTestId("live-fragment-row").filter({ hasText: "y5" });
  await row.getByRole("checkbox", { name: "Add y5 to product ion XIC" }).check();

  const card = page.getByTestId("product-ion-xic-card");
  await expect(card.getByText("Derived scan index is stale.")).toBeVisible();
  await expect(card.getByText(command)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Live mzML MS2 matching" })).toBeVisible();
});

test("all no-signal product traces show one local no-signal state", async ({ page }) => {
  await mockMzmlMatch(page, 0, -1, undefined, 200, { productNoSignal: true });
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("product-ion-xic-card");
  await card.getByRole("button", { name: "Add top 3 fragments" }).click();

  await expect(card.getByText("No product ion signal in the selected range.")).toBeVisible();
  await expect(card.getByTestId("plot-series")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Live mzML MS2 matching" })).toBeVisible();
});

for (const scanNumber of [-1, null, undefined]) {
  test(`metadata scan ${String(scanNumber)} is displayed as unavailable`, async ({ page }) => {
    await mockMzmlMatch(page, 0, scanNumber);
    await page.goto("/datasets/demo/matches/1");

    const metadata = page.getByTestId("match-metadata");
    await expect(metadata.getByText("N/A", { exact: true })).toBeVisible();
    await expect(metadata).toContainText("Not available from imported match metadata");
    await expect(page.getByText(/^MS1 scan #500\./)).toBeVisible();
    await expect(page.getByTestId("ms2-current-rt")).toContainText("MS2 scan #67726");
  });
}

test("available metadata scan keeps its imported value", async ({ page }) => {
  await mockMzmlMatch(page, 0, 70714);
  await page.goto("/datasets/demo/matches/1");

  await expect(page.getByTestId("match-metadata")).toContainText("70714");
});

test("labels identification, MS1, and MS2 retention times independently", async ({ page }) => {
  await mockMzmlMatch(page);
  await page.goto("/datasets/demo/matches/1");

  await expect(page.getByTestId("match-metadata")).toContainText("Identification RT apex");
  await expect(page.getByText(/MS1 scan RT: 92.4500 min/)).toBeVisible();
  await expect(page.getByText(/MS2 scan RT: 92.4600 min/)).toBeVisible();
});

test("Evidence Summary shows PFMB fallback without hiding live evidence", async ({ page }) => {
  await mockMzmlMatch(page);
  await page.goto("/datasets/demo/matches/1");

  const summary = page.getByTestId("bu-evidence-summary");
  await expect(summary.getByTestId("evidence-live-ms2")).toContainText("Live matched b/y ions");
  await expect(summary.getByTestId("evidence-pfmb")).toContainText("PFMB annotation not available");
});

test("MS2 label modes hide only text and keep tooltip and peak click active", async ({ page }) => {
  await mockMzmlMatch(page);
  await page.goto("/datasets/demo/matches/1");

  const controls = page.getByTestId("spectrum-label-mode").first();
  const svg = page.locator('svg[aria-label^="MS2 scan #67726"]');
  await expect(controls.getByRole("button", { name: "Top labels" })).toHaveAttribute("aria-pressed", "true");
  expect(await svg.getByTestId("spectrum-ion-label").count()).toBeGreaterThan(0);

  await controls.getByRole("button", { name: "No labels" }).click();
  await expect(svg.getByTestId("spectrum-ion-label")).toHaveCount(0);

  const box = await svg.boundingBox();
  if (!box) throw new Error("MS2 SVG has no bounding box");
  await svg.hover({
    position: {
      x: 72 + (box.width - 92) * (75.119 / 250),
      y: 120,
    },
  });
  await expect(page.getByText("Theoretical m/z 175.1190")).toBeVisible();
  await expect(page.getByText("Experimental m/z 175.1190")).toBeVisible();
  await expect(page.getByText("Series y; position 5; charge 1+")).toBeVisible();
  await expect(page.getByText("Click to add product ion XIC.")).toBeVisible();

  const productRequest = page.waitForRequest((request) => request.url().includes("/product-xics"));
  await clickMs2Peak(page, 67726, 175.119);
  await productRequest;
  await expect(page.getByTestId("product-ion-xic-card").getByText("y5 175.1190 m/z")).toBeVisible();
  await expect(page.getByTestId("live-fragment-row").filter({ hasText: "y5" }).getByRole("checkbox")).toBeChecked();

  await controls.getByRole("button", { name: "All labels" }).click();
  await expect(svg.getByTestId("spectrum-ion-label")).toHaveCount(9);
  await expect(page.getByTestId("live-fragment-row").filter({ hasText: "y5" }).getByRole("checkbox")).toBeChecked();
});

test("unsupported raw format shows a downgrade message without match-level spectrum calls", async ({ page }) => {
  let matchLevelCalls = 0;
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/datasets/demo") return fulfillJson(route, dataset);
    if (url.pathname === "/api/v1/datasets/demo/matches/1") return fulfillJson(route, matchDetail("bruker_d"));
    if (
      url.pathname.endsWith("/matches/1/xic")
      || url.pathname.includes("/matches/1/spectrum/")
      || url.pathname.endsWith("/matches/1/product-xic")
      || url.pathname.endsWith("/matches/1/product-xics")
    ) {
      matchLevelCalls += 1;
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });

  await page.goto("/datasets/demo/matches/1");

  await expect(page.getByText("Bruker .d match-level Precursor XIC and MS1/MS2 spectra are not supported.")).toBeVisible();
  expect(matchLevelCalls).toBe(0);
});
