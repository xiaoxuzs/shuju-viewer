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

function matchDetail() {
  return {
    id: 1,
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

// Modified PEPTIDE still has len 7 after stripping the bracket annotation.
function annotationFor(prsm: number) {
  return {
    prsm_index: prsm,
    peptide: "PEP[+57.021464]TIDE",
    matched_peak_count: 3,
    matched_ions: [
      { ion_type: "y", fragment_ordinal: 5, charge: 1, intensity: 30, observed_neutral_mass: 600.3, theoretical_neutral_mass: 600.3, mass_error_ppm: 0.5, mass_error_da: 0.0003, peak_id: 42 },
      { ion_type: "c", fragment_ordinal: 3, charge: 1, intensity: 30, observed_neutral_mass: 600.3, theoretical_neutral_mass: 600.3, mass_error_ppm: 0.5, mass_error_da: 0.0003, peak_id: 42 },
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
  slot_summary: [
    { prsm_index: 100, slot_index: 4, rt_minutes: 93.99, matched_peak_count: 2, matched_ion_count: 3, total_intensity: 100 },
    { prsm_index: 101, slot_index: 5, rt_minutes: 94.99, matched_peak_count: 3, matched_ion_count: 4, total_intensity: 12875 },
    { prsm_index: 102, slot_index: 6, rt_minutes: 95.99, matched_peak_count: 1, matched_ion_count: 1, total_intensity: 20 },
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

async function mockPfmb(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    if (p === "/api/v1/datasets/demo") return fulfillJson(route, dataset);
    if (p === "/api/v1/datasets/demo/matches/1") return fulfillJson(route, matchDetail());
    if (p.endsWith("/matches/1/ms2-slots")) return fulfillJson(route, slotsPayload);
    if (p.endsWith("/matches/1/ms2-annotation-matrix")) return fulfillJson(route, matrixPayload);
    const annMatch = p.match(/\/matches\/1\/ms2-annotation\/(\d+)$/);
    if (annMatch) return fulfillJson(route, annotationFor(Number(annMatch[1])));
    if (p.endsWith("/matches/1/xic")) return fulfillJson(route, xicStub);
    if (p.endsWith("/matches/1/spectrum/ms1")) return fulfillJson(route, spectrumStub(1));
    if (p.endsWith("/matches/1/spectrum/ms2")) return fulfillJson(route, spectrumStub(2));
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });
}

test("quality summary leads with the match-rate disclaimer", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  const disclaimer = card.getByTestId("pfmb-quality-disclaimer");
  await expect(disclaimer).toBeVisible();
  await expect(disclaimer).toContainText("not identification accuracy");
});

test("fragment coverage strips modifications before counting cleavage sites", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const coverage = page.getByTestId("pfmb-card").getByTestId("pfmb-quality-coverage");
  await expect(coverage.getByTestId("pfmb-coverage-pct")).toHaveText("50%");
  await expect(coverage).toContainText("3/6 cleavage sites");
});

test("ppm median and series counts are computed from the slot", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  await expect(card.getByTestId("pfmb-ppm-median")).toHaveText("0.5");

  const series = card.getByTestId("pfmb-quality-series");
  await expect(series.locator('[data-series="b"]')).toContainText("1");
  await expect(series.locator('[data-series="y"]')).toContainText("1");
  await expect(series.locator('[data-series="z_dot"]')).toContainText("1");
  await expect(series.locator('[data-series="c"]')).toContainText("1");
});

test("unique peak intensity counts duplicate annotations once", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const intensity = page.getByTestId("pfmb-card").getByTestId("pfmb-quality-intensity");
  await expect(intensity).toContainText("not a true TIC");
  await expect(intensity.getByTestId("pfmb-unique-peak-intensity")).toHaveText("12,875");
  await expect(intensity).toContainText("3 unique peak IDs");
});

test("per-slot trend renders all slots and a point click syncs RT", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  const points = card.getByTestId("pfmb-trend-point");
  await expect(points).toHaveCount(3);
  await expect(card.locator('[data-testid="pfmb-trend-point"][data-apex="true"]')).toHaveAttribute("data-slot", "5");

  await card.locator('[data-testid="pfmb-trend-point"][data-slot="4"]').click();
  await expect(card.getByTestId("pfmb-selected-rt")).toContainText("93.99");
});
