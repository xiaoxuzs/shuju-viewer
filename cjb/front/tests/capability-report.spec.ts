import { expect, test, type Page, type Route } from "@playwright/test";

const NOW = "2026-09-04T00:00:00.000Z";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/datasets", async (route) => {
    await json(route, []);
  });
});

test("Agent case shows only compact capability totals without report details", async ({ page }) => {
  const report = capabilityReport();
  await mockAgentCase(page, {
    validation_mode: "deep",
    dataset_capability_report: report,
  });

  await page.goto("/agent-import-cases/case-capabilities");

  const panel = page.getByTestId("dataset-capability-report");
  await expect(panel.getByRole("heading", { name: "Dataset capability report" })).toBeVisible();
  const totals = [
    ["Recognized entities", report.entities.filter(({ state }) => state === "DIRECT" || state === "DERIVED").length],
    ["Available views", report.views.filter(({ availability }) => availability === "AVAILABLE").length],
    ["Partial views", report.views.filter(({ availability }) => availability === "PARTIAL").length],
    ["Disabled views", report.views.filter(({ availability }) => availability === "DISABLED").length],
  ] as const;
  const metrics = panel.getByTestId("capability-summary-metric");
  await expect(metrics).toHaveCount(4);
  for (const [label, count] of totals) {
    const metric = metrics.filter({ hasText: label });
    await expect(metric).toContainText(String(count));
  }
  for (const section of [
    "recognized-entities", "entity-gaps", "view-availability", "missing-inputs",
    "capability-ambiguities", "capability-warnings",
  ]) {
    await expect(panel.getByTestId(section)).toHaveCount(0);
  }
  await expect(panel.getByText("Evidence:", { exact: true })).toHaveCount(0);
  await expect(panel.getByText("Search FASTA", { exact: true })).toHaveCount(0);
  await expect(panel.getByText("Fragment annotations are unavailable", { exact: false })).toHaveCount(0);
  await expect(panel.locator("pre, code, details, ul")).toHaveCount(0);
});

test("Agent case keeps existing verification output when no capability report exists", async ({ page }) => {
  await mockAgentCase(page, { validation_mode: "deep", readable_run_count: 1 });

  await page.goto("/agent-import-cases/case-capabilities");

  await expect(page.getByTestId("dataset-capability-report")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Deep verification" })).toBeVisible();
  await expect(page.getByText('"readable_run_count": 1', { exact: false })).toBeVisible();
});

test("Bottom-Up disabled tabs stay visible, explain why, and do not navigate", async ({ page }) => {
  const dataset = bottomUpDataset("bu-capabilities", 92);
  let proteinRequests = 0;
  await page.route("**/api/v1/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/v1/datasets/bu-capabilities") return json(route, dataset);
    if (pathname === "/api/v1/datasets/bu-capabilities/capability-report") {
      return json(route, bottomUpCapabilityReport(92));
    }
    if (pathname === "/api/v1/datasets/bu-capabilities/overview") {
      return json(route, bottomUpOverview(dataset));
    }
    if (pathname.startsWith("/api/v1/datasets/bu-capabilities/proteins")) proteinRequests += 1;
    return json(route, {}, 404);
  });

  await page.goto("/datasets/bu-capabilities");

  await expect(page.getByTestId("dataset-capability-report")).toBeVisible();
  const disabledTab = page.getByTestId("disabled-tab-bu.proteins");
  const proteinsButton = disabledTab.getByRole("button", { name: "Proteins", exact: true });
  await expect(proteinsButton).toBeDisabled();
  await expect(disabledTab).toContainText("This view is unavailable: proteins.");
  await expect(disabledTab).toContainText("REQUIRED_DATA_MISSING");
  await proteinsButton.click({ force: true });
  await expect(page).toHaveURL(/\/datasets\/bu-capabilities$/);

  const legacyAliasTab = page.getByTestId("disabled-tab-bu_peptides");
  await expect(legacyAliasTab.getByRole("button", { name: "Peptides", exact: true })).toBeDisabled();
  await expect(legacyAliasTab).toContainText("This view is unavailable: peptides.");
  await expect(page.getByRole("link", { name: "Matches", exact: true }))
    .toHaveAttribute("href", "/datasets/bu-capabilities/matches");

  await page.goto("/datasets/bu-capabilities/proteins");
  await expect(page.getByTestId("disabled-direct-view")).toContainText("Bottom-Up proteins is unavailable");
  await expect(page.getByTestId("page-transition-mask")).toHaveAttribute("data-state", "idle");
  expect(proteinRequests).toBe(0);

  await page.goto("/datasets/bu-capabilities/proteins/123");
  await expect(page.getByTestId("disabled-direct-view")).toContainText("Bottom-Up proteins is unavailable");
  await expect(page.getByTestId("page-transition-mask")).toHaveAttribute("data-state", "idle");
  expect(proteinRequests).toBe(0);
});

