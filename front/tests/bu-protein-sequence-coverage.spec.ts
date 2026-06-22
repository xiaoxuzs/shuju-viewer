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

const protein = {
  id: 1,
  accession: "PTEST",
  gene_name: "GENE",
  description: "Coverage test protein",
  is_decoy: false,
  protein_group: "PTEST",
  peptide_count: 2,
  match_count: 3,
  best_q_value: 0.001,
  pg_max_lfq: null,
  pg_q_value: null,
  pg_quantity: null,
  base_sequence: "MPEPTIDEKSEQPEPTIDE",
  coverage_mode: "full",
  coverage_percent: 17 / 19,
  coverage_segments: [
    {
      peptide_id: 101,
      sequence: "PEPTIDE",
      start: 1,
      end: 8,
      match_count: 2,
      best_q_value: 0.001,
      is_ambiguous: false,
      occurrence_index: 0,
    },
    {
      peptide_id: 202,
      sequence: "SEQ",
      start: 9,
      end: 12,
      match_count: 1,
      best_q_value: 0.002,
      is_ambiguous: false,
      occurrence_index: 0,
    },
    {
      peptide_id: 101,
      sequence: "PEPTIDE",
      start: 12,
      end: 19,
      match_count: 2,
      best_q_value: 0.001,
      is_ambiguous: false,
      occurrence_index: 1,
    },
  ],
  peptides: [
    {
      peptide_id: 101,
      sequence: "PEPTIDE",
      modified_sequence: null,
      match_count: 2,
      best_q_value: 0.001,
      best_match_id: 11,
    },
    {
      peptide_id: 202,
      sequence: "SEQ",
      modified_sequence: null,
      match_count: 1,
      best_q_value: 0.002,
      best_match_id: 12,
    },
  ],
  extra_metadata: { sequence_source: "mock" },
};

const manyPeptideProtein = {
  ...protein,
  id: 2,
  accession: "PSHORT",
  peptide_count: 40,
  match_count: 40,
  base_sequence: "MPEPTIDE",
  coverage_percent: 7 / 8,
  coverage_segments: Array.from({ length: 40 }, (_, index) => ({
    peptide_id: 1000 + index,
    sequence: `PEPTIDE${index}`,
    start: 1,
    end: 8,
    match_count: 1,
    best_q_value: 0.001 + index / 100_000,
    is_ambiguous: false,
    occurrence_index: 0,
  })),
  peptides: Array.from({ length: 40 }, (_, index) => ({
    peptide_id: 1000 + index,
    sequence: `PEPTIDE${index}`,
    modified_sequence: null,
    match_count: 1,
    best_q_value: 0.001 + index / 100_000,
    best_match_id: 100 + index,
  })),
};

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockProteinDetail(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());

    if (url.pathname === "/api/v1/datasets/demo") return fulfillJson(route, dataset);
    if (url.pathname === "/api/v1/datasets/demo/proteins/1") return fulfillJson(route, protein);
    if (url.pathname === "/api/v1/datasets/demo/proteins/2") return fulfillJson(route, manyPeptideProtein);

    return fulfillJson(route, {}, 404);
  });
}

test("protein sequence coverage links peptide selection to highlighted residues", async ({ page }) => {
  await mockProteinDetail(page);
  await page.goto("/datasets/demo/proteins/1");

  await expect(page.getByRole("heading", { name: /Sequence coverage - PTEST/ })).toBeVisible();

  const legend = page.getByRole("listbox", { name: "Covered peptides" });
  await expect(legend).toBeVisible();
  await expect(legend.getByRole("option")).toHaveCount(2);

  const peptide = legend.getByRole("option", { name: /PEPTIDE/ });
  const secondPeptide = legend.getByRole("option", { name: /SEQ/ });
  const peptideResidues = page.locator('[data-testid="covered-residue"][data-peptide-key="peptide:101"]');
  const secondPeptideResidues = page.locator('[data-testid="covered-residue"][data-peptide-key="peptide:202"]');

  await expect(peptideResidues.first()).not.toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  await expect(peptide).toHaveAttribute("aria-selected", "false");

  await peptide.click();
  await expect(peptide).toHaveAttribute("aria-selected", "true");
  await expect(peptideResidues.first()).toHaveCSS("background-color", "rgb(253, 224, 71)");
  await expect(page.locator('[data-testid="covered-residue"][data-peptide-key="peptide:101"][data-selected="true"]')).toHaveCount(14);

  await secondPeptide.click();
  await expect(peptide).toHaveAttribute("aria-selected", "false");
  await expect(secondPeptide).toHaveAttribute("aria-selected", "true");
  await expect(page.locator('[data-testid="covered-residue"][data-peptide-key="peptide:101"][data-selected="true"]')).toHaveCount(0);
  await expect(secondPeptideResidues.filter({ hasText: /[SEQ]/ })).toHaveCount(3);
  await expect(page.locator('[data-testid="covered-residue"][data-peptide-key="peptide:202"][data-selected="true"]')).toHaveCount(3);
});

test("short proteins keep long peptide sidebars internally scrollable", async ({ page }) => {
  await mockProteinDetail(page);
  await page.goto("/datasets/demo/proteins/2");

  await expect(page.getByRole("heading", { name: /Sequence coverage - PSHORT/ })).toBeVisible();

  const legend = page.getByRole("listbox", { name: "Covered peptides" });
  await expect(legend.getByRole("option")).toHaveCount(40);

  const sizes = await legend.evaluate((element) => ({
    clientHeight: element.clientHeight,
    overflowY: window.getComputedStyle(element).overflowY,
    scrollHeight: element.scrollHeight,
  }));

  expect(sizes.overflowY).toBe("auto");
  expect(sizes.scrollHeight).toBeGreaterThan(sizes.clientHeight);
  expect(sizes.clientHeight).toBeLessThan(220);

  const peptide = legend.getByRole("option", { name: /PEPTIDE0/ });
  await peptide.click();
  await expect(peptide).toHaveAttribute("aria-selected", "true");
  await expect(page.locator('[data-testid="covered-residue"][data-peptide-key="peptide:1000"][data-selected="true"]')).toHaveCount(7);
});
