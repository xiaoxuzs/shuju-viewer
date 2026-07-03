import type { SpectraScanIndexItem } from "@/features/spectra-only/types";

export type ScanLevelFilter = "all" | "ms1" | "ms2";

export interface ScanRelations {
  orderedScans: SpectraScanIndexItem[];
  parentByMs2ScanNumber: Map<number, SpectraScanIndexItem>;
  childrenByMs1ScanNumber: Map<number, SpectraScanIndexItem[]>;
}

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
  if (filter === "ms1") return scans.filter((scan) => getMsLevel(scan) === 1);
  if (filter === "ms2") return scans.filter((scan) => getMsLevel(scan) === 2);
  return scans;
}

export function buildScanRelations(scans: SpectraScanIndexItem[]): ScanRelations {
  const orderedScans = orderScans(scans);
  const parentByMs2ScanNumber = new Map<number, SpectraScanIndexItem>();
  const childrenByMs1ScanNumber = new Map<number, SpectraScanIndexItem[]>();
  let currentParentMs1: SpectraScanIndexItem | null = null;

  for (const scan of orderedScans) {
    const level = getMsLevel(scan);
    const scanNumber = getScanNumber(scan);
    if (level === 1) {
      currentParentMs1 = scan;
      if (scanNumber != null && !childrenByMs1ScanNumber.has(scanNumber)) {
        childrenByMs1ScanNumber.set(scanNumber, []);
      }
      continue;
    }
    if (level !== 2 || currentParentMs1 == null || scanNumber == null) continue;

    const parentScanNumber = getScanNumber(currentParentMs1);
    if (parentScanNumber == null) continue;
    parentByMs2ScanNumber.set(scanNumber, currentParentMs1);
    const children = childrenByMs1ScanNumber.get(parentScanNumber) ?? [];
    children.push(scan);
    childrenByMs1ScanNumber.set(parentScanNumber, children);
  }

  return {
    orderedScans,
    parentByMs2ScanNumber,
    childrenByMs1ScanNumber,
  };
}

export function findParentMs1Scan(
  scans: SpectraScanIndexItem[],
  selectedScan: SpectraScanIndexItem | null,
): SpectraScanIndexItem | null {
  if (!selectedScan || getMsLevel(selectedScan) !== 2) return null;
  const selectedScanNumber = getScanNumber(selectedScan);
  if (selectedScanNumber == null) return null;
  return buildScanRelations(scans).parentByMs2ScanNumber.get(selectedScanNumber) ?? null;
}

export function findChildMs2Scans(
  scans: SpectraScanIndexItem[],
  parentMs1Scan: SpectraScanIndexItem | null,
): SpectraScanIndexItem[] {
  if (!parentMs1Scan || getMsLevel(parentMs1Scan) !== 1) return [];
  const parentScanNumber = getScanNumber(parentMs1Scan);
  if (parentScanNumber == null) return [];
  return buildScanRelations(scans).childrenByMs1ScanNumber.get(parentScanNumber) ?? [];
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

export function getMsLevel(scan: SpectraScanIndexItem | Record<string, unknown> | null | undefined): number | null {
  const value = getField(scan, "ms_level", "msLevel", "msLevelLabel");
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const normalized = value.trim().toLowerCase();
  if (normalized === "ms1") return 1;
  if (normalized === "ms2") return 2;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

export function getScanNumber(scan: SpectraScanIndexItem | Record<string, unknown> | null | undefined): number | null {
  const value = getField(scan, "scan_number", "scanNumber");
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const parsed = Number(value.trim());
  return Number.isFinite(parsed) ? parsed : null;
}

function orderScans(scans: SpectraScanIndexItem[]): SpectraScanIndexItem[] {
  return scans
    .map((scan, index) => ({ scan, index }))
    .sort((left, right) => {
      const leftScanNumber = getScanNumber(left.scan);
      const rightScanNumber = getScanNumber(right.scan);
      if (leftScanNumber != null && rightScanNumber != null && leftScanNumber !== rightScanNumber) {
        return leftScanNumber - rightScanNumber;
      }
      if (leftScanNumber == null && rightScanNumber == null) {
        const leftRt = getFiniteNumber(left.scan.retention_time);
        const rightRt = getFiniteNumber(right.scan.retention_time);
        if (leftRt != null && rightRt != null && leftRt !== rightRt) return leftRt - rightRt;
      }
      return left.index - right.index;
    })
    .map((entry) => entry.scan);
}

function getField(scan: SpectraScanIndexItem | Record<string, unknown> | null | undefined, ...names: string[]): unknown {
  if (!scan) return null;
  const record = scan as Record<string, unknown>;
  for (const name of names) {
    if (record[name] !== undefined) return record[name];
  }
  return null;
}

function getFiniteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const parsed = Number(value.trim());
  return Number.isFinite(parsed) ? parsed : null;
}