test("legacy capability reports remain advisory and do not disable existing navigation", async ({ page }) => {
  const dataset = bottomUpDataset("legacy-bu", 93);
  await page.route("**/api/v1/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/v1/datasets/legacy-bu") return json(route, dataset);
    if (pathname === "/api/v1/datasets/legacy-bu/capability-report") {
      return json(route, {
        ...bottomUpCapabilityReport(93),
        source_case_id: null,
        provenance: "LEGACY_METADATA",
        enforcement: "ADVISORY",
        warnings: [{
          warning_id: "legacy_capability_metadata",
          message: "This report was conservatively inferred from legacy dataset capabilities.",
          evidence_refs: ["datasets.capabilities"],
        }],
      });
    }
    if (pathname === "/api/v1/datasets/legacy-bu/overview") {
      return json(route, bottomUpOverview(dataset));
    }
    return json(route, {}, 404);
  });

  await page.goto("/datasets/legacy-bu");

  await expect(page.getByTestId("capability-report-advisory")).toContainText("does not disable existing Viewer pages");
  await expect(page.getByRole("link", { name: "Proteins", exact: true }))
    .toHaveAttribute("href", "/datasets/legacy-bu/proteins");
});

test("dataset navigation fails closed when its capability report cannot be loaded", async ({ page }) => {
  const dataset = bottomUpDataset("invalid-report", 97);
  await page.route("**/api/v1/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/v1/datasets/invalid-report") return json(route, dataset);
    if (pathname === "/api/v1/datasets/invalid-report/capability-report") {
      return json(route, { detail: { code: "INVALID_DATASET_CAPABILITY_REPORT" } }, 500);
    }
    return json(route, {}, 404);
  });

  await page.goto("/datasets/invalid-report");

  await expect(page.getByRole("alert")).toContainText("could not load the dataset capability report");
  await expect(page.getByRole("link", { name: "Proteins", exact: true })).toHaveCount(0);
});

test("Top-Down dataset home displays the shared capability report", async ({ page }) => {
  const dataset = topDownDataset("top-down-capabilities", 95);
  await page.route("**/api/v1/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/v1/datasets/top-down-capabilities") return json(route, dataset);
    if (pathname === "/api/v1/datasets/top-down-capabilities/capability-report") {
      return json(route, topDownCapabilityReport(95));
    }
    return json(route, {}, 404);
  });

  await page.goto("/datasets/top-down-capabilities");

  await expect(page.getByTestId("dataset-capability-report")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Cutoffs", exact: true })).toBeVisible();
});

test("spectra-only home explains a disabled spectra view without requesting scan data", async ({ page }) => {
  let scanRequests = 0;
  const dataset = spectraOnlyDataset("spectra-disabled", 94);
  await page.route("**/api/v1/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/v1/datasets/spectra-disabled") return json(route, dataset);
    if (pathname === "/api/v1/datasets/spectra-disabled/capability-report") {
      return json(route, spectraDisabledCapabilityReport(94));
    }
    if (pathname.includes("/api/v1/datasets/94/runs/")) scanRequests += 1;
    return json(route, {}, 404);
  });

  await page.goto("/datasets/spectra-disabled");

  await expect(page.getByTestId("dataset-capability-report")).toBeVisible();
  const unavailable = page.getByTestId("disabled-spectra-view");
  await expect(unavailable).toContainText("This view is unavailable: spectra.");
  await expect(unavailable).toContainText("REQUIRED_DATA_MISSING");
  await expect(page.getByText("Run Chromatogram", { exact: true })).toHaveCount(0);
  expect(scanRequests).toBe(0);
});

