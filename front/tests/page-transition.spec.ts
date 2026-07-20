import { expect, test, type Page, type Route } from "@playwright/test";

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const buDataset = {
  id: 40,
  slug: "demo",
  name: "BU demo",
  description: null,
  source_path: "demo",
  capabilities: {},
  analysis_mode: "BOTTOM_UP",
  dataset_mode: "bottom_up",
  status: "ready",
  source_software: "DIA-NN",
  extra_metadata: { q_value_cutoff: 0.01 },
  runs: null,
  bu_runs: [
    { run_id: 1, file_name: "run-1.mzML", raw_format: "mzml", diann_run_name: "run-1", match_count: 3, has_im: false },
    { run_id: 2, file_name: "run-2.mzML", raw_format: "mzml", diann_run_name: "run-2", match_count: 2, has_im: false },
  ],
  created_at: "2026-07-20T00:00:00Z",
  updated_at: null,
  cutoffs: [],
};

const buOverview = {
  dataset_id: 40,
  slug: "demo",
  name: "BU demo",
  analysis_mode: "BOTTOM_UP",
  source_software: "DIA-NN",
  status: "ready",
  source_root: "demo",
  q_value_cutoff: 0.01,
  counts: { matches: 5, peptides: 3, proteins: 2, protein_groups: 2, runs: 2, decoy_matches: 0 },
  qc: { by_run: [], aggregated: {} },
  runs: buDataset.bu_runs,
  capabilities: {},
  import_stats: {},
  created_at: "2026-07-20T00:00:00Z",
};

const tdDataset = (slug: string, name: string, id: number) => ({
  id,
  slug,
  name,
  description: null,
  source_path: slug,
  capabilities: {},
  analysis_mode: "TOP_DOWN",
  dataset_mode: "top_down",
  status: "ready",
  source_software: "TopPIC",
  extra_metadata: {},
  runs: [],
  bu_runs: null,
  created_at: "2026-07-20T00:00:00Z",
  updated_at: null,
  cutoffs: [],
});

const spectraDataset = {
  id: 60,
  slug: "spectra",
  name: "Spectra demo",
  description: null,
  source_path: "spectra",
  capabilities: { analysis_shape: "mzml_only" },
  analysis_mode: null,
  dataset_mode: "spectra_only",
  status: "ready",
  source_software: "mzML",
  extra_metadata: {},
  runs: [
    { run_id: 1, run_name: "run-1.mzML", raw_format: "mzml", mzml_file_path: null, raw_path: null, metadata: {} },
    { run_id: 2, run_name: "run-2.mzML", raw_format: "mzml", mzml_file_path: null, raw_path: null, metadata: {} },
  ],
  bu_runs: null,
  created_at: "2026-07-20T00:00:00Z",
  updated_at: null,
  cutoffs: [],
};

const tdThreeDataset = {
  ...tdDataset("td", "TD demo", 51),
  capabilities: { spectra_source: "mzml_memory" },
};

const prsm = {
  id: 1,
  prsm_id: 1,
  sequence_id: 1,
  p_value: 0.001,
  e_value: 0.002,
  fdr: 0.01,
  matched_fragment_number: 0,
  matched_peak_number: 0,
  precursor_mono_mass: 1000,
  precursor_charge: 2,
  precursor_mz: 500,
  proteoform_mass: 1000,
  ms1_scans: "100",
  ms2_scans: "200",
  dataset_id: 51,
  run_id: 7,
  proteoform_id: 9,
  spectrum_file_name: "run.mzML",
  ms1_ids: null,
  ms2_ids: null,
  feature_inte: 100,
  ms_header: null,
  annotated_protein: null,
  ms_peaks: null,
};

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function chromatogram(runId: number) {
  return {
    type: "tic",
    unit_rt: "min",
    rt: [1, 2, 3],
    intensity: [10 * runId, 50 * runId, 20 * runId],
    downsampled: false,
    point_count_original: 3,
  };
}

