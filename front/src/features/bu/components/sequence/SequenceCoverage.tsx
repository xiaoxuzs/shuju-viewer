import type React from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { BuProteinDetailOut } from "@/features/bu/types";

import { CoverageBar } from "./CoverageBar";
import { PeptideLegend } from "./PeptideLegend";
import {
  buildPeptideColorMap,
  buildPeptideLegend,
  formatSegmentTooltip,
  getMappedSegments,
  resolveResidueColor,
  splitSequenceRows,
  type MappedCoverageSegment,
} from "./coverageLayout";

const CHUNK = 50;
const UNCOVERED_COLOR = "#111111";

export function SequenceCoverage({ protein }: { protein: BuProteinDetailOut }) {
  const sequence = protein.base_sequence ?? "";
  const mappedSegments = getMappedSegments(protein.coverage_segments, sequence.length);
  const colorMap = buildPeptideColorMap(mappedSegments);
  const legendItems = buildPeptideLegend(mappedSegments, colorMap);
  const mappedPeptideIds = new Set(legendItems.map((item) => item.peptideId));
  const unmappedCount = protein.peptides.filter(
    (peptide) => !mappedPeptideIds.has(peptide.peptide_id),
  ).length;
  const showCoverage =
    Boolean(sequence) && protein.coverage_mode !== "decoy" && protein.coverage_mode !== "list_only";
  const proteinName = resolveProteinName(protein);
  const title = `Sequence coverage — ${protein.accession}${proteinName ? ` (${proteinName})` : ""}`;
  const coverageLabel =
    protein.coverage_percent === null ? "-" : `${Math.round(protein.coverage_percent * 100)}%`;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="text-base">{title}</CardTitle>
            <CardDescription className="mt-1">
              Coverage: {coverageLabel} · {legendItems.length} peptides
            </CardDescription>
          </div>
          <CoverageBadge protein={protein} />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {protein.coverage_mode === "decoy" && (
          <Notice tone="muted">Sequence coverage is unavailable for decoy proteins. Related peptides are listed below.</Notice>
        )}
        {protein.coverage_mode === "list_only" && (
          <Notice tone="muted">The protein sequence is unavailable. Only the peptide list is shown.</Notice>
        )}
        {protein.coverage_mode === "partial" && unmappedCount > 0 && (
          <Notice tone="warning">{unmappedCount.toLocaleString()} peptides could not be mapped to the sequence.</Notice>
        )}
        {showCoverage && (
          <>
            <SequenceRows sequence={sequence} segments={mappedSegments} colorMap={colorMap} />
            <div className="pl-14">
              <CoverageBar
                sequenceLength={sequence.length}
                segments={mappedSegments}
                colorMap={colorMap}
                chunkSize={CHUNK}
              />
            </div>
            <PeptideLegend items={legendItems} />
          </>
        )}
      </CardContent>
    </Card>
  );
}

function CoverageBadge({ protein }: { protein: BuProteinDetailOut }) {
  const labelMap: Record<BuProteinDetailOut["coverage_mode"], string> = {
    full: "full",
    partial: "partial",
    list_only: "list only",
    decoy: "decoy",
  };
  return <Badge variant={protein.coverage_mode === "full" ? "default" : "secondary"}>{labelMap[protein.coverage_mode]}</Badge>;
}

function SequenceRows({
  sequence,
  segments,
  colorMap,
}: {
  sequence: string;
  segments: MappedCoverageSegment[];
  colorMap: Map<number, string>;
}) {
  const rows = splitSequenceRows(sequence, CHUNK);

  return (
    <div className="overflow-x-auto py-1">
      <div className="min-w-max space-y-4 font-mono text-[10.5px] leading-6">
        {rows.map((row) => (
          <div key={row.start} className="flex items-baseline gap-4">
            <span className="w-10 shrink-0 select-none text-right text-xs text-muted-foreground">{row.start + 1}</span>
            <div className="whitespace-nowrap">
              {Array.from(row.text).map((aa, offset) => {
                const index = row.start + offset;
                const residue = resolveResidueColor(index, segments, colorMap);

                return (
                  <span
                    key={index}
                    title={residue ? formatSegmentTooltip(residue.segment) : undefined}
                    className={`inline-block w-[1.15rem] text-center ${
                      residue ? "font-bold" : "font-normal"
                    }`}
                    style={{ color: residue?.color ?? UNCOVERED_COLOR }}
                  >
                    {aa}
                  </span>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Notice({ tone, children }: { tone: "muted" | "warning"; children: React.ReactNode }) {
  return (
    <div
      className={
        tone === "warning"
          ? "rounded-md border border-amber-300/60 bg-amber-100/70 px-3 py-2 text-sm text-amber-900"
          : "rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground"
      }
    >
      {children}
    </div>
  );
}

function resolveProteinName(protein: BuProteinDetailOut): string | null {
  const geneName = protein.gene_name?.trim();
  if (geneName) return geneName;

  const description = protein.description?.trim();
  return description ? description.slice(0, 40) : null;
}
