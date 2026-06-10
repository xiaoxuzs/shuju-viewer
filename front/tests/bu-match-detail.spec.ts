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
  return {
    scan,
    native_id: `scan=${scan}`,
    ms_level: msLevel,
    rt_seconds: rt * 60,
    rt_minutes: rt,
    mz: msLevel === 2 ? [100, 175.119, 300] : [400, 477.3051, 600],
    intensity: msLevel === 2 ? [20, 100, 30] : [10, 100, 20],
    precursor: msLevel === 2
      ? {
          selected_mz: 477.3051,
          charge: 2,
          isolation_target_mz: 478,
          isolation_lower: 6.5,
          isolation_upper: 6.5,
        }
      : null,
    matched_ions: msLevel === 2
      ? [
          {
            ion_type: "y",
            position: 5,
            charge: 1,
            theo_mz: 175.119,
            exp_mz: 175.119,
            ppm: 0,
            intensity: 100,
          },
        ]
      : [],
    markers: msLevel === 1 ? [{ mz: 477.3051, label: "precursor", charge: 2 }] : [],
  };
}

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockMzmlMatch(page: Page, matchDelayMs = 0, scanNumber: number | null | undefined = -1) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/datasets/demo") return fulfillJson(route, dataset);
    if (url.pathname === "/api/v1/datasets/demo/matches/1") {
      if (matchDelayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, matchDelayMs));
      }
      return fulfillJson(route, matchDetail("mzml", scanNumber));
    }
    if (url.pathname.endsWith("/matches/1/xic")) return fulfillJson(route, xic);
    if (url.pathname.endsWith("/matches/1/spectrum/ms1")) return fulfillJson(route, spectrum(500, 92.45, 1));
    if (url.pathname.endsWith("/matches/1/spectrum/ms2")) {
      return fulfillJson(route, url.searchParams.has("rt") ? spectrum(67727, 93.01, 2) : spectrum(67726, 92.46, 2));
    }
    if (url.pathname.endsWith("/matches/1/product-xic")) {
      return fulfillJson(route, {
        curve_type: "PRODUCT_ION_XIC",
        x_axis: "rt",
        y_axis: "intensity",
        unit_rt: "min",
        product_mz: Number(url.searchParams.get("mz")),
        ppm: Number(url.searchParams.get("ppm")),
        precursor_mz: 477.3051,
        isolation_filter: true,
        points: [
          { rt: 92.15, intensity: 20, scan: 67720 },
          { rt: 92.46, intensity: 100, scan: 67726 },
        ],
      });
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
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

test("precursor XIC selects MS2 and matched ion opens product XIC", async ({ page }) => {
  await mockMzmlMatch(page);
  await page.goto("/datasets/demo/matches/1");

  await expect(page.getByRole("heading", { name: "Precursor XIC" })).toBeVisible();
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

  const ms2Svg = page.locator('svg[aria-label^="MS2 scan #67727"]');
  const ms2Box = await ms2Svg.boundingBox();
  if (!ms2Box) throw new Error("MS2 SVG has no bounding box");
  const productRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname.endsWith("/product-xic") && url.searchParams.get("mz") === "175.119";
  });
  await ms2Svg.click({
    position: {
      x: 72 + (ms2Box.width - 92) * (75.119 / 200),
      y: 24,
    },
  });
  await productRequest;
  await expect(page.getByText("Product ion XIC: y5 / m/z 175.1190")).toBeVisible();

  await page.getByRole("button", { name: "clear" }).click();
  await expect(page.getByText("Product ion XIC: y5 / m/z 175.1190")).toBeHidden();
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
    ) {
      matchLevelCalls += 1;
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });

  await page.goto("/datasets/demo/matches/1");

  await expect(page.getByText("Bruker .d match-level Precursor XIC and MS1/MS2 spectra are not supported.")).toBeVisible();
  expect(matchLevelCalls).toBe(0);
});
