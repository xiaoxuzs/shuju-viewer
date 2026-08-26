import { expect, test, type Page, type Route } from "@playwright/test";

const dataset = {
  id: 40,
  slug: "demo",
  name: "BU demo",
  description: null,
  source_path: "demo",
  capabilities: {},
  analysis_mode: "BOTTOM_UP",
  status: "ready",
  source_software: "DIA-NN",
  extra_metadata: {},
  bu_runs: [],
  created_at: "2026-06-11T00:00:00Z",
  updated_at: null,
  cutoffs: [],
};

const overview = {
  dataset_id: 40,
  slug: "demo",
  name: "BU demo",
  analysis_mode: "BOTTOM_UP",
  source_software: "DIA-NN",
  status: "ready",
  source_root: "demo",
  q_value_cutoff: 0.01,
  counts: {
    matches: 3,
    peptides: 2,
    proteins: 1,
    protein_groups: 1,
    runs: 1,
    decoy_matches: 0,
  },
  qc: { by_run: [], aggregated: {} },
  runs: [{
    run_id: 39,
    file_name: "run.mzML",
    raw_format: "mzml",
    diann_run_name: "run",
    match_count: 3,
    has_im: false,
  }],
  capabilities: {},
  import_stats: {},
  created_at: "2026-06-11T00:00:00Z",
};

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockOverview(page: Page, chromatogramDetail: unknown, chromatogramStatus = 409) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/datasets/demo") return fulfillJson(route, dataset);
    if (url.pathname === "/api/v1/datasets/demo/overview") return fulfillJson(route, overview);
    if (url.pathname.endsWith("/runs/39/chromatogram")) {
      return chromatogramStatus === 409
        ? fulfillJson(route, { detail: chromatogramDetail }, 409)
        : fulfillJson(route, chromatogramDetail, chromatogramStatus);
    }
    if (url.pathname.endsWith("/overview/rt-mz")) {
      return fulfillJson(route, {
        unit_rt: "min",
        unit_mz: "Th",
        rt_edges: [1, 2],
        mz_edges: [400, 500],
        counts: [[3]],
        max_count: 3,
        total_points: 3,
        run_id: 39,
      });
    }
    return fulfillJson(route, {}, 404);
  });
}

test("chromatogram missing state stays local and shows the backfill command", async ({ page }) => {
  await mockOverview(page, "chromatogram_summary_missing");
  await page.goto("/datasets/demo");

  await expect(page.getByText("Derived chromatogram data is not ready.")).toBeVisible();
  await expect(page.getByText(
    "python scripts/backfill_dataset_derived_data.py --dataset-id 40 --run-id 39",
  )).toBeVisible();
  await expect(page.getByRole("img", { name: "RT by precursor m/z heatmap" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Runs" })).toBeVisible();
});

test("chromatogram stale state is distinct from missing", async ({ page }) => {
  await mockOverview(page, "chromatogram_summary_stale");
  await page.goto("/datasets/demo");

  await expect(page.getByText("Derived chromatogram data is stale.")).toBeVisible();
  await expect(page.getByText("Derived chromatogram data is not ready.")).toHaveCount(0);
});

test("chromatogram billion-scale ticks use a single y-axis scale label", async ({ page }) => {
  await mockOverview(page, {
    type: "tic",
    unit_rt: "min",
    rt: [1, 2, 3],
    intensity: [0, 6e9, 12e9],
    downsampled: false,
    point_count_original: 3,
  }, 200);
  await page.goto("/datasets/demo");

  await expect(page.locator("svg text[data-testid='y-axis-scale-label']")).toHaveText("×10⁹");
  await expect(page.locator("svg text").filter({ hasText: /^12\.0$/ })).toBeVisible();
  await expect(page.locator("svg text").filter({ hasText: /10⁹/ })).toHaveCount(1);
  await expect(page.locator("svg text").filter({ hasText: /G$/ })).toHaveCount(0);
});