function rtMz(runId: number) {
  return {
    unit_rt: "min",
    unit_mz: "Th",
    rt_edges: [1, 2],
    mz_edges: [400, 500],
    counts: [[runId]],
    max_count: runId,
    total_points: runId,
    run_id: runId,
  };
}

async function installVisualOrderTracker(page: Page, selector: string, minimumCount = 1) {
  await page.evaluate(({ selector: targetSelector, minimumCount: targetCount }) => {
    const trackedWindow = window as Window & { __transitionOrder?: string[] };
    trackedWindow.__transitionOrder = [];
    let visualRecorded = false;
    let idleRecorded = false;
    let activeRecorded = false;
    const record = () => {
      const mask = document.querySelector('[data-testid="page-transition-mask"]');
      if (mask?.getAttribute("data-state") === "active") activeRecorded = true;
      if (!visualRecorded && document.querySelectorAll(targetSelector).length >= targetCount) {
        visualRecorded = true;
        trackedWindow.__transitionOrder?.push("visual");
      }
      if (!idleRecorded && activeRecorded && mask?.getAttribute("data-state") === "idle") {
        idleRecorded = true;
        trackedWindow.__transitionOrder?.push("idle");
      }
    };
    new MutationObserver(record).observe(document.documentElement, {
      attributes: true,
      childList: true,
      subtree: true,
    });
    record();
  }, { selector, minimumCount });
}

async function transitionOrder(page: Page) {
  return page.evaluate(() => {
    const trackedWindow = window as Window & { __transitionOrder?: string[] };
    return trackedWindow.__transitionOrder ?? [];
  });
}

test("keeps a theme-matched mask over slow navigation until the first D3 paint", async ({ page }) => {
  const overviewGate = deferred();
  await page.addInitScript(() => localStorage.setItem("viewer.theme", "dark"));
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/datasets") return fulfillJson(route, [buDataset]);
    if (url.pathname === "/api/v1/datasets/demo") return fulfillJson(route, buDataset);
    if (url.pathname === "/api/v1/datasets/demo/overview") {
      await overviewGate.promise;
      return fulfillJson(route, buOverview);
    }
    if (url.pathname.endsWith("/runs/1/chromatogram")) return fulfillJson(route, chromatogram(1));
    if (url.pathname.endsWith("/overview/rt-mz")) return fulfillJson(route, rtMz(1));
    return fulfillJson(route, {}, 404);
  });

  await page.goto("/datasets");
  const mask = page.getByTestId("page-transition-mask");
  await expect(mask).toHaveAttribute("data-state", "idle");
  await page.getByRole("link").filter({ hasText: "BU demo" }).click();

  await expect(page).toHaveURL(/\/datasets\/demo$/);
  await expect(mask).toHaveAttribute("data-state", "active");
  await expect(mask).toHaveCSS("pointer-events", "auto");
  const colors = await page.evaluate(() => {
    const transitionMask = document.querySelector('[data-testid="page-transition-mask"]') as HTMLElement;
    return {
      mask: getComputedStyle(transitionMask).backgroundColor,
      body: getComputedStyle(document.body).backgroundColor,
    };
  });
  expect(colors.mask).toBe(colors.body);
  expect(colors.mask).not.toBe("rgb(255, 255, 255)");
  await installVisualOrderTracker(page, '[data-testid="plot-series"]');

  overviewGate.resolve();
  await expect(page.getByTestId("plot-series")).toBeVisible();
  await expect(mask).toHaveAttribute("data-state", "idle");
  expect(await transitionOrder(page)).toEqual(["visual", "idle"]);
});

