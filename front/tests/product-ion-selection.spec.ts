import { expect, test } from "@playwright/test";

import type { BuMatchedIon, BuProductXicOut } from "../src/features/bu/types";
import {
  MAX_PRODUCT_ION_XICS,
  addProductIonSelection,
  addTopProductIons,
  buildProductIonId,
  clearProductIonSelections,
  toggleProductIonSelection,
  toProductIonSelection,
} from "../src/features/bu/components/match-detail/productIonSelection";
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
