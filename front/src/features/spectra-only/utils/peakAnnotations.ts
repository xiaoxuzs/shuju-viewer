export type PeakLabelMode = "off" | "top5" | "top10" | "top20";

export interface RawPeakLike {
  mz: number | string | null | undefined;
  intensity: number | string | null | undefined;
  key?: string | null;
  sourceIndex?: number | null;
}

export interface NormalizedPeak {
  mz: number;
  intensity: number;
  key: string;
  sourceIndex: number;
}

export interface PeakAnnotation {
  peak: NormalizedPeak;
  rank: number;
  relativeIntensity: number;
  isBasePeak: boolean;
  isTopPeak: boolean;
  isSelected: boolean;
}

export interface PeakAnnotationResult {
  normalizedPeaks: NormalizedPeak[];
  basePeak: NormalizedPeak | null;
  basePeakIntensity: number;
  labelAnnotations: PeakAnnotation[];
  tableAnnotations: PeakAnnotation[];
  selectedAnnotation: PeakAnnotation | null;
}

const TABLE_LIMIT_WHEN_LABELS_OFF = 10;

export const DEFAULT_PEAK_LABEL_MODE: PeakLabelMode = "top10";

export const PEAK_LABEL_OPTIONS: Array<{ value: PeakLabelMode; label: string }> = [
  { value: "off", label: "Off" },
  { value: "top5", label: "Top 5" },
  { value: "top10", label: "Top 10" },
  { value: "top20", label: "Top 20" },
];

export function normalizePeaks(peaks: RawPeakLike[]): NormalizedPeak[] {
  return peaks.reduce<NormalizedPeak[]>((items, peak, index) => {
    const mz = toFiniteNumber(peak.mz);
    const intensity = toFiniteNumber(peak.intensity);
    if (mz == null || intensity == null) return items;

    const sourceIndex =
      typeof peak.sourceIndex === "number" && Number.isFinite(peak.sourceIndex)
        ? peak.sourceIndex
        : index;
    items.push({
      mz,
      intensity,
      sourceIndex,
      key: typeof peak.key === "string" && peak.key.length > 0
        ? peak.key
        : makePeakKey(sourceIndex, mz, intensity),
    });
    return items;
  }, []);
}

export function getBasePeak(peaks: RawPeakLike[]): NormalizedPeak | null {
  const normalized = normalizePeaks(peaks);
  let basePeak: NormalizedPeak | null = null;
  for (const peak of normalized) {
    if (!basePeak || peak.intensity > basePeak.intensity) {
      basePeak = peak;
    }
  }
  return basePeak;
}

export function getTopPeaks(peaks: RawPeakLike[], topN: number): NormalizedPeak[] {
  if (!Number.isFinite(topN) || topN <= 0) return [];
  return normalizePeaks(peaks)
    .sort(comparePeaksByIntensity)
    .slice(0, Math.floor(topN));
}

export function getRelativeIntensity(
  peak: RawPeakLike,
  basePeakIntensity: number | null | undefined,
): number {
  const intensity = toFiniteNumber(peak.intensity);
  if (intensity == null || !basePeakIntensity || basePeakIntensity <= 0) return 0;
  return (intensity / basePeakIntensity) * 100;
}

export function findNearestPeakByMz(
  peaks: RawPeakLike[],
  targetMz: number | string | null | undefined,
  toleranceDa: number,
): NormalizedPeak | null {
  const target = toFiniteNumber(targetMz);
  if (target == null || toleranceDa < 0) return null;

  let best: NormalizedPeak | null = null;
  let bestError = Number.POSITIVE_INFINITY;
  for (const peak of normalizePeaks(peaks)) {
    const error = peak.mz - target;
    if (Math.abs(error) < Math.abs(bestError)) {
      best = peak;
      bestError = error;
    }
  }
  if (!best || Math.abs(bestError) > toleranceDa) return null;
  return best;
}