test("uses fresh manual batches for Run changes and the chromatogram modal", async ({ page }) => {
  const runTwoGate = deferred();
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/datasets/demo") return fulfillJson(route, buDataset);
    if (url.pathname === "/api/v1/datasets/demo/overview") return fulfillJson(route, buOverview);
    if (url.pathname.endsWith("/runs/1/chromatogram")) return fulfillJson(route, chromatogram(1));
    if (url.pathname.endsWith("/runs/2/chromatogram")) {
      await runTwoGate.promise;
      return fulfillJson(route, chromatogram(2));
    }
    if (url.pathname.endsWith("/overview/rt-mz")) {
      return fulfillJson(route, rtMz(Number(url.searchParams.get("run_id") ?? 1)));
    }
    return fulfillJson(route, {}, 404);
  });

  await page.goto("/datasets/demo");
  const mask = page.getByTestId("page-transition-mask");
  await expect(mask).toHaveAttribute("data-state", "idle");
  const firstBatch = Number(await mask.getAttribute("data-batch-id"));

  await page.getByRole("combobox").selectOption("2");
  await expect(mask).toHaveAttribute("data-state", "active");
  expect(Number(await mask.getAttribute("data-batch-id"))).toBeGreaterThan(firstBatch);
  runTwoGate.resolve();
  await expect(mask).toHaveAttribute("data-state", "idle");

  const beforeModalBatch = Number(await mask.getAttribute("data-batch-id"));
  await installVisualOrderTracker(page, '[data-testid="plot-series"]', 2);
  await page.getByTitle("view large").click();
  await expect(page.getByRole("dialog")).toContainText("TIC Chromatogram");
  await expect(mask).toHaveAttribute("data-state", "idle");
  expect(Number(await mask.getAttribute("data-batch-id"))).toBeGreaterThan(beforeModalBatch);
  expect(await transitionOrder(page)).toEqual(["visual", "idle"]);
});

test("waits for scan metadata, spectrum D3 paint, and the new Run chromatogram", async ({ page }) => {
  const scanTwoGate = deferred();
  const runTwoChromatogramGate = deferred();
  const scansByRun = new Map([
    [1, [scan(100, 1), scan(200, 2)]],
    [2, [scan(300, 1)]],
  ]);
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/datasets/spectra") return fulfillJson(route, spectraDataset);
    const scanIndexMatch = url.pathname.match(/\/datasets\/60\/runs\/(\d+)\/scan-index$/);
    if (scanIndexMatch) {
      const runId = Number(scanIndexMatch[1]);
      const items = scansByRun.get(runId) ?? [];
      return fulfillJson(route, scanIndex(runId, items));
    }
    const chromMatch = url.pathname.match(/\/datasets\/60\/runs\/(\d+)\/chromatogram$/);
    if (chromMatch) {
      const runId = Number(chromMatch[1]);
      if (runId === 2) await runTwoChromatogramGate.promise;
      return fulfillJson(route, chromatogram(runId));
    }
    const spectrumMatch = url.pathname.match(/\/datasets\/60\/runs\/(\d+)\/spectra\/(\d+)$/);
    if (spectrumMatch) {
      const runId = Number(spectrumMatch[1]);
      const scanNumber = Number(spectrumMatch[2]);
      if (scanNumber === 200) await scanTwoGate.promise;
      return fulfillJson(route, spectrum(runId, scanNumber, scanNumber === 200 ? 2 : 1));
    }
    return fulfillJson(route, {}, 404);
  });

  await page.goto("/datasets/spectra");
  const mask = page.getByTestId("page-transition-mask");
  await expect(mask).toHaveAttribute("data-state", "idle");
  await expect(page.getByText(/Selected scan 100/)).toBeVisible();

  await page.locator("table").first().locator("tbody tr").filter({ hasText: "200" }).click();
  await expect(mask).toHaveAttribute("data-state", "active");
  scanTwoGate.resolve();
  await expect(page.getByText(/Selected scan 200/)).toBeVisible();
  await expect(page.getByTestId("spectra-only-2d-spectrum-chart").last()).toBeVisible();
  await expect(mask).toHaveAttribute("data-state", "idle");

  const scanBatch = Number(await mask.getAttribute("data-batch-id"));
  await page.getByRole("combobox").selectOption("2");
  await expect(mask).toHaveAttribute("data-state", "active");
  expect(Number(await mask.getAttribute("data-batch-id"))).toBeGreaterThan(scanBatch);
  runTwoChromatogramGate.resolve();
  await expect(page.getByText(/Selected scan 300/)).toBeVisible();
  await expect(mask).toHaveAttribute("data-state", "idle");
});