test("Bottom-Up widgets keep usable content while unavailable chromatogram and coverage stay local", async ({ page }) => {
  const dataset = bottomUpDataset("bu-local-capabilities", 98);
  let chromatogramRequests = 0;
  await page.route("**/api/v1/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/v1/datasets/bu-local-capabilities") return json(route, dataset);
    if (pathname === "/api/v1/datasets/bu-local-capabilities/capability-report") {
      return json(route, bottomUpLocalCapabilityReport(98));
    }
    if (pathname === "/api/v1/datasets/bu-local-capabilities/overview") {
      return json(route, {
        ...bottomUpOverview(dataset),
        counts: { ...bottomUpOverview(dataset).counts, runs: 1, proteins: 1 },
        runs: [{
          run_id: 7,
          file_name: "agent-output.zp",
          raw_format: "zp",
          diann_run_name: null,
          match_count: 1,
          has_im: false,
        }],
      });
    }
    if (pathname === "/api/v1/datasets/bu-local-capabilities/overview/rt-mz") {
      return json(route, emptyRtMzHeatmap(7));
    }
    if (pathname === "/api/v1/datasets/bu-local-capabilities/runs/7/chromatogram") {
      chromatogramRequests += 1;
      return json(route, {}, 500);
    }
    if (pathname === "/api/v1/datasets/bu-local-capabilities/proteins/5") {
      return json(route, proteinDetailFixture());
    }
    return json(route, {}, 404);
  });

  await page.goto("/datasets/bu-local-capabilities");
  await expect(page.locator('[role="status"]').filter({ hasText: "This view is unavailable: chromatograms." }))
    .toBeVisible();
  expect(chromatogramRequests).toBe(0);

  await page.goto("/datasets/bu-local-capabilities/proteins/5");
  await expect(page.getByRole("heading", { name: "PLOCAL", exact: true })).toBeVisible();
  await expect(page.getByTestId("decoy-truth-badge")).toHaveText("Unknown");
  await expect(page.getByText("This view is unavailable: protein_sequences, peptide_positions.", { exact: true }))
    .toBeVisible();
  await expect(page.getByRole("heading", { name: /Sequence coverage/ })).toHaveCount(0);
});

test("match detail hides unverified fragments and renders zero, missing, channel, sample, and unit quantification", async ({ page }) => {
  const dataset = bottomUpDataset("bu-match-capabilities", 99);
  let xicRequests = 0;
  let spectrumRequests = 0;
  await page.route("**/api/v1/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/v1/datasets/bu-match-capabilities") return json(route, dataset);
    if (pathname === "/api/v1/datasets/bu-match-capabilities/capability-report") {
      return json(route, bottomUpMatchCapabilityReport(99));
    }
    if (pathname === "/api/v1/datasets/bu-match-capabilities/matches/1") {
      return json(route, matchDetailFixture());
    }
    if (pathname.endsWith("/matches/1/xic")) {
      xicRequests += 1;
      return json(route, {}, 500);
    }
    if (pathname.endsWith("/matches/1/spectrum/ms1")) {
      spectrumRequests += 1;
      return json(route, spectrumFixture(10, 1));
    }
    if (pathname.endsWith("/matches/1/spectrum/ms2")) {
      spectrumRequests += 1;
      return json(route, spectrumFixture(11, 2));
    }
    return json(route, {}, 404);
  });

  await page.goto("/datasets/bu-match-capabilities/matches/1");

  const quantification = page.getByTestId("match-quantification");
  await expect(page.getByTestId("decoy-truth-badge")).toHaveText("Ambiguous");
  await expect(quantification).toContainText("This view is partially available: quantification_completeness.");
  await expect(quantification.getByText("TMT126", { exact: true })).toBeVisible();
  await expect(quantification.getByText("Sample A", { exact: true })).toBeVisible();
  await expect(quantification.getByText("reporter_intensity", { exact: true }).first()).toBeVisible();
  await expect(quantification.getByText("0", { exact: true })).toBeVisible();
  await expect(quantification.getByText("Missing", { exact: true })).toBeVisible();
  await expect(quantification.getByText("TMT127", { exact: true })).toBeVisible();

  await expect(page.getByText("This view is unavailable: chromatograms.", { exact: true })).toBeVisible();
  await expect(page.getByText(/No fragment labels are drawn because/)).toBeVisible();
  await expect(page.getByTestId("product-ion-evidence-section")).toHaveCount(0);
  await expect(page.getByTestId("bu-evidence-summary")).not.toContainText("Live matched b/y ions");
  await expect(page.getByTestId("spectrum-ion-label")).toHaveCount(0);
  await expect(page.getByText(/live matched/i)).toHaveCount(0);
  await expect(page.locator('svg[aria-label^="MS2 scan #11"]')).toBeVisible();
  expect(xicRequests).toBe(0);
  expect(spectrumRequests).toBe(2);
});

