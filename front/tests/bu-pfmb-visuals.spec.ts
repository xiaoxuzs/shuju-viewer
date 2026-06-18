import { expect, test, type Page, type Route } from "@playwright/test";

const dataset = {
  id: 39,
  slug: "demo",
  name: "DIA demo",
  description: null,
  source_path: "demo",
  capabilities: { has_ms2_pfmb: true },
  analysis_mode: "BOTTOM_UP",
  status: "ready",
  source_software: "DIA-NN",
  extra_metadata: {},
  bu_runs: [],
  created_at: "2026-06-07T00:00:00Z",
  updated_at: null,
  cutoffs: [],
};

function matchDetail(id = 1) {
  return {
    id,
    run_id: 10,
    run_name: "run.mzML",
    peptide_id: 5,
    sequence: "PEPTIDE",
    modified_sequence: null,
    precursor_mz: 477.3051,
    precursor_charge: 2,
    retention_time: 94.99,
    experimental_mass: null,
    q_value: 0.001,
    score: 10,
    intensity: 1000,
    is_decoy_match: false,
    scan_number: -1,
    protein_group: null,
    protein_accessions: [],
    genes: null,
    search_engine: "DIA-NN",
    spectrum_native_id: null,
    ms_level: 2,
    entity_type: "PEPTIDE",
    run: { run_id: 10, file_name: "run.mzML", raw_format: "mzml", file_path: "run.mzML", diann_run_name: "run" },
    rt_window: { rt_start: 93.99, rt_stop: 95.99, rt_apex: 94.99, unit: "min" },
    proteins: [],
    diann: {},
    spectrum_links: {},
    extra_metadata: { rt_start: 93.99, rt_stop: 95.99 },
  };
}

const slots = [
  { prsm_index: 100, slot_index: 4, slot_rt_seconds: 5639.4, rt_minutes: 93.99 },
  { prsm_index: 101, slot_index: 5, slot_rt_seconds: 5699.4, rt_minutes: 94.99 },
  { prsm_index: 102, slot_index: 6, slot_rt_seconds: 5759.4, rt_minutes: 95.99 },
];

const slotsPayload = { has_pfmb: true, source_row: 12345, apex_slot: 5, slots };

// PEPTIDE (len 7): b2 -> site 2, y5 -> site 2, z_dot3 -> site 4.
function annotationFor(prsm: number) {
  return {
    prsm_index: prsm,
    peptide: "PEP[+57.021464]TIDE",
    matched_peak_count: 3,
    matched_ions: [
      { ion_type: "y", fragment_ordinal: 5, charge: 1, intensity: 30, observed_neutral_mass: 600.3, theoretical_neutral_mass: 600.3, mass_error_ppm: 0.5, mass_error_da: 0.0003, peak_id: 42 },
      { ion_type: "c", fragment_ordinal: 3, charge: 1, intensity: 30, observed_neutral_mass: 600.3, theoretical_neutral_mass: 600.3, mass_error_ppm: 0.8, mass_error_da: 0.0005, peak_id: 42 },
      { ion_type: "b", fragment_ordinal: 2, charge: 1, intensity: 12345, observed_neutral_mass: 198.1, theoretical_neutral_mass: 198.1, mass_error_ppm: -1.5, mass_error_da: -0.0003, peak_id: 7 },
      { ion_type: "z_dot", fragment_ordinal: 3, charge: 2, intensity: 500, observed_neutral_mass: 360.2, theoretical_neutral_mass: 360.2, mass_error_ppm: 1.2, mass_error_da: 0.0007, peak_id: 99 },
    ],
  };
}

