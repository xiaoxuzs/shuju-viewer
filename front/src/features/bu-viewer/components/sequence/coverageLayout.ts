import type { BuCoverageSegment } from "@/features/bu-viewer/types";

import { COVERAGE_PEPTIDE_COLORS } from "./coverageColors";

export interface SequenceRow {
  start: number;
  end: number;
  text: string;
}

export type MappedCoverageSegment = Omit<BuCoverageSegment, "start" | "end"> & {
  start: number;
  end: number;
};

export interface PeptideLegendItem {
  key: string;
  peptideId: number;
  sequence: string;
  color: string;
  ambiguous: boolean;
}

export interface ResidueCoverage {
  color: string;
  segment: MappedCoverageSegment;
  selected: boolean;
}

export type PeptideColorMap = Map<string, string>;

export function splitSequenceRows(seq: string, chunkSize = 50): SequenceRow[] {
  const requestedSize = Number.isFinite(chunkSize) ? Math.floor(chunkSize) : 50;
  const size = Math.max(1, requestedSize);
  const rows: SequenceRow[] = [];

  for (let start = 0; start < seq.length; start += size) {
    const end = Math.min(start + size, seq.length);
    rows.push({ start, end, text: seq.slice(start, end) });
  }

  return rows;
}

export function getMappedSegments(
  segments: BuCoverageSegment[],
  sequenceLength: number,
): MappedCoverageSegment[] {
  const safeLength = Number.isFinite(sequenceLength) ? Math.max(0, sequenceLength) : 0;
  const mapped: MappedCoverageSegment[] = [];

  for (const segment of segments) {
    const { start, end } = segment;
    if (start === null || end === null) continue;
    if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
    if (start < 0 || end > safeLength || start >= end) continue;

    mapped.push({ ...segment, start, end });
  }

  return mapped.sort(
    (a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start),
  );
}

export function buildPeptideSelectionKey(segment: MappedCoverageSegment): string {
  if (Number.isFinite(segment.peptide_id)) return `peptide:${segment.peptide_id}`;

  return [
    "segment",
    segment.sequence,
    segment.start,
    segment.end,
    segment.occurrence_index,
  ].join(":");
}

export function buildPeptideColorMap(mapped: MappedCoverageSegment[]): PeptideColorMap {
  const colorMap: PeptideColorMap = new Map();

  for (const segment of mapped) {
    const key = buildPeptideSelectionKey(segment);
    if (colorMap.has(key)) continue;
    const colorIndex = colorMap.size % COVERAGE_PEPTIDE_COLORS.length;
    colorMap.set(key, COVERAGE_PEPTIDE_COLORS[colorIndex]);
  }

  return colorMap;
}

export function buildPeptideLegend(
  mapped: MappedCoverageSegment[],
  colorMap: PeptideColorMap,
): PeptideLegendItem[] {
  const items = new Map<string, PeptideLegendItem>();

  for (const segment of mapped) {
    const key = buildPeptideSelectionKey(segment);
    const color = colorMap.get(key);
    if (!color) continue;

    const existing = items.get(key);
    if (existing) {
      if (segment.is_ambiguous) existing.ambiguous = true;
      continue;
    }

    items.set(key, {
      key,
      peptideId: segment.peptide_id,
      sequence: segment.sequence,
      color,
      ambiguous: segment.is_ambiguous,
    });
  }

  return Array.from(items.values());
}

export function resolveResidueColor(
  pos: number,
  mapped: MappedCoverageSegment[],
  colorMap: PeptideColorMap,
  selectedPeptideKey: string | null = null,
): ResidueCoverage | null {
  let fallback: ResidueCoverage | null = null;

  for (const segment of mapped) {
    if (segment.start <= pos && pos < segment.end) {
      const key = buildPeptideSelectionKey(segment);
      const color = colorMap.get(key);
      if (!color) continue;

      if (selectedPeptideKey === key) {
        return { color, segment, selected: true };
      }

      if (!fallback) fallback = { color, segment, selected: false };
    }
  }

  return fallback;
}

export function getSegmentColor(
  segment: MappedCoverageSegment,
  colorMap: PeptideColorMap,
): string | undefined {
  return colorMap.get(buildPeptideSelectionKey(segment));
}

export function formatSegmentTooltip(segment: MappedCoverageSegment): string {
  return `${segment.sequence} [${segment.start}, ${segment.end}) - peptide #${segment.peptide_id}`;
}
