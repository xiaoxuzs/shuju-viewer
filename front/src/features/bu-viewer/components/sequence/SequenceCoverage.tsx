import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { BuProteinDetailOut } from "@/features/bu-viewer/types";

import { CoverageBar } from "./CoverageBar";
import { PeptideLegend } from "./PeptideLegend";
import {
  SELECTED_PEPTIDE_HIGHLIGHT,
  coverageMarkerBackground,
} from "./coverageColors";
import {
  buildPeptideColorMap,
  buildPeptideLegend,
  buildPeptideSelectionKey,
  formatSegmentTooltip,
  getMappedSegments,
  resolveResidueColor,
  splitSequenceRows,
  type MappedCoverageSegment,
  type PeptideColorMap,
} from "./coverageLayout";

const CHUNK = 50;
const UNCOVERED_COLOR = "#111111";
const SELECTED_TEXT_COLOR = "#111827";
const SIDEBAR_MIN_HEIGHT = 224;

export function SequenceCoverage({ protein }: { protein: BuProteinDetailOut }) {
  const [selectedPeptideKey, setSelectedPeptideKey] = useState<string | null>(null);
  const [leftPanelHeight, setLeftPanelHeight] = useState(SIDEBAR_MIN_HEIGHT);
  const leftPanelRef = useRef<HTMLDivElement | null>(null);
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
  const title = `Sequence coverage - ${protein.accession}${proteinName ? ` (${proteinName})` : ""}`;
  const coverageLabel =
    protein.coverage_percent === null ? "-" : `${Math.round(protein.coverage_percent * 100)}%`;

  useEffect(() => {
    setSelectedPeptideKey(null);
  }, [protein.id]);

  useEffect(() => {
    const node = leftPanelRef.current;
    if (!showCoverage || !node) return;

    const measure = () => {
      setLeftPanelHeight(Math.max(SIDEBAR_MIN_HEIGHT, Math.ceil(node.getBoundingClientRect().height)));
    };

    measure();
    if (typeof ResizeObserver === "undefined") return;

    const observer = new ResizeObserver((entries) => {
      const height = entries[0]?.contentRect.height ?? node.getBoundingClientRect().height;
      setLeftPanelHeight(Math.max(SIDEBAR_MIN_HEIGHT, Math.ceil(height)));
    });
    observer.observe(node);

    return () => observer.disconnect();
  }, [showCoverage]);

  const sidebarStyle = {
    "--coverage-sidebar-height": `${leftPanelHeight}px`,
  } as CSSProperties;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="text-base">{title}</CardTitle>
            <CardDescription className="mt-1">
              Coverage: {coverageLabel} - {legendItems.length} peptides
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
          <div
            className={
              legendItems.length > 0
                ? "grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(17.5rem,22rem)] lg:items-stretch"
                : "space-y-4"
            }
          >
            <div ref={leftPanelRef} className="min-w-0 space-y-4">
              <SequenceRows
                sequence={sequence}
                segments={mappedSegments}
                colorMap={colorMap}
                selectedPeptideKey={selectedPeptideKey}
              />
              <div className="pl-14">
                <CoverageBar
                  sequenceLength={sequence.length}
                  segments={mappedSegments}
                  colorMap={colorMap}
                  chunkSize={CHUNK}
                />
              </div>
            </div>
            {legendItems.length > 0 && (
              <aside
                className="min-h-0 min-w-0 self-start overflow-hidden border-t border-border/70 pt-4 lg:flex lg:h-[var(--coverage-sidebar-height)] lg:max-h-[var(--coverage-sidebar-height)] lg:flex-col lg:border-l lg:border-t-0 lg:pl-4 lg:pt-0"
                style={sidebarStyle}
              >
                <div className="mb-2 flex shrink-0 items-baseline justify-between gap-2">
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Peptides
                  </h4>
                  <span className="text-xs text-muted-foreground">
                    {legendItems.length.toLocaleString()}
                  </span>
                </div>
                <PeptideLegend
                  items={legendItems}
                  selectedPeptideKey={selectedPeptideKey}
                  onSelect={setSelectedPeptideKey}
                />
              </aside>
            )}
          </div>
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
  selectedPeptideKey,
}: {
  sequence: string;
  segments: MappedCoverageSegment[];
  colorMap: PeptideColorMap;
  selectedPeptideKey: string | null;
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
                const residue = resolveResidueColor(index, segments, colorMap, selectedPeptideKey);
                const selected = Boolean(residue?.selected);

                return (
                  <span
                    key={index}
                    className={`inline-block w-[1.15rem] rounded-[2px] text-center ${
                      residue ? "font-bold" : "font-normal"
                    }`}
                    data-peptide-key={residue ? buildPeptideSelectionKey(residue.segment) : undefined}
                    data-selected={selected ? "true" : undefined}
                    data-testid={residue ? "covered-residue" : undefined}
                    style={{
                      backgroundColor: residue
                        ? selected
                          ? SELECTED_PEPTIDE_HIGHLIGHT
                          : coverageMarkerBackground(residue.color, 0.18)
                        : undefined,
                      boxShadow: selected ? "0 0 0 1px rgba(250, 204, 21, 0.65)" : undefined,
                      color: residue
                        ? selected
                          ? SELECTED_TEXT_COLOR
                          : residue.color
                        : UNCOVERED_COLOR,
                    }}
                    title={residue ? formatSegmentTooltip(residue.segment) : undefined}
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

function Notice({ tone, children }: { tone: "muted" | "warning"; children: ReactNode }) {
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