const matrixPayload = {
  peptide: "PEP[+57.021464]TIDE",
  apex_slot: 5,
  slots,
  fragments: [
    { key: "b2", ion_type: "b", fragment_ordinal: 2, occurrence: 3, total_intensity: 30000 },
    { key: "y5", ion_type: "y", fragment_ordinal: 5, occurrence: 2, total_intensity: 50 },
    { key: "c3", ion_type: "c", fragment_ordinal: 3, occurrence: 2, total_intensity: 50 },
    { key: "z_dot3", ion_type: "z_dot", fragment_ordinal: 3, occurrence: 1, total_intensity: 500 },
  ],
  intensity: [
    [12345, 9000, 8655],
    [0, 30, 20],
    [0, 30, 20],
    [0, 500, 0],
  ],
  detected: [
    [true, true, true],
    [true, true, true],
    [false, true, true],
    [false, true, false],
  ],
};

const xicStub = {
  rt: [93.99, 94.99, 95.99],
  intensity: [10, 100, 20],
  precursor_mz: 477.3051,
  precursor_charge: 2,
  ppm: 10,
  rt_apex: 94.99,
  rt_start: 93.99,
  rt_stop: 95.99,
  unit_rt: "min",
  traces: [{ label: "M", isotope_index: 0, target_mz: 477.3051, intensity: [10, 100, 20] }],
};

function spectrumStub(msLevel: 1 | 2) {
  const pfmbMappedMz = [181.1073, 199.1073, 601.3073];
  return {
    scan: msLevel === 2 ? 100 : 99,
    native_id: `scan=${msLevel}`,
    ms_level: msLevel,
    rt_seconds: 94.99 * 60,
    rt_minutes: 94.99,
    mz: msLevel === 2 ? [100, ...pfmbMappedMz, 650, 700] : [100, 200, 300],
    intensity: msLevel === 2 ? [20, 40, 100, 80, 60, 30] : [20, 100, 30],
    precursor: msLevel === 2 ? { selected_mz: 477.3051, charge: 2, isolation_target_mz: 478, isolation_lower: 6.5, isolation_upper: 6.5 } : null,
    matched_ions: msLevel === 2
      ? [
          { ion_type: "y", position: 5, charge: 1, theo_mz: 601.3, exp_mz: 601.3073, ppm: 0.5, intensity: 80 },
          { ion_type: "b", position: 4, charge: 1, theo_mz: 650, exp_mz: 650, ppm: 0, intensity: 60 },
        ]
      : [],
    markers: [],
  };
}

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

interface Counters {
  slots: number;
  matrix: number;
  annotationPrsm: number[];
  productXics: number;
}

async function mockPfmb(
  page: Page,
  opts: { ms2Spectrum?: ReturnType<typeof spectrumStub>; annotationDelayMs?: number } = {},
): Promise<Counters> {
  const counters: Counters = { slots: 0, matrix: 0, annotationPrsm: [], productXics: 0 };
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    if (p === "/api/v1/datasets/demo") return fulfillJson(route, dataset);
    const detailMatch = p.match(/\/datasets\/demo\/matches\/(\d+)$/);
    if (detailMatch) return fulfillJson(route, matchDetail(Number(detailMatch[1])));
    if (/\/matches\/\d+\/ms2-slots$/.test(p)) {
      counters.slots += 1;
      return fulfillJson(route, slotsPayload);
    }
    if (/\/matches\/\d+\/ms2-annotation-matrix$/.test(p)) {
      counters.matrix += 1;
      return fulfillJson(route, matrixPayload);
    }
    const annMatch = p.match(/\/matches\/\d+\/ms2-annotation\/(\d+)$/);
    if (annMatch) {
      counters.annotationPrsm.push(Number(annMatch[1]));
      if (opts.annotationDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, opts.annotationDelayMs));
      }
      return fulfillJson(route, annotationFor(Number(annMatch[1])));
    }
    if (/\/matches\/\d+\/xic$/.test(p)) return fulfillJson(route, xicStub);
    if (/\/matches\/\d+\/spectrum\/ms1$/.test(p)) return fulfillJson(route, spectrumStub(1));
    if (/\/matches\/\d+\/spectrum\/ms2$/.test(p)) {
      if (opts.ms2Spectrum) return fulfillJson(route, opts.ms2Spectrum);
      const requestedRt = Number(url.searchParams.get("rt"));
      const spectrum = spectrumStub(2);
      return fulfillJson(
        route,
        Number.isFinite(requestedRt)
          ? { ...spectrum, rt_minutes: requestedRt, rt_seconds: requestedRt * 60 }
          : spectrum,
      );
    }
    if (/\/matches\/\d+\/product-xics$/.test(p)) {
      counters.productXics += 1;
      return fulfillJson(route, { traces: [] });
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });
  return counters;
}

