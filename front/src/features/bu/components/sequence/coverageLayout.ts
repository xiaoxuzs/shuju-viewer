import type { BuCoverageSegment } from "@/features/bu/types";

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
  peptideId: number;
  sequence: string;
  color: string;
  ambiguous: boolean;
}

export interface ResidueCoverage {
  color: string;
  segment: MappedCoverageSegment;
}

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

export function buildPeptideColorMap(mapped: MappedCoverageSegment[]): Map<number, string> {
  const colorMap = new Map<number, string>();

  for (const segment of mapped) {
    if (colorMap.has(segment.peptide_id)) continue;
    const colorIndex = colorMap.size % COVERAGE_PEPTIDE_COLORS.length;
    colorMap.set(segment.peptide_id, COVERAGE_PEPTIDE_COLORS[colorIndex]);
  }

  return colorMap;
}

export function buildPeptideLegend(
  mapped: MappedCoverageSegment[],
  colorMap: Map<number, string>,
): PeptideLegendItem[] {
  const items = new Map<number, PeptideLegendItem>();

  for (const segment of mapped) {
    const color = colorMap.get(segment.peptide_id);
    if (!color) continue;

    const existing = items.get(segment.peptide_id);
    if (existing) {
      if (segment.is_ambiguous) existing.ambiguous = true;
      continue;
    }

    items.set(segment.peptide_id, {
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
  colorMap: Map<number, string>,
): ResidueCoverage | null {
  for (const segment of mapped) {
    if (segment.start <= pos && pos < segment.end) {
      const color = colorMap.get(segment.peptide_id);
      return color ? { color, segment } : null;
    }
  }

  return null;
}

export function formatSegmentTooltip(segment: MappedCoverageSegment): string {
  return `${segment.sequence} [${segment.start}, ${segment.end}) · peptide #${segment.peptide_id}`;
}
