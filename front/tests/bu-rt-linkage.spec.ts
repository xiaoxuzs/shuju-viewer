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

// Slots at 93.99 / 94.99 (apex) / 95.99 minutes.
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

const matrixPayload = {
  peptide: "PEPTIDE",
  apex_slot: 5,
  slots: slotsPayload.slots,
  fragments: [{ key: "y5", ion_type: "y", fragment_ordinal: 5, occurrence: 3, total_intensity: 3000 }],
  intensity: [[1000, 1000, 1000]],
  slot_summary: slotsPayload.slots.map((slot) => ({
    prsm_index: slot.prsm_index,
    slot_index: slot.slot_index,
    rt_minutes: slot.rt_minutes,
    matched_peak_count: 1,
    matched_ion_count: 1,
    total_intensity: 1000,
  })),
};

function annotationFor(prsm: number) {
  return {
    prsm_index: prsm,
    peptide: "PEPTIDE",
    matched_peak_count: 1,
    matched_ions: [
      {
        ion_type: "y",
        fragment_ordinal: 5,
        charge: 1,
        intensity: 1000,
        observed_neutral_mass: 600.3,
        theoretical_neutral_mass: 600.3,
        mass_error_ppm: 0.5,
        mass_error_da: 0.0003,
        peak_id: 42,
      },
    ],
  };
}

// XIC points at 93.0 / 94.0 / 94.99 / 96.5 minutes (domain is exactly [min, max]).
const xicStub = {
  rt: [93.0, 94.0, 94.99, 96.5],
  intensity: [10, 60, 100, 5],
  precursor_mz: 477.3051,
  precursor_charge: 2,
  ppm: 10,
  rt_apex: 94.99,
  rt_start: 93.99,
  rt_stop: 95.99,
  unit_rt: "min",
  traces: [{ label: "M", isotope_index: 0, target_mz: 477.3051, intensity: [10, 60, 100, 5] }],
};

function spectrumStub(msLevel: 1 | 2, rt: number) {
  return {
    scan: Math.round(rt * 100),
    native_id: `scan=${Math.round(rt * 100)}`,
    ms_level: msLevel,
    rt_seconds: rt * 60,
    rt_minutes: rt,
    mz: [100, 200, 300],
    intensity: [20, 100, 30],
    precursor:
      msLevel === 2
        ? { selected_mz: 477.3051, charge: 2, isolation_target_mz: 478, isolation_lower: 6.5, isolation_upper: 6.5 }
        : null,
    matched_ions:
      msLevel === 2
        ? [{
            ion_type: "y",
            position: 5,
            charge: 1,
            theo_mz: 200,
            exp_mz: 200,
            ppm: 0,
            intensity: 100,
          }]
        : [],
    markers: [],
  };
}

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockRt(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    if (p === "/api/v1/datasets/demo") return fulfillJson(route, dataset);
    if (p === "/api/v1/datasets/demo/matches/1") return fulfillJson(route, matchDetail());
    if (p.endsWith("/matches/1/xic")) return fulfillJson(route, xicStub);
    if (p.endsWith("/matches/1/spectrum/ms1")) return fulfillJson(route, spectrumStub(1, 94.99));
    if (p.endsWith("/matches/1/spectrum/ms2")) {
      const rtParam = url.searchParams.get("rt");
      const rt = rtParam ? Number(rtParam) : 94.99;
      return fulfillJson(route, spectrumStub(2, rt));
    }
    if (p.endsWith("/matches/1/ms2-slots")) return fulfillJson(route, slotsPayload);
    if (p.endsWith("/matches/1/ms2-annotation-matrix")) return fulfillJson(route, matrixPayload);
    const ann = p.match(/\/matches\/1\/ms2-annotation\/(\d+)$/);
    if (ann) return fulfillJson(route, annotationFor(Number(ann[1])));
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });
}

function ms2HasRt(rt: string) {
  return (request: { url(): string }) => {
    const u = new URL(request.url());
    return u.pathname.endsWith("/matches/1/spectrum/ms2") && u.searchParams.get("rt") === rt;
  };
}