export function buildPeakAnnotations(
  peaks: RawPeakLike[],
  mode: PeakLabelMode,
  selectedPeak: RawPeakLike | null = null,
): PeakAnnotationResult {
  const normalizedPeaks = normalizePeaks(peaks);
  const rankedPeaks = normalizedPeaks.slice().sort(comparePeaksByIntensity);
  const rankByKey = new Map<string, number>();
  rankedPeaks.forEach((peak, index) => rankByKey.set(peak.key, index + 1));

  const basePeak = rankedPeaks[0] ?? null;
  const basePeakIntensity = basePeak?.intensity ?? 0;
  const selected = selectedPeak ? resolveSelectedPeak(normalizedPeaks, selectedPeak) : null;

  const labelLimit = getPeakLabelLimit(mode);
  const tableLimit = getPeakTableLimit(mode);
  const labelKeys = new Set(rankedPeaks.slice(0, labelLimit).map((peak) => peak.key));
  const tablePeaks = rankedPeaks.slice(0, tableLimit);

  return {
    normalizedPeaks,
    basePeak,
    basePeakIntensity,
    labelAnnotations: rankedPeaks
      .filter((peak) => labelKeys.has(peak.key))
      .map((peak) => annotatePeak(peak, rankByKey, basePeak, labelKeys, selected)),
    tableAnnotations: tablePeaks.map((peak) =>
      annotatePeak(peak, rankByKey, basePeak, new Set(tablePeaks.map((item) => item.key)), selected),
    ),
    selectedAnnotation: selected
      ? annotatePeak(selected, rankByKey, basePeak, labelKeys, selected)
      : null,
  };
}

export function getPeakLabelLimit(mode: PeakLabelMode): number {
  if (mode === "top5") return 5;
  if (mode === "top10") return 10;
  if (mode === "top20") return 20;
  return 0;
}

export function getPeakTableLimit(mode: PeakLabelMode): number {
  return mode === "off" ? TABLE_LIMIT_WHEN_LABELS_OFF : getPeakLabelLimit(mode);
}

export function formatPeakMz(value: number): string {
  return value.toFixed(4);
}

export function formatPeakRelativeIntensity(value: number): string {
  return `${value.toFixed(1)}%`;
}

export function formatPeakIntensity(value: number): string {
  if (value === 0) return "0";
  const absolute = Math.abs(value);
  if (absolute >= 100_000 || absolute < 0.01) return value.toExponential(3);
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function makePeakKey(sourceIndex: number, mz: number, intensity: number): string {
  return `${sourceIndex}:${mz}:${intensity}`;
}

function annotatePeak(
  peak: NormalizedPeak,
  rankByKey: Map<string, number>,
  basePeak: NormalizedPeak | null,
  topPeakKeys: Set<string>,
  selectedPeak: NormalizedPeak | null,
): PeakAnnotation {
  return {
    peak,
    rank: rankByKey.get(peak.key) ?? 0,
    relativeIntensity: getRelativeIntensity(peak, basePeak?.intensity ?? 0),
    isBasePeak: basePeak?.key === peak.key,
    isTopPeak: topPeakKeys.has(peak.key),
    isSelected: selectedPeak?.key === peak.key,
  };
}

function resolveSelectedPeak(
  peaks: NormalizedPeak[],
  selectedPeak: RawPeakLike,
): NormalizedPeak | null {
  const normalizedSelected = normalizePeaks([selectedPeak])[0];
  if (!normalizedSelected) return null;
  return (
    peaks.find((peak) => peak.key === normalizedSelected.key) ??
    peaks.find(
      (peak) =>
        peak.mz === normalizedSelected.mz &&
        peak.intensity === normalizedSelected.intensity,
    ) ??
    null
  );
}

function comparePeaksByIntensity(left: NormalizedPeak, right: NormalizedPeak): number {
  if (right.intensity !== left.intensity) return right.intensity - left.intensity;
  if (left.mz !== right.mz) return left.mz - right.mz;
  return left.sourceIndex - right.sourceIndex;
}

function toFiniteNumber(value: number | string | null | undefined): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string") return null;
  const parsed = Number(value.trim());
  return Number.isFinite(parsed) ? parsed : null;
}
