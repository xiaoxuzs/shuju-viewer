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
  return {
    scan: msLevel === 2 ? 100 : 99,
    native_id: `scan=${msLevel}`,
    ms_level: msLevel,
    rt_seconds: 94.99 * 60,
    rt_minutes: 94.99,
    mz: [100, 200, 300],
    intensity: [20, 100, 30],
    precursor: msLevel === 2 ? { selected_mz: 477.3051, charge: 2, isolation_target_mz: 478, isolation_lower: 6.5, isolation_upper: 6.5 } : null,
    matched_ions: [],
    markers: [],
  };
}

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

interface Counters {
  matrix: number;
  annotationPrsm: number[];
}

async function mockPfmb(page: Page): Promise<Counters> {
  const counters: Counters = { matrix: 0, annotationPrsm: [] };
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    if (p === "/api/v1/datasets/demo") return fulfillJson(route, dataset);
    const detailMatch = p.match(/\/datasets\/demo\/matches\/(\d+)$/);
    if (detailMatch) return fulfillJson(route, matchDetail(Number(detailMatch[1])));
    if (/\/matches\/\d+\/ms2-slots$/.test(p)) return fulfillJson(route, slotsPayload);
    if (/\/matches\/\d+\/ms2-annotation-matrix$/.test(p)) {
      counters.matrix += 1;
      return fulfillJson(route, matrixPayload);
    }
    const annMatch = p.match(/\/matches\/\d+\/ms2-annotation\/(\d+)$/);
    if (annMatch) {
      counters.annotationPrsm.push(Number(annMatch[1]));
      return fulfillJson(route, annotationFor(Number(annMatch[1])));
    }
    if (/\/matches\/\d+\/xic$/.test(p)) return fulfillJson(route, xicStub);
    if (/\/matches\/\d+\/spectrum\/ms1$/.test(p)) return fulfillJson(route, spectrumStub(1));
    if (/\/matches\/\d+\/spectrum\/ms2$/.test(p)) return fulfillJson(route, spectrumStub(2));
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });
  return counters;
}

test("spectrum draws one physical peak for duplicate peak_id annotations", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  const peaks = card.getByTestId("pfmb-spectrum-peak");
  const rows = card.getByTestId("pfmb-ion-row");
  await expect(rows).toHaveCount(4);
  await expect(peaks).toHaveCount(3);

  const sharedPeak = card.locator('[data-testid="pfmb-spectrum-peak"][data-peak-id="42"]');
  await expect(sharedPeak).toHaveCount(1);
  await expect(sharedPeak).toHaveAttribute("data-families", "y5,c3");
});

test("heatmap loads with a single matrix request and no per-slot N+1", async ({ page }) => {
  const counters = await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  await expect(card.getByTestId("pfmb-heatmap")).toBeVisible();
  // 4 fragment families x 3 slots = 12 cells, from ONE request.
  await expect(card.getByTestId("pfmb-heatmap-cell")).toHaveCount(12);
  expect(counters.matrix).toBe(1);
  // Active-slot annotation is fetched once (apex), never once-per-slot.
  expect(new Set(counters.annotationPrsm).size).toBeLessThanOrEqual(1);
  expect(counters.annotationPrsm).not.toContain(100);
  expect(counters.annotationPrsm).not.toContain(102);
});

test("clicking a heatmap cell switches RT and highlights the fragment", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  // Column 0 = slot 4 (rt 93.99); row b2.
  await card.locator('[data-testid="pfmb-heatmap-cell"][data-family="b2"][data-col="0"]').click();

  await expect(card.getByTestId("pfmb-selected-rt")).toContainText("93.99");
  await expect(card.getByTestId("pfmb-ion-row").filter({ hasText: "b2" })).toHaveAttribute("data-highlighted", "true");
});

test("clicking a covered sequence site highlights the table row", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  await expect(card.getByTestId("pfmb-sequence-coverage")).toBeVisible();
  await expect(card.getByTestId("seq-residue")).toHaveCount(7);
  await expect(card.getByTestId("pfmb-sequence-coverage")).not.toContainText("[+57.021464]");

  // Site 4 is covered only by z_dot3.
  await card.locator('[data-testid="seq-site"][data-site="4"]').click();
  await expect(card.getByTestId("pfmb-ion-row").filter({ hasText: "z.3" })).toHaveAttribute("data-highlighted", "true");
  await expect(card.getByTestId("pfmb-ion-row").filter({ hasText: "b2" })).toHaveAttribute("data-highlighted", "false");
});

test("clicking a spectrum peak highlights the matching table row", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  const svg = card.locator('svg[aria-label^="Pre-computed PFMB annotation spectrum"]');
  const box = await svg.boundingBox();
  if (!box) throw new Error("PFMB spectrum SVG has no bounding box");
  // Neutral-mass domain [190.056, 608.344]; z_dot3 (360.2) sits at ~0.407 of the
  // inner width (margins left=72, right=20). y is mid-plot (no vertical gate).
  await svg.click({ position: { x: 72 + (box.width - 92) * 0.4068, y: 180 } });

  await expect(card.getByTestId("pfmb-ion-row").filter({ hasText: "z.3" })).toHaveAttribute("data-highlighted", "true");
});

test("mass-mode toggle switches the spectrum axis label", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  const svg = card.locator('svg[aria-label^="Pre-computed PFMB annotation spectrum"]');
  await expect(svg).toContainText("neutral mass (Da)");

  await card.getByTestId("pfmb-mass-mode").getByRole("button", { name: "m/z" }).click();
  await expect(svg).toContainText("m/z");
});

test("changing match resets PFMB highlight, mass mode and fullscreen state", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  await card.getByTestId("pfmb-ion-row").filter({ hasText: "b2" }).click();
  await card.getByTestId("pfmb-mass-mode").getByRole("button", { name: "m/z" }).click();
  await card.getByRole("button", { name: "enlarge" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();

  await page.evaluate(() => {
    window.history.pushState({}, "", "/datasets/demo/matches/2");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });

  await expect(page).toHaveURL(/\/datasets\/demo\/matches\/2$/);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(card.getByTestId("pfmb-mass-mode").getByRole("button", { name: "neutral mass" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(card.locator('[data-testid="pfmb-ion-row"][data-highlighted="true"]')).toHaveCount(0);
});