test("clicking a PFMB slot drives the live MS2 scan and shows the RT everywhere", async ({ page }) => {
  await mockRt(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  await expect(card).toBeVisible();
  // Default (no RT selected) => apex slot 5 / prsm 101.
  await expect(card.getByTestId("pfmb-slot-summary")).toContainText("101");

  const ms2Request = page.waitForRequest(ms2HasRt("93.99"));
  await card.getByRole("button", { name: "Slot 4 | PFMB slot RT 93.99 min", exact: true }).click();
  await ms2Request;

  // Live MS2 header reflects the requested RT.
  await expect(page.getByTestId("ms2-current-rt")).toContainText("MS2 scan RT: 93.9900 min");
  // XIC card shows the same RT, marked as coming from the PFMB slot.
  await expect(page.getByTestId("xic-selected-rt")).toContainText("93.9900");
  await expect(page.getByTestId("xic-selected-rt")).toContainText("Current inspected RT");
  await expect(page.getByTestId("xic-selected-rt")).toContainText("from PFMB slot");
  // PFMB selection moved to slot 4 / prsm 100.
  await expect(card.getByTestId("pfmb-slot-summary")).toContainText("100");
  await expect(card.getByRole("button", { name: "Slot 4 | PFMB slot RT 93.99 min", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(card.getByTestId("pfmb-slot-summary")).toContainText("PFMB slot RT");
  await expect(card.getByRole("button", { name: /PFMB slot RT 94.99 min \| PFMB apex/ })).toBeVisible();
});

test("live mzML and pre-computed PFMB evidence stay visibly distinct", async ({ page }) => {
  await mockRt(page);
  await page.goto("/datasets/demo/matches/1");

  await expect(page.getByRole("heading", { name: "Live mzML MS2 matching" })).toBeVisible();
  await expect(page.getByText("Matched fragments are calculated from the selected mzML MS2 scan.", {
    exact: false,
  })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Live mzML matched b/y fragments (1)" })).toBeVisible();

  const card = page.getByTestId("pfmb-card");
  await expect(card.getByRole("heading", { name: "Pre-computed PFMB annotation" })).toBeVisible();
  await expect(card).toContainText("counts and intensity sums are not directly comparable");
  await expect(card.getByRole("heading", {
    name: "Pre-computed PFMB matched fragments (1)",
  })).toBeVisible();
});

test("clicking an XIC point selects the nearest PFMB slot", async ({ page }) => {
  await mockRt(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  await expect(card).toBeVisible();

  const xicSvg = page
    .locator('svg[aria-label="Retention Time (min) versus MS1 intensity at isotope m/z"]')
    .first();
  const box = await xicSvg.boundingBox();
  if (!box) throw new Error("XIC SVG has no bounding box");
  // Target the 94.0 min point: fraction = (94.0 - 93.0) / (96.5 - 93.0).
  const fraction = (94.0 - 93.0) / (96.5 - 93.0);
  const ms2Request = page.waitForRequest((request) => {
    const u = new URL(request.url());
    return u.pathname.endsWith("/matches/1/spectrum/ms2") && u.searchParams.has("rt");
  });
  await xicSvg.click({ position: { x: 72 + (box.width - 92) * fraction, y: box.height / 2 } });
  await ms2Request;

  // 94.0 is within tolerance of slot 4 (93.99) => PFMB jumps to prsm 100, no hint.
  await expect(card.getByTestId("pfmb-selected-rt")).toBeVisible();
  await expect(card.getByTestId("pfmb-selected-rt")).toContainText(
    "Current inspected RT: 94.0000 min from XIC selection",
  );
  await expect(card.getByTestId("pfmb-rt-out-of-tolerance")).toHaveCount(0);
  await expect(card.getByTestId("pfmb-slot-summary")).toContainText("100");
  await expect(card.getByRole("button", { name: "Slot 4 | PFMB slot RT 93.99 min", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("an XIC RT beyond tolerance is not force-linked to a slot", async ({ page }) => {
  await mockRt(page);
  await page.goto("/datasets/demo/matches/1");

  const card = page.getByTestId("pfmb-card");
  await expect(card).toBeVisible();

  const xicSvg = page
    .locator('svg[aria-label="Retention Time (min) versus MS1 intensity at isotope m/z"]')
    .first();
  const box = await xicSvg.boundingBox();
  if (!box) throw new Error("XIC SVG has no bounding box");
  // Click near the 96.5 min point (nearest slot 95.99 is 0.51 min away > 0.5 tolerance).
  const ms2Request = page.waitForRequest((request) => {
    const u = new URL(request.url());
    return u.pathname.endsWith("/matches/1/spectrum/ms2") && u.searchParams.has("rt");
  });
  await xicSvg.click({ position: { x: 72 + (box.width - 92) * 0.95, y: box.height / 2 } });
  await ms2Request;

  await expect(card.getByTestId("pfmb-rt-out-of-tolerance")).toBeVisible();
  // Falls back to the apex slot (prsm 101), not the far slot.
  await expect(card.getByTestId("pfmb-slot-summary")).toContainText("101");
  await expect(card.getByTestId("pfmb-heatmap-current-col")).toHaveAttribute("data-col", "1");
  await expect(card.locator('[data-testid="pfmb-trend-point"][data-current="true"]')).toHaveAttribute(
    "data-slot",
    "5",
  );
});