async function mockAgentCase(page: Page, verification: Record<string, unknown>): Promise<void> {
  await page.route("**/api/v1/agent-import-cases/case-capabilities**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname.endsWith("/messages") || pathname.endsWith("/attempts") || pathname.endsWith("/artifacts")) {
      await json(route, []);
      return;
    }
    await json(route, agentCase(verification));
  });
}

function agentCase(verification: Record<string, unknown>) {
  return {
    case_id: "case-capabilities",
    workspace_id: "default",
    status: "SUCCESS",
    source_mode: "server_path",
    source_ref: "E:\\data\\unknown-format",
    dataset_fingerprint: "a".repeat(32),
    analysis_category: "BOTTOM_UP",
    source_profile: "Unknown proteomics format",
    format_details: null,
    interaction_mode: "autonomous",
    autonomous_attempt_used: 1,
    guided_attempt_no: 0,
    context_revision: 0,
    version: 3,
    stop_requested_at: null,
    candidate_zp_sha256: "b".repeat(64),
    verification,
    dataset_id: 91,
    dataset_slug: "capability-sample",
    created_at: NOW,
    updated_at: NOW,
  };
}

function capabilityReport() {
  const psms = fact("psms", "DIRECT", null, { count: 150, evidenceRefs: ["semantic.identifications"] });
  const proteins = fact("proteins", "DIRECT", null, { count: 12, evidenceRefs: ["semantic.proteins"] });
  const proteinSequences = fact("protein_sequences", "MISSING", "FASTA_REQUIRED");
  const peptidePositions = fact("peptide_positions", "DERIVED", null, {
    count: 120,
    evidenceRefs: ["semantic.proteins", "semantic.peptides"],
    derivationId: "viewer.peptide-position.exact-subsequence.v1",
  });
  const proteinSequenceCompleteness = fact("protein_sequence_completeness", "MISSING", "FASTA_REQUIRED");
  const peptidePositionCompleteness = fact("peptide_position_completeness", "DIRECT");
  const spectra = fact("spectra", "DIRECT", null, { count: 150 });
  const spectrumLinks = fact("spectrum_links", "DIRECT", null, { count: 150 });
  const fragmentAnnotations = fact(
    "fragment_annotations",
    "VIEWER_UNSUPPORTED",
    "ANNOTATION_DIALECT_UNSUPPORTED",
  );
  const quantification = fact("quantification", "DIRECT", null, { count: 150 });
  const quantificationCompleteness = fact("quantification_completeness", "DIRECT");
  const quantificationSemantics = fact("quantification_semantics", "AMBIGUOUS", "QUANT_SEMANTICS_AMBIGUOUS");
  return {
    schema_version: 1,
    dataset_id: 91,
    source_case_id: "case-capabilities",
    provenance: "VALIDATED_FACTS",
    enforcement: "ENFORCED",
    entities: [
      psms,
      proteins,
      proteinSequences,
      peptidePositions,
      proteinSequenceCompleteness,
      peptidePositionCompleteness,
      spectra,
      spectrumLinks,
      fragmentAnnotations,
      quantification,
      quantificationCompleteness,
      quantificationSemantics,
    ],
    views: [
      view("bu.matches", "Bottom-Up matches", "/datasets/{slug}/matches", "AVAILABLE", null, null, [
        requirement(psms),
      ]),
      view(
        "quantification",
        "Quantification",
        "/datasets/{slug}/matches/{match_id}",
        "PARTIAL",
        "This view is partially available: quantification_semantics.",
        "OPTIONAL_REQUIREMENT_AMBIGUOUS",
        [
          requirement(psms),
          requirement(quantification),
          requirement(quantificationCompleteness, false),
          requirement(quantificationSemantics, false),
        ],
      ),
      view(
        "bu.protein_coverage",
        "Protein sequence coverage",
        "/datasets/{slug}/proteins/{protein_id}",
        "DISABLED",
        "This view is unavailable: protein_sequences.",
        "REQUIRED_DATA_MISSING",
        [
          requirement(proteins),
          requirement(proteinSequences),
          requirement(peptidePositions),
          requirement(proteinSequenceCompleteness, false),
          requirement(peptidePositionCompleteness, false),
        ],
      ),
      view(
        "fragment_annotation",
        "Fragment annotation",
        "/datasets/{slug}/matches/{match_id}",
        "DISABLED",
        "This view is unavailable: fragment_annotations.",
        "VIEWER_UNSUPPORTED",
        [
          requirement(psms),
          requirement(spectra),
          requirement(spectrumLinks),
          requirement(fragmentAnnotations),
        ],
      ),
    ],
    missing_inputs: [
      {
        input_id: "search-fasta",
        label: "Search FASTA",
        reason_code: "FASTA_REQUIRED",
        message: "Add the FASTA used by this search to restore protein sequences.",
        unlocks: ["bu.protein_coverage"],
      },
    ],
    ambiguities: [
      {
        ambiguity_id: "quantification_semantics",
        message: "The quantity column has no declared normalization semantics; user confirmation is required.",
        evidence_refs: ["semantic.quantification"],
        affected_views: ["quantification"],
      },
    ],
    warnings: [
      {
        warning_id: "fragment-annotation",
        message: "Fragment annotations are unavailable; Viewer did not synthesize them.",
        evidence_refs: ["fragments.bin"],
      },
    ],
  };
}

