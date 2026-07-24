import { expect, test, type Page, type Route } from "@playwright/test";

type SourceSoftware = "DIA-CLIP" | "DIA-NN";

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function dataset(slug: string, sourceSoftware: SourceSoftware) {
  return {
    id: sourceSoftware === "DIA-CLIP" ? 44 : 45,
    slug,
    name: `${sourceSoftware} demo`,
    description: sourceSoftware === "DIA-CLIP"
      ? "DIA-CLIP Bottom-Up DIA dataset with DIA-NN context"
      : null,
    source_path: slug,
    capabilities: {},
    analysis_mode: "BOTTOM_UP",
    dataset_mode: "bottom_up",
    status: "ready",
    source_software: sourceSoftware,
    extra_metadata: { q_value_cutoff: 0.01 },
    runs: [],
    bu_runs: [],
    cutoffs: [],
    created_at: "2026-07-24T00:00:00Z",
    updated_at: null,
  };
}

function overview(slug: string, sourceSoftware: SourceSoftware) {
  return {
    dataset_id: sourceSoftware === "DIA-CLIP" ? 44 : 45,
    slug,
    name: `${sourceSoftware} demo`,
    analysis_mode: "BOTTOM_UP",
    source_software: sourceSoftware,
    status: "ready",
    source_root: slug,
    q_value_cutoff: 0.01,
    counts: {
      matches: 1,
      peptides: 1,
      proteins: 1,
      protein_groups: 1,
      runs: 1,
      decoy_matches: 0,
    },
    qc: { by_run: [], aggregated: {} },
    runs: [{
      run_id: 1,
      file_name: "run.mzML",
      raw_format: "mzml",
      diann_run_name: "run",
      match_count: 1,
      has_im: false,
    }],
    capabilities: {},
    import_stats: { imported_matches: 1 },
    created_at: "2026-07-24T00:00:00Z",
  };
}

function matches() {
  return {
    page: 1,
    page_size: 50,
    total: 1,
    items: [{
      id: 1,
      run_id: 1,
      run_name: "run.mzML",
      peptide_id: 1,
      sequence: "PEPTIDE",
      modified_sequence: "PEPTIDE",
      protein_group: "P00001",
      precursor_mz: 456.789,
      precursor_charge: 2,
      retention_time: 12.34,
      experimental_mass: 911.56,
      q_value: 0.004,
      score: 0.91,
      intensity: 123456,
      is_decoy_match: false,
      scan_number: 100,
      extra_metadata: {},
    }],
  };
}

async function mockDataset(page: Page, slug: string, sourceSoftware: SourceSoftware) {
  await page.route("**/api/v1/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === `/api/v1/datasets/${slug}`) {
      return fulfillJson(route, dataset(slug, sourceSoftware));
    }
    if (pathname === `/api/v1/datasets/${slug}/overview`) {
      return fulfillJson(route, overview(slug, sourceSoftware));
    }
    if (pathname === `/api/v1/datasets/${slug}/matches`) {
      return fulfillJson(route, matches());
    }
    if (pathname.endsWith("/runs/1/chromatogram")) {
      return fulfillJson(route, { detail: "chromatogram_summary_missing" }, 409);
    }
    if (pathname.endsWith("/overview/rt-mz")) {
      return fulfillJson(route, {
        unit_rt: "min",
        unit_mz: "Th",
        rt_edges: [1, 2],
        mz_edges: [400, 500],
        counts: [[1]],
        max_count: 1,
        total_points: 1,
        run_id: 1,
      });
    }
    return fulfillJson(route, {}, 404);
  });
}

test("DIA-CLIP overview uses DIA-CLIP presentation without exposing DIA-NN provenance", async ({ page }) => {
  await mockDataset(page, "dia-clip", "DIA-CLIP");
  await page.goto("/datasets/dia-clip");

  await expect(page.getByText("DIA-CLIP Bottom-Up DIA dataset with reference context")).toBeVisible();
  await expect(page.getByRole("heading", { name: "DIA-CLIP QC" })).toBeVisible();
  await expect(page.getByText("DIA-CLIP q-value cutoff")).toBeVisible();
  await expect(page.getByText("DIA-CLIP run: run")).toBeVisible();
  await expect(page.getByText("DIA-NN", { exact: false })).toHaveCount(0);
});

test("match columns are source-specific for DIA-CLIP and remain unchanged for DIA-NN", async ({ page }) => {
  await mockDataset(page, "dia-clip", "DIA-CLIP");
  await page.goto("/datasets/dia-clip/matches");

  await expect(page.getByRole("columnheader", { name: "DIA-CLIP score" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "DIA-CLIP q-value" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "DIA-CLIP quantity" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Q.Value" })).toHaveCount(0);
  await expect(page.getByRole("columnheader", { name: "Intensity" })).toHaveCount(0);

  await page.unrouteAll();
  await mockDataset(page, "dia-nn", "DIA-NN");
  await page.goto("/datasets/dia-nn/matches");

  await expect(page.getByRole("columnheader", { name: "Q.Value" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Intensity" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "DIA-CLIP score" })).toHaveCount(0);
});
