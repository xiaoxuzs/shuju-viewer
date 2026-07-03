import type { SpectraScanIndexItem } from "@/features/spectra-only/types";

export type ScanLevelFilter = "all" | "ms1" | "ms2";

export interface PeakLike {
  mz: number;
  intensity: number;
}

export interface PrecursorPeakMatch {
  targetMz: number;
  peak: PeakLike;
  errorDa: number;
  errorPpm: number;
}

export function filterScansByMsLevel(
  scans: SpectraScanIndexItem[],
  filter: ScanLevelFilter,
): SpectraScanIndexItem[] {
  if (filter === "ms1") return scans.filter((scan) => scan.ms_level === 1);
  if (filter === "ms2") return scans.filter((scan) => scan.ms_level === 2);
  return scans;
}

export function findParentMs1Scan(
  scans: SpectraScanIndexItem[],
  selectedScan: SpectraScanIndexItem | null,
): SpectraScanIndexItem | null {
  if (!selectedScan || selectedScan.ms_level !== 2) return null;
  const selectedIndex = findScanIndex(scans, selectedScan);
  if (selectedIndex < 0) return null;
  for (let index = selectedIndex - 1; index >= 0; index -= 1) {
    if (scans[index].ms_level === 1) return scans[index];
  }
  return null;
}

export function findChildMs2Scans(
  scans: SpectraScanIndexItem[],
  parentMs1Scan: SpectraScanIndexItem | null,
): SpectraScanIndexItem[] {
  if (!parentMs1Scan || parentMs1Scan.ms_level !== 1) return [];
  const parentIndex = findScanIndex(scans, parentMs1Scan);
  if (parentIndex < 0) return [];

  const children: SpectraScanIndexItem[] = [];
  for (let index = parentIndex + 1; index < scans.length; index += 1) {
    const scan = scans[index];
    if (scan.ms_level === 1) break;
    if (scan.ms_level === 2) children.push(scan);
  }
  return children;
}

export function findNearestPeakByMz(
  peaks: PeakLike[],
  targetMz: number | null | undefined,
  toleranceDa = 0.05,
): PrecursorPeakMatch | null {
  if (typeof targetMz !== "number" || !Number.isFinite(targetMz)) return null;
  if (toleranceDa < 0) return null;

  let best: PeakLike | null = null;
  let bestError = Number.POSITIVE_INFINITY;
  for (const peak of peaks) {
    if (!Number.isFinite(peak.mz) || !Number.isFinite(peak.intensity)) continue;
    const error = peak.mz - targetMz;
    if (Math.abs(error) < Math.abs(bestError)) {
      best = peak;
      bestError = error;
    }
  }
  if (!best || Math.abs(bestError) > toleranceDa) return null;
  return {
    targetMz,
    peak: best,
    errorDa: bestError,
    errorPpm: targetMz === 0 ? 0 : (bestError / targetMz) * 1_000_000,
  };
}

export function formatMassError(match: PrecursorPeakMatch | null): string {
  if (!match) return "-";
  return `${match.errorDa.toFixed(4)} Da (${match.errorPpm.toFixed(1)} ppm)`;
}

function findScanIndex(
  scans: SpectraScanIndexItem[],
  target: SpectraScanIndexItem,
): number {
  return scans.findIndex((scan) => scan.scan_number === target.scan_number);
}