test("keeps system-dark direct visits and refreshes covered through the Three.js first frame", async ({ page }) => {
  let ms1Gate = deferred();
  await page.emulateMedia({ colorScheme: "dark" });
  await page.addInitScript(() => localStorage.removeItem("viewer.theme"));
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/datasets/td") return fulfillJson(route, tdThreeDataset);
    if (url.pathname === "/api/v1/datasets/td/cutoffs/prsm/prsms/1") return fulfillJson(route, prsm);
    if (url.pathname.endsWith("/runs/7/spectra/100")) {
      await ms1Gate.promise;
      return fulfillJson(route, rawSpectrum(100, 1));
    }
    if (url.pathname.endsWith("/runs/7/spectra/200")) return fulfillJson(route, rawSpectrum(200, 2));
    return fulfillJson(route, {}, 404);
  });

  await page.goto("/datasets/td/prsm/prsms/1");
  const mask = page.getByTestId("page-transition-mask");
  await expect(mask).toHaveAttribute("data-state", "active");
  await expect(page.locator("html")).toHaveAttribute("data-resolved-theme", "dark");
  const initialColors = await page.evaluate(() => ({
    root: getComputedStyle(document.documentElement).backgroundColor,
    mask: getComputedStyle(document.querySelector('[data-testid="page-transition-mask"]') as HTMLElement).backgroundColor,
  }));
  expect(initialColors.mask).toBe(initialColors.root);
  await installVisualOrderTracker(page, "canvas");
  ms1Gate.resolve();
  await expect(page.locator("canvas")).toBeVisible();
  await expect(mask).toHaveAttribute("data-state", "idle");
  expect(await transitionOrder(page)).toEqual(["visual", "idle"]);

  ms1Gate = deferred();
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(mask).toHaveAttribute("data-state", "active");
  await expect(page.locator("html")).toHaveAttribute("data-resolved-theme", "dark");
  ms1Gate.resolve();
  await expect(page.locator("canvas")).toBeVisible();
  await expect(mask).toHaveAttribute("data-state", "idle");
});

for (const failure of [
  { label: "404", status: 404 },
  { label: "500", status: 500 },
  { label: "network timeout", status: null },
] as const) {
  test(`exits the mask and shows the existing error state after ${failure.label}`, async ({ page }) => {
    await page.route("**/api/v1/**", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === "/api/v1/datasets/missing") {
        if (failure.status == null) return route.abort("timedout");
        return fulfillJson(route, { detail: "backend failure" }, failure.status);
      }
      return fulfillJson(route, {}, 404);
    });

    await page.goto("/datasets/missing");
    await expect(page.getByText("Failed to load data.")).toBeVisible();
    await expect(page.getByTestId("page-transition-mask")).toHaveAttribute("data-state", "idle");
  });
}