function ms2Svg(page: Page) {
  return page.locator('svg[aria-label^="MS2 scan #100"]').first();
}

async function clickMs2Mz(page: Page, mz: number) {
  const svg = ms2Svg(page);
  const box = await svg.boundingBox();
  if (!box) throw new Error("MS2 SVG has no bounding box");
  await svg.click({
    position: {
      x: 72 + (box.width - 92) * ((mz - 100) / 600),
      y: 220,
    },
  });
}

async function hoverMs2Mz(page: Page, mz: number) {
  const svg = ms2Svg(page);
  const box = await svg.boundingBox();
  if (!box) throw new Error("MS2 SVG has no bounding box");
  await svg.hover({
    position: {
      x: 72 + (box.width - 92) * ((mz - 100) / 600),
      y: 220,
    },
  });
}

test("PFMB Evidence removes the standalone spectrum and overlays mapped annotations on live MS2", async ({ page }) => {
  const counters = await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const evidence = page.getByTestId("ms2-pfmb-evidence");
  await expect(evidence.getByRole("heading", { name: "MS2 / PFMB Evidence", exact: true })).toBeVisible();
  await expect(evidence.getByRole("heading", { name: "MS2 spectrum", exact: true })).toBeVisible();
  await expect(evidence.getByRole("heading", { name: "Product ion evidence", exact: true })).toBeVisible();
  await expect(evidence.getByRole("heading", { name: "PFMB evidence", exact: true })).toBeVisible();
  await expect(evidence.getByTestId("product-ion-xic-card")).toBeVisible();
  await expect(evidence.getByTestId("live-fragment-row")).toHaveCount(2);

  const card = evidence.getByTestId("pfmb-card");
  const rows = card.getByTestId("pfmb-ion-row");
  await expect(rows).toHaveCount(4);
  await expect(card.getByTestId("pfmb-header")).toContainText(
    "counts and intensity sums are not directly comparable",
  );
  await expect(card.getByTestId("pfmb-quality-summary")).toBeVisible();
  await expect(card.getByTestId("pfmb-heatmap")).toBeVisible();
  await expect(card.getByTestId("pfmb-slot-panel")).toBeVisible();
  await expect(card.getByTestId("pfmb-slot-panel").getByTestId("pfmb-slot-buttons")).toBeVisible();
  await expect(card.getByTestId("pfmb-sequence-coverage")).toBeVisible();
  await expect(card.getByTestId("pfmb-slot-summary")).toBeVisible();
  await expect(card.getByText("Pre-computed PFMB annotation spectrum")).toHaveCount(0);
  await expect(card.getByTestId("pfmb-spectrum-peak")).toHaveCount(0);

  const heatmapBox = await card.getByTestId("pfmb-heatmap").boundingBox();
  const slotPanelBox = await card.getByTestId("pfmb-slot-panel").boundingBox();
  expect(heatmapBox).not.toBeNull();
  expect(slotPanelBox).not.toBeNull();
  expect(slotPanelBox!.x).toBeGreaterThan(heatmapBox!.x + 100);
  expect(Math.abs(slotPanelBox!.y - heatmapBox!.y)).toBeLessThan(80);

  await expect(page.getByTestId("spectrum-annotation-legend")).toContainText("PFMB primary");
  await expect(page.getByTestId("spectrum-annotation-legend")).toContainText("Live fallback");
  await expect(page.getByTestId("external-spectrum-annotation")).toHaveCount(0);

  const svg = ms2Svg(page);
  await expect(svg.locator('line[data-peak-stem="true"]')).toHaveCount(6);
  await expect(svg.locator('line[data-primary-source="pfmb"][data-has-live="true"][data-primary-label="y5"]'))
    .toHaveCount(1);
  await expect(svg.locator('line[data-primary-source="pfmb"][data-primary-label="b2"]')).toHaveCount(1);
  await expect(svg.locator('line[data-primary-source="live"][data-primary-label="b4"]')).toHaveCount(1);
  await expect(svg.locator('line[data-primary-source="pfmb"][data-primary-label="c3"]')).toHaveCount(0);

  await hoverMs2Mz(page, 601.3073);
  await expect(page.getByText("Primary source: PFMB pre-computed")).toBeVisible();
  await expect(page.getByText("Secondary source: Live mzML")).toBeVisible();
  await expect(page.getByText("Live exp m/z 601.3073")).toBeVisible();
  await expect(page.getByText("Series c; position 3; charge 1+")).toBeVisible();

  await clickMs2Mz(page, 601.3073);
  await page.waitForTimeout(250);
  expect(counters.productXics).toBe(0);

  const productResponse = page.waitForResponse((response) => response.url().endsWith("/product-xics"));
  await clickMs2Mz(page, 650);
  await productResponse;
  expect(counters.productXics).toBe(1);

  await svg.locator("xpath=..").getByRole("button", { name: "enlarge" }).click();
  const dialog = page.getByRole("dialog");
  const modalSvg = dialog.locator('svg[aria-label^="MS2 scan #100"]');
  await expect(modalSvg.locator('line[data-peak-stem="true"]')).toHaveCount(6);
  await expect(modalSvg.locator('line[data-primary-source="pfmb"][data-has-live="true"][data-primary-label="y5"]'))
    .toHaveCount(1);
  await expect(dialog.getByTestId("external-spectrum-annotation")).toHaveCount(0);
});