function bottomUpDataset(slug: string, id: number) {
  return {
    id,
    slug,
    name: "Capability-aware Bottom-Up dataset",
    description: null,
    source_path: `E:\\data\\${slug}`,
    capabilities: {},
    analysis_mode: "BOTTOM_UP",
    dataset_mode: "bottom_up",
    status: "ready",
    source_software: null,
    extra_metadata: null,
    runs: null,
    bu_runs: [],
    created_at: NOW,
    updated_at: null,
    cutoffs: [],
  };
}

function bottomUpOverview(dataset: ReturnType<typeof bottomUpDataset>) {
  return {
    dataset_id: dataset.id,
    slug: dataset.slug,
    name: dataset.name,
    analysis_mode: "BOTTOM_UP",
    source_software: null,
    status: "ready",
    source_root: dataset.source_path,
    q_value_cutoff: 0.01,
    counts: { matches: 7, peptides: 3, proteins: 0, protein_groups: 0, runs: 0, decoy_matches: 0 },
    qc: { by_run: [], aggregated: {} },
    runs: [],
    capabilities: {},
    import_stats: {},
    created_at: NOW,
  };
}

function topDownDataset(slug: string, id: number) {
  return {
    ...bottomUpDataset(slug, id),
    name: "Capability-aware Top-Down dataset",
    analysis_mode: "TOP_DOWN",
    dataset_mode: "top_down",
    bu_runs: null,
  };
}

function topDownCapabilityReport(datasetId: number) {
  const proteins = fact("proteins", "DIRECT");
  return {
    schema_version: 1,
    dataset_id: datasetId,
    source_case_id: "case-top-down-capabilities",
    provenance: "VALIDATED_FACTS",
    enforcement: "ENFORCED",
    entities: [proteins],
    views: [view(
      "td.proteins",
      "Top-Down proteins",
      "/datasets/{slug}/{cutoff}/proteins",
      "AVAILABLE",
      "All declared requirements are available.",
      null,
      [requirement(proteins)],
    )],
    missing_inputs: [],
    ambiguities: [],
    warnings: [],
  };
}

