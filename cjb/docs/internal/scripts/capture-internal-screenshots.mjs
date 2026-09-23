import { createRequire } from "node:module";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SCRIPT_DIR, "../../..");
const SCREENSHOT_DIR = path.join(REPO_ROOT, "docs/internal/assets/screenshots");
const MANIFEST_PATH = path.join(REPO_ROOT, "docs/internal/screenshot-manifest.json");
const FRONTEND_URL = process.env.VIEWER_FRONTEND_URL ?? "http://127.0.0.1:5173";
const API_BASE = process.env.VIEWER_API_BASE ?? "http://127.0.0.1:8000/api/v1";
const requireFromFront = createRequire(path.join(REPO_ROOT, "front/package.json"));
const { chromium } = requireFromFront("@playwright/test");

const nowIso = () => new Date().toISOString();

const manifest = {
  generated_at: nowIso(),
  frontend_url: FRONTEND_URL,
  api_base: API_BASE,
  discovery: {},
  screenshots: [],
};

function addResult(entry) {
  manifest.screenshots.push({
    generated_at: nowIso(),
    ...entry,
  });
}

async function apiJson(pathname) {
  const url = `${API_BASE}${pathname}`;
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`${response.status} ${response.statusText}${body ? `: ${body.slice(0, 240)}` : ""}`);
  }
  return response.json();
}

async function discoverData() {
  const datasets = await apiJson("/datasets");
  const spectraDataset = datasets.find((item) => item.dataset_mode === "spectra_only" && item.runs?.length)
    ?? datasets.find((item) => item.runs?.length);
  const buDataset = datasets.find((item) => item.dataset_mode === "bottom_up" && item.capabilities?.has_ms2_pfmb)
    ?? datasets.find((item) => item.dataset_mode === "bottom_up");
  let buMatch = null;
  if (buDataset) {
    const matches = await apiJson(`/datasets/${encodeURIComponent(buDataset.slug)}/matches?page=1&page_size=1`);
    buMatch = matches.items?.[0] ?? null;
  }

  manifest.discovery = {
    dataset_count: datasets.length,
    spectra_dataset: spectraDataset
      ? {
          id: spectraDataset.id,
          slug: spectraDataset.slug,
          run_id: spectraDataset.runs?.[0]?.run_id ?? null,
        }
      : null,
    bottom_up_dataset: buDataset
      ? {
          id: buDataset.id,
          slug: buDataset.slug,
          run_id: buDataset.bu_runs?.[0]?.run_id ?? null,
          has_ms2_pfmb: Boolean(buDataset.capabilities?.has_ms2_pfmb),
        }
      : null,
    bottom_up_match: buMatch
      ? {
          id: buMatch.id,
          run_id: buMatch.run_id,
          sequence: buMatch.sequence,
        }
      : null,
  };
  return { datasets, spectraDataset, buDataset, buMatch };
}

async function waitForPageReady(page) {
  await page.waitForLoadState("domcontentloaded");
  await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => {});
  await page.locator("body").waitFor({ state: "visible", timeout: 20_000 });
}

async function hideCaret(page) {
  await page.addStyleTag({
    content: `
      * { caret-color: transparent !important; }
      html { scroll-behavior: auto !important; }
    `,
  }).catch(() => {});
}

async function captureViewport(page, fileName) {
  await fs.mkdir(SCREENSHOT_DIR, { recursive: true });
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, fileName),
    fullPage: false,
    animations: "disabled",
  });
}

async function captureLocator(page, selector, fileName) {
  const locator = page.locator(selector).first();
  await locator.waitFor({ state: "visible", timeout: 30_000 });
  await locator.scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);
  await locator.screenshot({
    path: path.join(SCREENSHOT_DIR, fileName),
    animations: "disabled",
  });
}

async function runCapture(context, spec) {
  const page = await context.newPage();
  const route = spec.route();
  try {
    await page.goto(`${FRONTEND_URL}${route}`, { waitUntil: "domcontentloaded", timeout: 45_000 });
    await waitForPageReady(page);
    await hideCaret(page);
    if (spec.action) await spec.action(page);
    if (spec.selector) {
      await captureLocator(page, spec.selector, spec.file);
    } else {
      await captureViewport(page, spec.file);
    }
    addResult({
      file: spec.file,
      module: spec.module,
      success: true,
      route,
      reason: null,
    });
  } catch (error) {
    addResult({
      file: spec.file,
      module: spec.module,
      success: false,
      route,
      reason: error instanceof Error ? error.message : String(error),
    });
  } finally {
    await page.close().catch(() => {});
  }
}

