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
    run: {
      run_id: 10,
      file_name: "run.mzML",
      raw_format: "mzml",
      file_path: "run.mzML",
      diann_run_name: "run",
    },
    rt_window: { rt_start: 93.99, rt_stop: 95.99, rt_apex: 94.99, unit: "min" },
    proteins: [],
    diann: {},
    spectrum_links: {},
    extra_metadata: { rt_start: 93.99, rt_stop: 95.99 },
  };
}

const slotsPayload = {
  has_pfmb: true,
  source_row: 12345,
  apex_slot: 5,
  slots: [
    { prsm_index: 100, slot_index: 4, slot_rt_seconds: 5639.4, rt_minutes: 93.99 },
    { prsm_index: 101, slot_index: 5, slot_rt_seconds: 5699.4, rt_minutes: 94.99 },
    { prsm_index: 102, slot_index: 6, slot_rt_seconds: 5759.4, rt_minutes: 95.99 },
  ],
};

function annotationFor(prsm: number) {
  if (prsm === 102) {
    return { prsm_index: 102, peptide: "PEPTIDE", matched_peak_count: 0, matched_ions: [] };
  }
  // matched_peak_count (2) intentionally differs from matched_ions length (3)
  // so the summary clearly distinguishes the two counts.
  return {
    prsm_index: prsm,
    peptide: "PEPTIDE",
    matched_peak_count: 2,
    matched_ions: [
      // intensity 0 is legal data and must stay visible.
      {
        ion_type: "y",
        fragment_ordinal: 5,
        charge: 1,
        intensity: 0,
        observed_neutral_mass: 600.3,
        theoretical_neutral_mass: 600.3,
        mass_error_ppm: 0.5,
        mass_error_da: 0.0003,
        peak_id: 42,
      },
      // obs == theo, but stored ppm is -900 (isotope peak): UI must show the field value.
      {
        ion_type: "b",
        fragment_ordinal: 2,
        charge: 1,
        intensity: 12345,
        observed_neutral_mass: 198.1,
        theoretical_neutral_mass: 198.1,
        mass_error_ppm: -900,
        mass_error_da: 1.0033,
        peak_id: 7,
      },
      {
        ion_type: "z_dot",
        fragment_ordinal: 3,
        charge: 2,
        intensity: 500,
        observed_neutral_mass: 360.2,
        theoretical_neutral_mass: 360.2,
        mass_error_ppm: 1.2,
        mass_error_da: 0.0007,
        peak_id: 99,
      },
    ],
  };
}

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
    precursor:
      msLevel === 2
        ? {
            selected_mz: 477.3051,
            charge: 2,
            isolation_target_mz: 478,
            isolation_lower: 6.5,
            isolation_upper: 6.5,
          }
        : null,
    matched_ions: [],
    markers: [],
  };
}

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

interface Opts {
  slotsStatus?: number;
  annotationStatus?: number;
  slots?: unknown;
}

async function mockPfmb(page: Page, opts: Opts = {}) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    if (p === "/api/v1/datasets/demo") return fulfillJson(route, dataset);
    if (p === "/api/v1/datasets/demo/matches/1") return fulfillJson(route, matchDetail());
    if (p.endsWith("/matches/1/ms2-slots")) {
      if (opts.slotsStatus && opts.slotsStatus >= 400) {
        return route.fulfill({ status: opts.slotsStatus, contentType: "application/json", body: "{}" });
      }
      return fulfillJson(route, opts.slots ?? slotsPayload);
    }
    const annMatch = p.match(/\/matches\/1\/ms2-annotation\/(\d+)$/);
    if (annMatch) {
      if (opts.annotationStatus && opts.annotationStatus >= 400) {
        return route.fulfill({ status: opts.annotationStatus, contentType: "application/json", body: "{}" });
      }
      return fulfillJson(route, annotationFor(Number(annMatch[1])));
    }
    if (p.endsWith("/matches/1/xic")) return fulfillJson(route, xicStub);
    if (p.endsWith("/matches/1/spectrum/ms1")) return fulfillJson(route, spectrumStub(1));
    if (p.endsWith("/matches/1/spectrum/ms2")) return fulfillJson(route, spectrumStub(2));
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });
}