function bottomUpCapabilityReport(datasetId: number) {
  const proteins = fact("proteins", "MISSING", "PROTEINS_MISSING");
  const peptides = fact("peptides", "MISSING", "SEMANTIC_ENTITY_EMPTY");
  const psms = fact("psms", "DIRECT");
  const spectra = fact("spectra", "MISSING", "SPECTRA_MISSING");
  return {
    schema_version: 1,
    dataset_id: datasetId,
    source_case_id: "case-bu-capabilities",
    provenance: "VALIDATED_FACTS",
    enforcement: "ENFORCED",
    entities: [proteins, peptides, psms, spectra],
    views: [
      view(
        "bu.proteins",
        "Bottom-Up proteins",
        "/datasets/{slug}/proteins",
        "DISABLED",
        "This view is unavailable: proteins.",
        "REQUIRED_DATA_MISSING",
        [requirement(proteins)],
      ),
      view(
        "bu_peptides",
        "Bottom-Up peptides",
        "/datasets/{slug}/peptides",
        "DISABLED",
        "This view is unavailable: peptides.",
        "REQUIRED_DATA_MISSING",
        [requirement(peptides)],
      ),
      view(
        "bu.matches",
        "Bottom-Up matches",
        "/datasets/{slug}/matches",
        "AVAILABLE",
        "All declared requirements are available.",
        null,
        [requirement(psms)],
      ),
    ],
    missing_inputs: [],
    ambiguities: [],
    warnings: [],
  };
}

function spectraOnlyDataset(slug: string, id: number) {
  return {
    id,
    slug,
    name: "Spectra pending verification",
    description: null,
    source_path: `E:\\data\\${slug}`,
    capabilities: { analysis_shape: "zp_spectra_only", spectra_source: "zp" },
    analysis_mode: "TOP_DOWN",
    dataset_mode: "spectra_only",
    status: "ready",
    source_software: null,
    extra_metadata: null,
    runs: [
      {
        run_id: 1,
        run_name: "run.mzML",
        raw_format: "mzml",
        mzml_file_path: null,
        raw_path: null,
        metadata: {},
      },
    ],
    bu_runs: null,
    created_at: NOW,
    updated_at: null,
    cutoffs: [],
  };
}

function spectraDisabledCapabilityReport(datasetId: number) {
  const spectra = fact("spectra", "MISSING", "SPECTRA_NOT_VERIFIED");
  return {
    schema_version: 1,
    dataset_id: datasetId,
    source_case_id: "case-spectra-disabled",
    provenance: "VALIDATED_FACTS",
    enforcement: "ENFORCED",
    entities: [spectra],
    views: [
      view(
        "spectra",
        "Spectra",
        "/datasets/{slug}",
        "DISABLED",
        "This view is unavailable: spectra.",
        "REQUIRED_DATA_MISSING",
        [requirement(spectra)],
      ),
    ],
    missing_inputs: [],
    ambiguities: [],
    warnings: [],
  };
}

function bottomUpLocalCapabilityReport(datasetId: number) {
  const proteins = fact("proteins", "DIRECT", null, { count: 1 });
  const chromatograms = fact("chromatograms", "MISSING", "CHROMATOGRAMS_MISSING");
  const proteinSequences = fact("protein_sequences", "MISSING", "FASTA_MISSING");
  const peptidePositions = fact("peptide_positions", "MISSING", "FASTA_MISSING");
  const proteinSequenceCompleteness = fact("protein_sequence_completeness", "MISSING", "FASTA_MISSING");
  const peptidePositionCompleteness = fact("peptide_position_completeness", "MISSING", "FASTA_MISSING");
  return {
    schema_version: 1,
    dataset_id: datasetId,
    source_case_id: "case-bu-local-capabilities",
    provenance: "VALIDATED_FACTS",
    enforcement: "ENFORCED",
    entities: [
      proteins,
      chromatograms,
      proteinSequences,
      peptidePositions,
      proteinSequenceCompleteness,
      peptidePositionCompleteness,
    ],
    views: [
      view(
        "bu.proteins",
        "Bottom-Up proteins",
        "/datasets/{slug}/proteins",
        "AVAILABLE",
        "All declared requirements are available.",
        null,
        [requirement(proteins)],
      ),
      view(
        "chromatogram",
        "Chromatogram",
        "/datasets/{slug}",
        "DISABLED",
        "This view is unavailable: chromatograms.",
        "REQUIRED_DATA_MISSING",
        [requirement(chromatograms)],
      ),
      view(
        "bu.protein_coverage",
        "Protein sequence coverage",
        "/datasets/{slug}/proteins/{protein_id}",
        "DISABLED",
        "This view is unavailable: protein_sequences, peptide_positions.",
        "REQUIRED_DATA_MISSING",
        [
          requirement(proteins),
          requirement(proteinSequences),
          requirement(peptidePositions),
          requirement(proteinSequenceCompleteness, false),
          requirement(peptidePositionCompleteness, false),
        ],
      ),
    ],
    missing_inputs: [{
      input_id: "fasta",
      label: "Search FASTA",
      reason_code: "FASTA_MISSING",
      message: "Provide the FASTA used by this search.",
      unlocks: ["bu.protein_coverage"],
    }],
    ambiguities: [],
    warnings: [],
  };
}