async function scrollToText(page, text) {
  const locator = page.getByText(text, { exact: false }).first();
  await locator.waitFor({ state: "visible", timeout: 30_000 });
  await locator.scrollIntoViewIfNeeded();
  await page.waitForTimeout(700);
}

async function selectScan(page, scanNumber) {
  const input = page.getByPlaceholder("Scan number");
  await input.fill(String(scanNumber));
  await page.getByRole("button", { name: "Load scan" }).click();
  await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => {});
  await page.waitForTimeout(1000);
}

async function addTopProductIons(page) {
  await page.locator('[data-testid="product-ion-evidence-section"]').scrollIntoViewIfNeeded();
  await page.getByRole("button", { name: "Add top 3 fragments" }).click();
  await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});
  await page.locator('[data-testid="selected-product-ion-chips"], [data-testid="product-ion-xic-empty-state"]').first()
    .waitFor({ state: "visible", timeout: 30_000 });
  await page.waitForTimeout(1000);
}

function buildSpecs(discovery) {
  const { spectraDataset, buDataset, buMatch } = discovery;
  const specs = [
    {
      file: "home-or-dataset-list.png",
      module: "数据集列表模块",
      route: () => "/datasets",
      action: async (page) => {
        await page.getByText("Datasets").first().waitFor({ timeout: 30_000 });
      },
    },
    {
      file: "raw-or-mzml-import.png",
      module: "RAW或mzML导入模块",
      route: () => "/datasets",
      selector: '[role="dialog"]',
      action: async (page) => {
        await page.getByRole("button", { name: "Import from folder" }).click();
      },
    },
  ];

  if (spectraDataset) {
    const spectraRoute = `/datasets/${encodeURIComponent(spectraDataset.slug)}`;
    specs.push(
      {
        file: "dataset-detail.png",
        module: "数据集详情模块",
        route: () => spectraRoute,
        action: async (page) => {
          await page.getByText("Scans").first().waitFor({ timeout: 45_000 });
        },
      },
      {
        file: "spectra-only-page.png",
        module: "spectra-only谱图浏览模块",
        route: () => spectraRoute,
        action: async (page) => {
          await page.getByText("Showing").first().waitFor({ timeout: 45_000 });
        },
      },
      {
        file: "chromatogram-page.png",
        module: "chromatogram模块",
        route: () => spectraRoute,
        action: async (page) => scrollToText(page, "Run Chromatogram"),
      },
      {
        file: "ms1-spectrum.png",
        module: "MS1谱图模块",
        route: () => spectraRoute,
        selector: '[data-testid="spectra-only-2d-spectrum-panel"]',
        action: async (page) => {
          await page.locator('[data-testid="spectra-only-2d-spectrum-panel"]').waitFor({ timeout: 45_000 });
        },
      },
      {
        file: "ms2-spectrum.png",
        module: "MS2谱图模块",
        route: () => spectraRoute,
        selector: '[data-testid="spectra-only-2d-spectrum-panel"]',
        action: async (page) => {
          await page.getByText("Showing").first().waitFor({ timeout: 45_000 });
          await selectScan(page, 19);
          await page.getByText("Selected MS2 Spectrum").first().waitFor({ timeout: 45_000 });
        },
      },
    );
  } else {
    for (const file of ["dataset-detail.png", "spectra-only-page.png", "chromatogram-page.png", "ms1-spectrum.png", "ms2-spectrum.png"]) {
      addResult({
        file,
        module: "spectra-only相关模块",
        success: false,
        route: null,
        reason: "当前 API 未发现包含 runs 的 spectra-only 数据集，无法访问真实 spectra-only 页面。",
      });
    }
  }

  if (buDataset) {
    const buBase = `/datasets/${encodeURIComponent(buDataset.slug)}`;
    specs.push(
      {
        file: "bu-overview.png",
        module: "BU Overview模块",
        route: () => buBase,
        action: async (page) => {
          await page.getByText("Run Chromatogram").first().waitFor({ timeout: 45_000 });
        },
      },
      {
        file: "bu-protein-or-peptide-list.png",
        module: "BU蛋白或肽段列表模块",
        route: () => `${buBase}/proteins`,
        action: async (page) => {
          await page.getByText("Proteins").first().waitFor({ timeout: 45_000 });
        },
      },
    );
    if (buMatch) {
      const matchRoute = `${buBase}/matches/${buMatch.id}`;
      specs.push(
        {
          file: "bu-match-detail.png",
          module: "BU Match Detail模块",
          route: () => matchRoute,
          action: async (page) => {
            await page.locator('[data-testid="match-metadata"]').waitFor({ timeout: 45_000 });
          },
        },
        {
          file: "evidence-summary.png",
          module: "Evidence Summary模块",
          route: () => matchRoute,
          selector: '[data-testid="bu-evidence-summary"]',
          action: async (page) => {
            await page.locator('[data-testid="bu-evidence-summary"]').waitFor({ timeout: 45_000 });
          },
        },
        {
          file: "precursor-xic.png",
          module: "Precursor XIC模块",
          route: () => matchRoute,
          action: async (page) => scrollToText(page, "Precursor XIC"),
        },
        {
          file: "ms2-fragment-evidence.png",
          module: "MS2 Fragment Evidence模块",
          route: () => matchRoute,
          selector: '[data-testid="live-ms2-evidence-section"]',
          action: async (page) => {
            await page.locator('[data-testid="live-ms2-evidence-section"]').waitFor({ timeout: 60_000 });
          },
        },
        {
          file: "product-ion-xic.png",
          module: "Product ion XIC模块",
          route: () => matchRoute,
          selector: '[data-testid="product-ion-xic-card"]',
          action: addTopProductIons,
        },
        {
          file: "fragment-table.png",
          module: "Fragment table模块",
          route: () => matchRoute,
          selector: '[data-testid="product-ion-evidence-section"]',
          action: async (page) => {
            await page.locator('[data-testid="product-ion-evidence-section"]').waitFor({ timeout: 60_000 });
          },
        },
        {
          file: "pfmb-heatmap.png",
          module: "PFMB Heatmap模块",
          route: () => matchRoute,
          selector: '[data-testid="fragment-match-evidence-section"]',
          action: async (page) => {
            await page.locator('[data-testid="fragment-match-evidence-section"]').waitFor({ timeout: 60_000 });
          },
        },
      );
    } else {
      for (const file of [
        "bu-match-detail.png",
        "evidence-summary.png",
        "precursor-xic.png",
        "ms2-fragment-evidence.png",
        "product-ion-xic.png",
        "fragment-table.png",
        "pfmb-heatmap.png",
      ]) {
        addResult({
          file,
          module: "BU match证据相关模块",
          success: false,
          route: buBase,
          reason: "当前 API 未发现可用 BU match，无法访问真实 match detail 和证据页面。",
        });
      }
    }
  } else {
    for (const file of [
      "bu-overview.png",
      "bu-protein-or-peptide-list.png",
      "bu-match-detail.png",
      "evidence-summary.png",
      "precursor-xic.png",
      "ms2-fragment-evidence.png",
      "product-ion-xic.png",
      "fragment-table.png",
      "pfmb-heatmap.png",
    ]) {
      addResult({
        file,
        module: "Bottom-Up相关模块",
        success: false,
        route: null,
        reason: "当前 API 未发现 Bottom-Up 数据集，无法访问真实 BU 页面。",
      });
    }
  }

  return specs;
}

async function main() {
  await fs.mkdir(SCREENSHOT_DIR, { recursive: true });
  const discovery = await discoverData();
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  });
  try {
    for (const spec of buildSpecs(discovery)) {
      await runCapture(context, spec);
    }
  } finally {
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
    await fs.writeFile(MANIFEST_PATH, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  }

  const ok = manifest.screenshots.filter((item) => item.success).length;
  const failed = manifest.screenshots.length - ok;
  console.log(`Screenshots complete: ${ok} succeeded, ${failed} failed.`);
  console.log(`Manifest: ${MANIFEST_PATH}`);
}

main().catch(async (error) => {
  manifest.fatal_error = error instanceof Error ? error.message : String(error);
  await fs.mkdir(path.dirname(MANIFEST_PATH), { recursive: true });
  await fs.writeFile(MANIFEST_PATH, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  console.error(error);
  process.exitCode = 1;
});
