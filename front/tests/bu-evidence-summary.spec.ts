import { expect, test } from "@playwright/test";

import { buildBuEvidenceSummary } from "../src/features/bu/components/match-detail/evidenceSummaryModel";

const match = {
  sequence: "PEPTIDE",
  precursor_charge: 2,
  precursor_mz: 477.3051,
  q_value: 0.001,
  identification_rt_apex: 94.99,
  rt_window: { rt_start: 93.99, rt_stop: 95.99, rt_apex: 94.99, unit: "min" },
} as any;

const annotation = {
  prsm_index: 101,
  peptide: "PEPTIDE",
  matched_peak_count: 2,
  matched_ions: [
    {
      ion_type: "b",
      fragment_ordinal: 2,
      charge: 1,
      intensity: 100,
      observed_neutral_mass: 200,
      theoretical_neutral_mass: 200,
      mass_error_ppm: -1,
      mass_error_da: -0.0002,
      peak_id: 1,
    },
    {
      ion_type: "y",
      fragment_ordinal: 5,
      charge: 1,
      intensity: 80,
      observed_neutral_mass: 600,
      theoretical_neutral_mass: 600,
      mass_error_ppm: 1,
      mass_error_da: 0.0006,
      peak_id: 2,
    },
  ],
} as any;

test("evidence summary keeps live and PFMB metrics source-specific", () => {
  const sections = buildBuEvidenceSummary({
    match,
    xic: {
      data: {
        rt: [94.99],
        intensity: [100],
        precursor_mz: 477.3051,
        precursor_charge: 2,
        ppm: 10,
        rt_apex: 94.99,
        rt_start: 93.99,
        rt_stop: 95.99,
        traces: [],
        unit_rt: "min",
      },
      isLoading: false,
      isError: false,
    },
    ms2: {
      data: {
        scan: 70714,
        native_id: "scan=70714",
        ms_level: 2,
        rt_seconds: 5699.4,
        rt_minutes: 94.99,
        mz: [200],
        intensity: [100],
        precursor: null,
        markers: [],
        matched_ions: [{
          ion_type: "b",
          position: 2,
          charge: 1,
          theo_mz: 200,
          exp_mz: 200,
          ppm: 0.5,
          intensity: 100,
        }],
      },
      isLoading: false,
      isError: false,
    },
    hasPfmb: true,
    pfmbSlots: {
      data: {
        has_pfmb: true,
        source_row: 1,
        apex_slot: 5,
        slots: [{ prsm_index: 101, slot_index: 5, slot_rt_seconds: 5699.4, rt_minutes: 94.99 }],
      },
      isLoading: false,
      isError: false,
    },
    pfmbAnnotation: { data: annotation, isLoading: false, isError: false },
    activePfmbSlot: { prsm_index: 101, slot_index: 5, slot_rt_seconds: 5699.4, rt_minutes: 94.99 },
    inspectedRt: null,
    selectedXicPoint: null,
  });

  const live = sections.find((section) => section.key === "live-ms2")!;
  const pfmb = sections.find((section) => section.key === "pfmb")!;
  const accuracy = sections.find((section) => section.key === "mass-accuracy")!;
  expect(live.rows.map((row) => row.label)).toContain("Live matched b/y ions");
  expect(pfmb.rows.map((row) => row.label)).toContain("Fragment Match matched peak rows");
  expect(pfmb.rows.find((row) => row.label === "Fragment Match coverage")?.value).toBe("17%");
  expect(accuracy.rows.map((row) => row.label)).toEqual([
    "Live MS2 mass accuracy",
    "Fragment Match mass accuracy",
  ]);
});

test("evidence summary provides explicit missing-source fallbacks", () => {
  const sections = buildBuEvidenceSummary({
    match,
    xic: { isLoading: false, isError: true },
    ms2: { isLoading: false, isError: true },
    hasPfmb: false,
    pfmbSlots: { isLoading: false, isError: false },
    pfmbAnnotation: { isLoading: false, isError: false },
    activePfmbSlot: null,
    inspectedRt: null,
    selectedXicPoint: null,
  });

  expect(sections.find((section) => section.key === "chromatographic")?.empty).toBe("XIC not available");
  expect(sections.find((section) => section.key === "live-ms2")?.empty).toBe("MS2 scan not available");
  expect(sections.find((section) => section.key === "pfmb")?.empty).toBe("Fragment Match annotation not available");
  expect(sections.find((section) => section.key === "mass-accuracy")?.empty).toBe("Mass accuracy not available");
});

test("DIA-CLIP metadata adds a source-specific evidence section without changing DIA-NN sections", () => {
  const sections = buildBuEvidenceSummary({
    match: {
      ...match,
      score: 0.91,
      intensity: 1234,
      extra_metadata: {
        diaclip: {
          feature_distance: 0.12,
          cos_similarity: 0.98,
          quant_result: 1234,
          diann_q_value: 0.004,
          diann_precursor_quantity: 999,
        },
      },
    },
    xic: { isLoading: false, isError: true },
    ms2: { isLoading: false, isError: true },
    hasPfmb: false,
    pfmbSlots: { isLoading: false, isError: false },
    pfmbAnnotation: { isLoading: false, isError: false },
    activePfmbSlot: null,
    inspectedRt: null,
    selectedXicPoint: null,
  });

  const diaclip = sections.find((section) => section.key === "diaclip");
  expect(diaclip?.rows.map((row) => row.label)).toEqual([
    "DIA-CLIP score",
    "Feature distance",
    "Cosine similarity",
    "DIA-CLIP quantity",
    "Reference q-value",
    "Reference precursor quantity",
  ]);
  expect(diaclip?.rows.find((row) => row.label === "DIA-CLIP score")?.value).toBe("0.91");
  expect(sections).toHaveLength(6);
});
