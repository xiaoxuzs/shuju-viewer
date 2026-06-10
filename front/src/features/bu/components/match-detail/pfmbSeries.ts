import type { BuPfmbMatchedIon } from "@/features/bu/types";

export type PfmbIonType = BuPfmbMatchedIon["ion_type"];

// Fixed colors per fragment series, shared by the PFMB table, spectrum chart,
// sequence-coverage map and heatmap so a series always reads the same.
export const PFMB_SERIES_COLOR: Record<PfmbIonType, string> = {
  b: "#1f77b4",
  y: "#d62728",
  c: "#2ca02c",
  z_dot: "#7952b3",
};

export const PROTON_MASS = 1.007276466812;
const MODIFICATION_RE = /\[[^\]]*\]/g;

// ASCII label for a series (z_dot is rendered as "z." to avoid mojibake glyphs).
export function seriesLabel(ionType: PfmbIonType): string {
  return ionType === "z_dot" ? "z." : ionType;
}

// Charge-merged family key, e.g. "b5" / "y7". Used for cross-component
// highlighting where charge is intentionally ignored.
export function ionFamilyKey(ion: Pick<BuPfmbMatchedIon, "ion_type" | "fragment_ordinal">): string {
  return `${ion.ion_type}${ion.fragment_ordinal}`;
}

export function ionLabel(ion: Pick<BuPfmbMatchedIon, "ion_type" | "fragment_ordinal" | "charge">): string {
  return `${seriesLabel(ion.ion_type)}${ion.fragment_ordinal}${ion.charge > 1 ? `^${ion.charge}+` : ""}`;
}

export function pfmbResidues(peptide: string): string[] {
  return peptide.replace(MODIFICATION_RE, "").split("");
}

// Cleavage site (1..len-1) covered by a fragment ion.
// b/c ions count from the N-terminus; y/z. ions from the C-terminus.
export function cleavageSite(
  ion: Pick<BuPfmbMatchedIon, "ion_type" | "fragment_ordinal">,
  peptideLength: number,
): number {
  if (ion.ion_type === "b" || ion.ion_type === "c") return ion.fragment_ordinal;
  return peptideLength - ion.fragment_ordinal;
}

// Convert a PFMB neutral mass to m/z for a given charge.
export function neutralToMz(neutralMass: number, charge: number): number {
  if (charge <= 0) return neutralMass;
  return (neutralMass + charge * PROTON_MASS) / charge;
}
