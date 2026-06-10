import { expect, test } from "@playwright/test";

import type {
  BuMatchedIon,
  BuProductXicBatchOut,
  BuProductXicOut,
} from "../src/features/bu/types";
import {
  MAX_PRODUCT_ION_XICS,
  addProductIonSelection,
  addTopProductIons,
  buildProductIonId,
  clearProductIonSelections,
  isProductIonSelected,
  toggleProductIonSelection,
  toProductIonSelection,
} from "../src/features/bu/components/match-detail/productIonSelection";
import {
  buildProductIonBatchQueryKey,
  buildProductIonBatchTraces,
} from "../src/features/bu/components/match-detail/productIonBatch";
import { assignProductIonColors } from "../src/features/bu/components/match-detail/productIonColors";
import {
  buildProductIonXicTrace,
  normalizeProductIonTrace,
} from "../src/features/bu/components/match-detail/productIonXicViewModel";

function matchedIon(position: number, charge = 1, intensity = 100): BuMatchedIon {
  return {
    ion_type: "y",
    position,
    charge,
    theo_mz: 100 + position + charge / 10,
    exp_mz: 100 + position + charge / 10,
    ppm: 0,
    intensity,
  };
}

test("toggles a product ion and distinguishes charge states", () => {
  const singlyCharged = toProductIonSelection(matchedIon(5, 1))!;
  const doublyCharged = toProductIonSelection(matchedIon(5, 2))!;

  const added = toggleProductIonSelection([], singlyCharged);
  expect(added.selections).toEqual([singlyCharged]);
  expect(buildProductIonId(singlyCharged)).not.toBe(buildProductIonId(doublyCharged));
  expect(addProductIonSelection(added.selections, singlyCharged).selections).toBe(added.selections);
  expect(addProductIonSelection(added.selections, doublyCharged).selections).toHaveLength(2);
  expect(toggleProductIonSelection(added.selections, singlyCharged).selections).toEqual([]);
});

test("enforces the product ion comparison limit", () => {
  const selections = Array.from({ length: MAX_PRODUCT_ION_XICS }, (_, index) =>
    toProductIonSelection(matchedIon(index + 1))!,
  );
  const result = addProductIonSelection(selections, toProductIonSelection(matchedIon(20))!);

  expect(result.limitReached).toBe(true);
  expect(result.selections).toBe(selections);
});

test("adds the top three valid live matched fragments without duplicates", () => {
  const existing = toProductIonSelection(matchedIon(2, 1, 200))!;
  const invalidMz = { ...matchedIon(9, 1, 999), theo_mz: Number.NaN };
  const result = addTopProductIons(
    [existing],
    [
      matchedIon(1, 1, 100),
      matchedIon(2, 1, 200),
      invalidMz,
      matchedIon(3, 1, 300),
      matchedIon(4, 1, 50),
    ],
  );

  expect(result.selections.map((ion) => ion.position)).toEqual([2, 3, 1, 4]);
  expect(result.limitReached).toBe(false);
  expect(clearProductIonSelections()).toEqual([]);
});

test("normalizes traces defensively and preserves raw values", () => {
  expect(normalizeProductIonTrace([])).toEqual([]);
  expect(normalizeProductIonTrace([{ rt: 1, intensity: 0 }])).toEqual([{ rt: 1, intensity: 0 }]);
  expect(normalizeProductIonTrace([
    { rt: 1, intensity: 10 },
    { rt: 2, intensity: 20 },
  ])).toEqual([
    { rt: 1, intensity: 50 },
    { rt: 2, intensity: 100 },
  ]);

  const selection = toProductIonSelection(matchedIon(5))!;
  const xic: BuProductXicOut = {
    curve_type: "PRODUCT_ION_XIC",
    x_axis: "rt",
    y_axis: "intensity",
    unit_rt: "min",
    product_mz: selection.theoreticalMz,
    ppm: 20,
    precursor_mz: 477.3,
    isolation_filter: true,
    points: [{ rt: 1, intensity: 25, scan: 1 }],
  };
  expect(buildProductIonXicTrace(selection, xic, "#123456", "raw").points[0].intensity).toBe(25);
  expect(buildProductIonXicTrace(selection, xic, "#123456", "normalized").points[0].intensity).toBe(100);
});

test("assigns unique stable colors for active ions", () => {
  const first = assignProductIonColors(["a", "b", "c"]);
  const second = assignProductIonColors(["b", "c"], first.assignments);
  const third = assignProductIonColors(["a", "b", "c"], second.assignments);

  expect(new Set(Object.values(first.colors)).size).toBe(3);
  expect(second.colors.b).toBe(first.colors.b);
  expect(third.colors.a).toBe(first.colors.a);
});

test("keeps table selection stable when rows are reordered", () => {
  const selected = toProductIonSelection(matchedIon(5, 2))!;
  const selectedIds = new Set([selected.id]);
  const reordered = [matchedIon(7), matchedIon(5, 2), matchedIon(1)];

  expect(reordered.map((ion) => isProductIonSelected(ion, selectedIds))).toEqual([false, true, false]);
});

test("canonical batch query key ignores selection order", () => {
  const first = toProductIonSelection(matchedIon(1))!;
  const second = toProductIonSelection(matchedIon(2, 2))!;
  const context = {
    datasetId: 39,
    slug: "demo",
    matchId: 1,
    runId: 10,
    ms2Scan: 100,
    tolerancePpm: 20,
    rtWindowOverride: null,
  };

  expect(buildProductIonBatchQueryKey({ ...context, selections: [first, second] })).toEqual(
    buildProductIonBatchQueryKey({ ...context, selections: [second, first] }),
  );
});

test("batch traces preserve display order and tolerate partial statuses", () => {
  const first = toProductIonSelection(matchedIon(1))!;
  const second = toProductIonSelection(matchedIon(2))!;
  const third = toProductIonSelection(matchedIon(3))!;
  const response: BuProductXicBatchOut = {
    traces: [
      {
        id: third.id,
        ion: third.ion,
        series: third.series,
        position: third.position,
        charge: third.charge,
        mz: third.theoreticalMz,
        tolerance_ppm: 20,
        status: "error",
        error: "failed",
        points: [],
      },
      {
        id: second.id,
        ion: second.ion,
        series: second.series,
        position: second.position,
        charge: second.charge,
        mz: second.theoreticalMz,
        tolerance_ppm: 20,
        status: "no_signal",
        points: [{ rt: 1, intensity: 0, scan: 1 }],
      },
      {
        id: first.id,
        ion: first.ion,
        series: first.series,
        position: first.position,
        charge: first.charge,
        mz: first.theoreticalMz,
        tolerance_ppm: 20,
        status: "ok",
        points: [{ rt: 1, intensity: 25, scan: 1 }],
      },
    ],
  };

  const traces = buildProductIonBatchTraces(
    [second, first, third],
    response,
    { [first.id]: "#111", [second.id]: "#222", [third.id]: "#333" },
    "normalized",
  );

  expect(traces.map((trace) => trace.ionId)).toEqual([second.id, first.id]);
  expect(traces[0].points[0].intensity).toBe(0);
  expect(traces[1].points[0].intensity).toBe(100);
});