function bottomUpMatchCapabilityReport(datasetId: number) {
  const psms = fact("psms", "DIRECT", null, { count: 1 });
  const spectra = fact("spectra", "DIRECT", null, { count: 2 });
  const spectrumLinks = fact("spectrum_links", "DIRECT", null, { count: 1 });
  const chromatograms = fact("chromatograms", "MISSING", "CHROMATOGRAMS_MISSING");
  const fragmentAnnotations = fact("fragment_annotations", "MISSING", "FRAGMENT_ANNOTATIONS_MISSING");
  const quantification = fact("quantification", "DIRECT", null, { count: 3 });
  const quantificationCompleteness = fact(
    "quantification_completeness",
    "MISSING",
    "QUANTIFICATION_VALUES_MISSING",
  );
  const quantificationSemantics = fact("quantification_semantics", "DIRECT");
  return {
    schema_version: 1,
    dataset_id: datasetId,
    source_case_id: "case-bu-match-capabilities",
    provenance: "VALIDATED_FACTS",
    enforcement: "ENFORCED",
    entities: [
      psms,
      spectra,
      spectrumLinks,
      chromatograms,
      fragmentAnnotations,
      quantification,
      quantificationCompleteness,
      quantificationSemantics,
    ],
    views: [
      view(
        "bu.matches",
        "Bottom-Up matches",
        "/datasets/{slug}/matches",
        "AVAILABLE",
        "All declared requirements are available.",
        null,
        [requirement(psms)],
      ),
      view(
        "spectra",
        "Spectra",
        "/datasets/{slug}",
        "AVAILABLE",
        "All declared requirements are available.",
        null,
        [requirement(spectra)],
      ),
      view(
        "chromatogram",
        "Chromatogram",
        "/datasets/{slug}",
        "DISABLED",
        "This view is unavailable: chromatograms.",
        "REQUIRED_DATA_MISSING",
        [requirement(chromatograms)],
      ),
      view(
        "fragment_annotation",
        "Fragment annotation",
        "/datasets/{slug}/matches/{match_id}",
        "DISABLED",
        "This view is unavailable: fragment_annotations.",
        "REQUIRED_DATA_MISSING",
        [
          requirement(psms),
          requirement(spectra),
          requirement(spectrumLinks),
          requirement(fragmentAnnotations),
        ],
      ),
      view(
        "quantification",
        "Quantification",
        "/datasets/{slug}/matches/{match_id}",
        "PARTIAL",
        "This view is partially available: quantification_completeness.",
        "OPTIONAL_DATA_MISSING",
        [
          requirement(psms),
          requirement(quantification),
          requirement(quantificationCompleteness, false),
          requirement(quantificationSemantics, false),
        ],
      ),
    ],
    missing_inputs: [],
    ambiguities: [],
    warnings: [{
      warning_id: "fragment_annotation_missing",
      message: "Fragment annotations are unavailable; Viewer did not synthesize them.",
      evidence_refs: ["semantic.identifications"],
    }],
  };
}

function emptyRtMzHeatmap(runId: number) {
  return {
    unit_rt: "min",
    unit_mz: "Th",
    rt_edges: [],
    mz_edges: [],
    counts: [],
    max_count: 0,
    total_points: 0,
    run_id: runId,
  };
}