test("unmapped PFMB annotations are not drawn on the live MS2 spectrum", async ({ page }) => {
  await mockPfmb(page, {
    ms2Spectrum: {
      ...spectrumStub(2),
      mz: [100, 200, 300],
      intensity: [20, 100, 30],
    },
  });
  await page.goto("/datasets/demo/matches/1");

  await expect(ms2Svg(page).locator('line[data-primary-source="pfmb"]')).toHaveCount(0);
  await expect(page.getByTestId("ms2-pfmb-unmapped")).toContainText("not drawn");
});

test("heatmap loads with a single matrix request and no per-slot N+1", async ({ page }) => {
  const counters = await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  await expect(card.getByTestId("pfmb-heatmap")).toBeVisible();
  // 4 fragment families x 3 slots = 12 cells, from ONE request.
  await expect(card.getByTestId("pfmb-heatmap-cell")).toHaveCount(12);
  expect(counters.matrix).toBe(1);
  expect(counters.slots).toBe(1);
  // Active-slot annotation is fetched once (apex), never once-per-slot.
  expect(new Set(counters.annotationPrsm).size).toBeLessThanOrEqual(1);
  expect(counters.annotationPrsm).toHaveLength(1);
  expect(counters.annotationPrsm).not.toContain(100);
  expect(counters.annotationPrsm).not.toContain(102);
});

test("heatmap distinguishes detected zero from not detected when metadata exists", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const heatmap = page.getByTestId("pfmb-heatmap");
  await expect(heatmap.getByTestId("pfmb-heatmap-legend")).toContainText("Log intensity");
  await expect(heatmap.getByTestId("pfmb-heatmap-legend")).toContainText("Matched zero intensity");
  await expect(heatmap).toContainText("Columns are PFMB slot RT values in minutes");
  await expect(heatmap.getByTestId("pfmb-heatmap-apex")).toContainText("PFMB apex");
  await expect(heatmap.getByTestId("pfmb-heatmap-rt-label")).toContainText(["93.99", "94.99", "95.99"]);
  await expect(heatmap.getByTestId("pfmb-heatmap-rt-label").first()).toHaveAttribute("data-slot-index", "4");
  await expect(heatmap.getByTestId("pfmb-heatmap-rt-label").first()).toHaveText("93.99");
  await expect(heatmap.locator('[data-family="y5"][data-col="0"]')).toHaveAttribute(
    "data-detection",
    "matched-zero",
  );
  await expect(heatmap.locator('[data-family="c3"][data-col="0"]')).toHaveAttribute(
    "data-detection",
    "not-detected",
  );
});

