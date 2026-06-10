import type { BuMatchedIon } from "@/features/bu/types";

export const MAX_PRODUCT_ION_XICS = 8;

export interface ProductIonSelection {
  id: string;
  ion: string;
  series: "b" | "y";
  position: number;
  charge: number;
  theoreticalMz: number;
  experimentalMz?: number;
  ppm?: number;
  intensity?: number;
}

export interface ProductIonSelectionResult {
  selections: ProductIonSelection[];
  limitReached: boolean;
}

function finiteOrUndefined(value: number): number | undefined {
  return Number.isFinite(value) ? value : undefined;
}

export function buildProductIonId(input: {
  ion: string;
  charge: number;
  theoreticalMz: number;
}): string {
  return `${input.ion}|${input.charge}|${input.theoreticalMz.toPrecision(12)}`;
}

export function productIonLabel(ion: Pick<ProductIonSelection, "ion" | "charge">): string {
  return `${ion.ion}${ion.charge > 1 ? `^${ion.charge}+` : ""}`;
}

export function toProductIonSelection(ion: BuMatchedIon | null | undefined): ProductIonSelection | null {
  if (
    !ion
    || (ion.ion_type !== "b" && ion.ion_type !== "y")
    || !Number.isInteger(ion.position)
    || ion.position <= 0
    || !Number.isInteger(ion.charge)
    || ion.charge <= 0
    || !Number.isFinite(ion.theo_mz)
    || ion.theo_mz <= 0
  ) {
    return null;
  }

  const selection = {
    ion: `${ion.ion_type}${ion.position}`,
    series: ion.ion_type,
    position: ion.position,
    charge: ion.charge,
    theoreticalMz: ion.theo_mz,
    experimentalMz: finiteOrUndefined(ion.exp_mz),
    ppm: finiteOrUndefined(ion.ppm),
    intensity: finiteOrUndefined(ion.intensity),
  };
  return { ...selection, id: buildProductIonId(selection) };
}

export function isSameProductIon(a: ProductIonSelection, b: ProductIonSelection): boolean {
  return a.id === b.id;
}

export function isProductIonSelected(
  ion: BuMatchedIon | null | undefined,
  selectedIds: ReadonlySet<string>,
): boolean {
  const selection = toProductIonSelection(ion);
  return selection !== null && selectedIds.has(selection.id);
}

export function addProductIonSelection(
  selections: ProductIonSelection[],
  ion: ProductIonSelection | null,
  maxSelections = MAX_PRODUCT_ION_XICS,
): ProductIonSelectionResult {
  if (!ion || selections.some((selected) => isSameProductIon(selected, ion))) {
    return { selections, limitReached: false };
  }
  if (selections.length >= maxSelections) {
    return { selections, limitReached: true };
  }
  return { selections: [...selections, ion], limitReached: false };
}

export function removeProductIonSelection(
  selections: ProductIonSelection[],
  ionId: string,
): ProductIonSelection[] {
  return selections.filter((ion) => ion.id !== ionId);
}

export function toggleProductIonSelection(
  selections: ProductIonSelection[],
  ion: ProductIonSelection | null,
  maxSelections = MAX_PRODUCT_ION_XICS,
): ProductIonSelectionResult {
  if (!ion) return { selections, limitReached: false };
  if (selections.some((selected) => isSameProductIon(selected, ion))) {
    return {
      selections: removeProductIonSelection(selections, ion.id),
      limitReached: false,
    };
  }
  return addProductIonSelection(selections, ion, maxSelections);
}

export function clearProductIonSelections(): ProductIonSelection[] {
  return [];
}

export function addTopProductIons(
  selections: ProductIonSelection[],
  matchedIons: BuMatchedIon[],
  count = 3,
  maxSelections = MAX_PRODUCT_ION_XICS,
): ProductIonSelectionResult {
  const ranked = matchedIons
    .map((ion, index) => ({ ion: toProductIonSelection(ion), index }))
    .filter(
      (item): item is { ion: ProductIonSelection; index: number } =>
        item.ion !== null && Number.isFinite(item.ion.intensity),
    )
    .sort((a, b) => (b.ion.intensity ?? 0) - (a.ion.intensity ?? 0) || a.index - b.index);

  let next = selections;
  let added = 0;
  let limitReached = false;
  for (const candidate of ranked) {
    if (added >= count) break;
    if (next.some((selected) => isSameProductIon(selected, candidate.ion))) continue;
    const result = addProductIonSelection(next, candidate.ion, maxSelections);
    if (result.limitReached) {
      limitReached = true;
      break;
    }
    next = result.selections;
    added += 1;
  }
  return { selections: next, limitReached };
}