function proteinDetailFixture() {
  return {
    id: 5,
    accession: "PLOCAL",
    gene_name: null,
    description: "Protein remains usable without sequence coverage",
    is_decoy: null,
    is_decoy_state: "MISSING",
    protein_group: "PLOCAL",
    peptide_count: 1,
    match_count: 1,
    best_q_value: 0.001,
    pg_max_lfq: null,
    pg_q_value: null,
    pg_quantity: null,
    base_sequence: null,
    coverage_mode: "list_only",
    coverage_percent: null,
    coverage_segments: [],
    peptides: [],
    extra_metadata: {},
  };
}

function matchDetailFixture() {
  return {
    id: 1,
    run_id: 10,
    run_name: "agent-output.zp",
    peptide_id: 5,
    sequence: "PEPTIDE",
    modified_sequence: null,
    precursor_mz: 477.3051,
    precursor_charge: 2,
    retention_time: 12.5,
    experimental_mass: null,
    q_value: 0.001,
    score: 10,
    intensity: null,
    is_decoy_match: null,
    is_decoy_state: "AMBIGUOUS",
    scan_number: 11,
    protein_group: null,
    protein_accessions: [],
    genes: null,
    search_engine: "Agent-ZP",
    spectrum_native_id: "scan=11",
    ms_level: 2,
    entity_type: "PEPTIDE",
    run: {
      run_id: 10,
      file_name: "agent-output.zp",
      raw_format: "zp",
      file_path: "agent-output.zp",
      diann_run_name: null,
    },
    rt_window: { rt_start: 12, rt_stop: 13, rt_apex: 12.5, unit: "min" },
    proteins: [],
    diann: {},
    spectrum_links: {},
    extra_metadata: {
      quantification: [
        {
          quantification_id: "quant:126",
          entity_kind: "identification",
          entity_id: "identification:1",
          run_id: "run:1",
          sample: "Sample A",
          channel: "TMT126",
          value: 0,
          unit: "reporter_intensity",
          normalization_kind: "raw",
          source_fields: {},
          evidence_refs: ["report.tsv:Reporter intensity 126"],
        },
        {
          quantification_id: "quant:127",
          entity_kind: "identification",
          entity_id: "identification:1",
          run_id: "run:1",
          sample: "Sample B",
          channel: "TMT127",
          value: null,
          unit: "reporter_intensity",
          normalization_kind: "raw",
          source_fields: {},
          evidence_refs: ["report.tsv:Reporter intensity 127"],
        },
      ],
    },
  };
}

function spectrumFixture(scan: number, msLevel: 1 | 2) {
  return {
    scan,
    native_id: `scan=${scan}`,
    ms_level: msLevel,
    rt_seconds: 750,
    rt_minutes: 12.5,
    mz: msLevel === 1 ? [400, 477.3051, 600] : [100, 150, 200],
    intensity: msLevel === 1 ? [10, 100, 20] : [20, 90, 10],
    precursor: msLevel === 1
      ? null
      : {
          selected_mz: 477.3051,
          charge: 2,
          isolation_target_mz: 477.3051,
          isolation_lower: 1,
          isolation_upper: 1,
        },
    matched_ions: msLevel === 1
      ? []
      : [{ ion_type: "b", position: 2, charge: 1, theo_mz: 150, exp_mz: 150, ppm: 0, intensity: 90 }],
    markers: msLevel === 1 ? [{ mz: 477.3051, label: "precursor", charge: 2 }] : [],
  };
}

function fact(
  entity: string,
  state: string,
  reasonCode: string | null = null,
  options: { count?: number; evidenceRefs?: string[]; derivationId?: string } = {},
) {
  return {
    entity,
    state,
    count: options.count ?? null,
    reason_code: reasonCode,
    evidence_refs: options.evidenceRefs ?? [],
    derivation_id: options.derivationId ?? null,
  };
}

function requirement(entity: ReturnType<typeof fact>, required = true) {
  return {
    entity: entity.entity,
    state: entity.state,
    required,
    reason_code: entity.reason_code,
    derivation_id: entity.derivation_id,
  };
}

function view(
  viewId: string,
  title: string,
  route: string,
  availability: string,
  message: string | null = "All declared requirements are available.",
  reasonCode: string | null = null,
  requirements: Array<ReturnType<typeof requirement>> = [],
) {
  return {
    view_id: viewId,
    title,
    route,
    availability,
    requirements,
    reason_code: reasonCode,
    message,
  };
}

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}