test("clicking a heatmap cell switches RT and highlights the fragment", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  // Column 0 = slot 4 (rt 93.99); row b2.
  await card.locator('[data-testid="pfmb-heatmap-cell"][data-family="b2"][data-col="0"]').click();

  await expect(card.getByTestId("pfmb-selected-rt")).toContainText("93.99");
  await expect(card.getByTestId("pfmb-ion-row").filter({ hasText: "b2" })).toHaveAttribute("data-highlighted", "true");
  await expect(card.locator('[data-testid="seq-site"][data-site="2"]')).toHaveAttribute("data-highlighted", "true");
});

test("clicking a PFMB slot updates selection without scrolling the page", async ({ page }) => {
  await mockPfmb(page, { annotationDelayMs: 250 });
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  const slotPanel = card.getByTestId("pfmb-slot-panel");
  await expect(card.getByTestId("pfmb-slot-summary")).toContainText("101");
  await slotPanel.scrollIntoViewIfNeeded();
  const before = await page.evaluate(() => window.scrollY);

  await slotPanel.getByRole("button", { name: "Slot 4 | PFMB slot RT 93.99 min", exact: true }).click();

  await expect(card.getByTestId("pfmb-selected-rt")).toContainText("93.99");
  await expect(card.getByTestId("pfmb-heatmap-current-col")).toHaveAttribute("data-col", "0");
  await expect(card.getByTestId("pfmb-slot-summary")).toContainText("100");
  const after = await page.evaluate(() => window.scrollY);
  expect(Math.abs(after - before)).toBeLessThanOrEqual(10);
});

test("heatmap tooltip reports ion, slot RT, intensity, and detection state", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const cell = page.locator('[data-testid="pfmb-heatmap-cell"][data-family="y5"][data-col="0"]');
  await cell.hover();
  const tooltip = page.getByTestId("pfmb-heatmap-tooltip");
  await expect(tooltip).toContainText("y5");
  await expect(tooltip).toContainText("PFMB slot RT 93.9900 min");
  await expect(tooltip).toContainText("Matched peak with zero intensity");
});

test("clicking a covered sequence site highlights the table row", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  await expect(card.getByTestId("pfmb-sequence-coverage")).toBeVisible();
  await expect(card.getByTestId("seq-residue")).toHaveCount(7);
  await expect(card.getByTestId("pfmb-sequence-coverage")).not.toContainText("[+57.021464]");
  await expect(card.locator('[data-testid="seq-residue"][data-index="1"]')).toHaveAttribute(
    "title",
    "Residue P, index 1",
  );
  await expect(card.locator('[data-testid="seq-site"][data-site="4"]')).toHaveAttribute(
    "title",
    /Cleavage position 4; supported ion series: z\.; matched ions: z\.3\^2\+/,
  );

  // Site 4 is covered only by z_dot3.
  await card.locator('[data-testid="seq-site"][data-site="4"]').click();
  await expect(card.getByTestId("pfmb-ion-row").filter({ hasText: "z.3" })).toHaveAttribute("data-highlighted", "true");
  await expect(card.getByTestId("pfmb-ion-row").filter({ hasText: "b2" })).toHaveAttribute("data-highlighted", "false");
});

test("changing match resets PFMB highlight state", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  await card.getByTestId("pfmb-ion-row").filter({ hasText: "b2" }).click();

  await page.evaluate(() => {
    window.history.pushState({}, "", "/datasets/demo/matches/2");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });

  await expect(page).toHaveURL(/\/datasets\/demo\/matches\/2$/);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(card.locator('[data-testid="pfmb-ion-row"][data-highlighted="true"]')).toHaveCount(0);
});