test("defaults to the apex slot", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  await expect(card).toBeVisible();
  const apex = card.getByRole("button", { name: "Slot 5 | 94.99 min | Apex", exact: true });
  await expect(apex).toHaveAttribute("aria-pressed", "true");
  // Apex slot is prsm 101 -> annotation summary reflects it.
  await expect(card.getByTestId("pfmb-slot-summary")).toContainText("101");
});

test("slot buttons show index, RT and Apex state", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  await expect(card.getByRole("button", { name: "Slot 5 | 94.99 min | Apex", exact: true })).toBeVisible();
  const nonApex = card.getByRole("button", { name: "Slot 4 | 93.99 min", exact: true });
  await expect(nonApex).toBeVisible();
  await expect(nonApex).not.toContainText("Apex");
});

test("summary distinguishes matched peaks from matched ion rows", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const summary = page.getByTestId("pfmb-card").getByTestId("pfmb-slot-summary");
  await expect(summary.locator("div", { hasText: "Matched peaks (by peak_id)" })).toContainText("2");
  await expect(summary.locator("div", { hasText: "Matched ion rows" })).toContainText("3");
  await expect(summary.locator("div", { hasText: "Zero-intensity rows" })).toContainText("1");
});

test("zero-intensity ion row stays visible (not filtered)", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  const rows = card.getByTestId("pfmb-ion-row");
  await expect(rows).toHaveCount(3);
  await expect(rows.filter({ hasText: "y5" })).toHaveCount(1);
});

test("table headers use neutral mass, not m/z", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  await expect(card.getByText("Theoretical neutral mass")).toBeVisible();
  await expect(card.getByText("Observed neutral mass")).toBeVisible();
  await expect(card.getByText("Mass error (ppm)")).toBeVisible();
  await expect(card.getByText("Mass error (Da)")).toBeVisible();
  // The fragment table itself must stay neutral-mass based (the m/z mention
  // elsewhere is the spectrum chart's mass-mode toggle, which is expected).
  await expect(card.locator("table").getByText("m/z")).toHaveCount(0);
});

test("ppm column shows the backend field value, not a recomputed value", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  // b2 has obs == theo (recompute would give 0) but stored ppm is -900.
  const b2 = card.getByTestId("pfmb-ion-row").filter({ hasText: "b2" });
  await expect(b2).toContainText("-900");
});

test("table supports client-side sorting", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  const rows = card.getByTestId("pfmb-ion-row");
  // Default order: ion type -> ordinal -> charge => b2, y5, z.3
  await expect(rows.nth(0)).toContainText("b2");
  await expect(rows.nth(1)).toContainText("y5");
  await expect(rows.nth(2)).toContainText("z.3");

  const intensitySort = card.getByRole("button", { name: "Sort by Intensity" });
  await intensitySort.click();
  await expect(rows.nth(0)).toContainText("y5"); // intensity 0 first (asc)
  await intensitySort.click();
  await expect(rows.nth(0)).toContainText("b2"); // intensity 12345 first (desc)
});

test("empty matched_ions shows an explicit empty state", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  await card.getByRole("button", { name: "Slot 6 | 95.99 min", exact: true }).click();
  await expect(card.getByTestId("pfmb-empty-ions")).toBeVisible();
  await expect(card.getByTestId("pfmb-empty-ions")).toContainText("no matched fragment ions");
});

test("slots request failure shows an error state inside the card", async ({ page }) => {
  await mockPfmb(page, { slotsStatus: 500 });
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  await expect(card.getByTestId("pfmb-slots-error")).toBeVisible();
});

test("annotation request failure shows an error state inside the card", async ({ page }) => {
  await mockPfmb(page, { annotationStatus: 500 });
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  await expect(card.getByTestId("pfmb-annotation-error")).toBeVisible();
});

test("capability present but no slot shows a message, not a hidden card", async ({ page }) => {
  await mockPfmb(page, {
    slots: { has_pfmb: true, source_row: null, apex_slot: null, slots: [] },
  });
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  await expect(card.getByTestId("pfmb-no-slots")).toBeVisible();
});

test("PFMB card has no known mojibake glyphs", async ({ page }) => {
  await mockPfmb(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  await expect(card).toBeVisible();
  const text = await card.innerText();
  for (const glyph of ["z\u2022", "\u2605", "\u0394", "\u2194", "\u00b7"]) {
    expect(text).not.toContain(glyph);
  }
});
