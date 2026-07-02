import type { BuPfmbMatchedIon } from "@/features/bu-viewer/types";
import {
  PFMB_SERIES_COLOR,
  ionLabel,
  neutralToMz,
} from "@/features/bu-viewer/components/match-detail/pfmbSeries";
import type { SpectrumExternalAnnotation } from "@/features/bu-viewer/components/spectrum/spectrumAnnotation";

export interface PfmbSpectrumOverlay {
  annotations: SpectrumExternalAnnotation[];
  mappedAnnotations: SpectrumExternalAnnotation[];
  totalCount: number;
  mappedCount: number;
  unmappedCount: number;
}

export function buildPfmbSpectrumOverlay({
  ions,
  rawMz,
  rawIntensity,
  ppmTolerance = 20,
}: {
  ions: BuPfmbMatchedIon[];
  rawMz: number[];
  rawIntensity: number[];
  ppmTolerance?: number;
}): PfmbSpectrumOverlay {
  const annotations = ions.map((ion) => {
    const expMz = neutralToMz(ion.observed_neutral_mass, ion.charge);
    const theoMz = neutralToMz(ion.theoretical_neutral_mass, ion.charge);
    const rawPeak = findNearestRawPeak(rawMz, rawIntensity, expMz, ppmTolerance);
    return {
      id: `pfmb:${ion.peak_id}:${ion.ion_type}:${ion.fragment_ordinal}:${ion.charge}`,
      source: "pfmb",
      ionType: ion.ion_type,
      position: ion.fragment_ordinal,
      charge: ion.charge,
      expMz,
      theoMz,
      ppm: ion.mass_error_ppm,
      massErrorDa: ion.mass_error_da,
      label: ionLabel(ion),
      matchedPeakMz: rawPeak?.mz,
      matchedPeakIntensity: rawPeak?.intensity,
      isMappedToRawPeak: rawPeak !== null,
      color: PFMB_SERIES_COLOR[ion.ion_type],
    } satisfies SpectrumExternalAnnotation;
  });
  const mappedAnnotations = annotations.filter((annotation) => annotation.isMappedToRawPeak);
  return {
    annotations,
    mappedAnnotations,
    totalCount: annotations.length,
    mappedCount: mappedAnnotations.length,
    unmappedCount: annotations.length - mappedAnnotations.length,
  };
}

function findNearestRawPeak(
  rawMz: number[],
  rawIntensity: number[],
  targetMz: number,
  ppmTolerance: number,
): { mz: number; intensity: number } | null {
  let bestIndex: number | null = null;
  let bestPpm = Infinity;
  for (let i = 0; i < rawMz.length; i++) {
    const mz = rawMz[i];
    if (!Number.isFinite(mz)) continue;
    const deltaPpm = Math.abs(((mz - targetMz) / targetMz) * 1_000_000);
    if (deltaPpm <= ppmTolerance && deltaPpm < bestPpm) {
      bestPpm = deltaPpm;
      bestIndex = i;
    }
  }
  return bestIndex === null
    ? null
    : { mz: rawMz[bestIndex], intensity: rawIntensity[bestIndex] ?? 0 };
}