test("ignores an old request after rapid navigation and covers browser back and forward", async ({ page }) => {
  const datasetA = tdDataset("a", "TD A", 71);
  const datasetB = tdDataset("b", "TD B", 72);
  const datasetAGate = deferred();
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/datasets") return fulfillJson(route, [datasetA, datasetB]);
    if (url.pathname === "/api/v1/datasets/a") {
      await datasetAGate.promise;
      return fulfillJson(route, datasetA);
    }
    if (url.pathname === "/api/v1/datasets/b") return fulfillJson(route, datasetB);
    return fulfillJson(route, {}, 404);
  });

  await page.goto("/datasets");
  const mask = page.getByTestId("page-transition-mask");
  await expect(mask).toHaveAttribute("data-state", "idle");
  await page.getByRole("link").filter({ hasText: "TD A" }).click();
  await expect(mask).toHaveAttribute("data-state", "active");

  await page.evaluate(() => {
    history.pushState(null, "", "/datasets/b");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(page).toHaveURL(/\/datasets\/b$/);
  await expect(page.getByRole("heading", { name: "TD B" })).toBeVisible();
  await expect(mask).toHaveAttribute("data-state", "idle");
  const currentBatch = await mask.getAttribute("data-batch-id");

  const responseA = page.waitForResponse((response) => response.url().endsWith("/api/v1/datasets/a"));
  datasetAGate.resolve();
  await responseA;
  await expect(mask).toHaveAttribute("data-batch-id", currentBatch ?? "");
  await expect(mask).toHaveAttribute("data-state", "idle");
  await expect(page).toHaveURL(/\/datasets\/b$/);

  await page.evaluate(() => {
    const trackedWindow = window as Window & { __activeTransitions?: number };
    trackedWindow.__activeTransitions = 0;
    const transitionMask = document.querySelector('[data-testid="page-transition-mask"]');
    if (!transitionMask) return;
    new MutationObserver(() => {
      if (transitionMask.getAttribute("data-state") === "active") {
        trackedWindow.__activeTransitions = (trackedWindow.__activeTransitions ?? 0) + 1;
      }
    }).observe(transitionMask, { attributes: true, attributeFilter: ["data-state"] });
  });

  await page.goBack();
  await expect(page).toHaveURL(/\/datasets\/a$/);
  await expect(mask).toHaveAttribute("data-state", "idle");
  await page.goForward();
  await expect(page).toHaveURL(/\/datasets\/b$/);
  await expect(mask).toHaveAttribute("data-state", "idle");
  await expect.poll(() => page.evaluate(() => {
    const trackedWindow = window as Window & { __activeTransitions?: number };
    return trackedWindow.__activeTransitions ?? 0;
  })).toBeGreaterThanOrEqual(2);
});

function scan(scanNumber: number, msLevel: number) {
  return {
    scan_number: scanNumber,
    native_id: `scan=${scanNumber}`,
    ms_level: msLevel,
    retention_time: scanNumber / 100,
    tic: 1000,
    bpc: 500,
    precursor_mz: msLevel === 2 ? 500 : null,
    isolation_target_mz: msLevel === 2 ? 500 : null,
    isolation_lower_mz: msLevel === 2 ? 499 : null,
    isolation_upper_mz: msLevel === 2 ? 501 : null,
  };
}

function scanIndex(runId: number, items: ReturnType<typeof scan>[]) {
  return {
    dataset_id: 60,
    run_id: runId,
    total: items.length,
    offset: 0,
    limit: items.length,
    items,
    summary: {
      total_scans: items.length,
      ms1_count: items.filter((item) => item.ms_level === 1).length,
      ms2_count: items.filter((item) => item.ms_level === 2).length,
      other_count: 0,
      ms_level_counts: {},
      rt_min: 1,
      rt_max: 3,
      scan_min: items[0]?.scan_number ?? null,
      scan_max: items.at(-1)?.scan_number ?? null,
      max_tic: 1000,
      max_bpc: 500,
      ms2_fraction: 0.5,
      precursor_linked_ms2_count: 1,
    },
  };
}

function spectrum(runId: number, scanNumber: number, msLevel: number) {
  return {
    dataset_id: 60,
    run_id: runId,
    scan: scanNumber,
    native_id: `scan=${scanNumber}`,
    ms_level: msLevel,
    rt_seconds: scanNumber,
    mz: [100, 150, 200],
    intensity: [10, 100, 30],
    precursor: msLevel === 2 ? { mz: 500 } : null,
  };
}

function rawSpectrum(scanNumber: number, msLevel: number) {
  return {
    dataset_id: 51,
    run_id: 7,
    scan: scanNumber,
    native_id: `scan=${scanNumber}`,
    ms_level: msLevel,
    rt_seconds: scanNumber,
    mz: [100, 200, 300, 400],
    intensity: [10, 50, 100, 30],
    precursor: null,
  };
}
