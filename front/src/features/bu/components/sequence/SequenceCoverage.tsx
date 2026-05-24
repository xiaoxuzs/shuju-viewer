import type React from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { BuProteinDetailOut } from "@/features/bu/types";

const LINE_LENGTH = 70;

export function SequenceCoverage({ protein }: { protein: BuProteinDetailOut }) {
  const sequence = protein.base_sequence ?? "";
  const mappedSegments = protein.coverage_segments.filter((segment) => segment.start !== null && segment.end !== null);
  const unmappedCount = protein.peptides.filter(
    (peptide) => !mappedSegments.some((segment) => segment.peptide_id === peptide.peptide_id),
  ).length;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle className="text-base">Sequence coverage</CardTitle>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <CoverageBadge protein={protein} />
            {protein.coverage_percent !== null && (
              <span>{(protein.coverage_percent * 100).toFixed(1)}% covered</span>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {protein.coverage_mode === "decoy" && (
          <Notice tone="muted">Decoy 蛋白不提供 coverage；下方仍展示关联肽段。</Notice>
        )}
        {protein.coverage_mode === "list_only" && (
          <Notice tone="muted">蛋白序列不可用，仅展示肽段列表。</Notice>
        )}
        {protein.coverage_mode === "partial" && unmappedCount > 0 && (
          <Notice tone="warning">{unmappedCount.toLocaleString()} 条肽段未能映射到序列。</Notice>
        )}
        {sequence && protein.coverage_mode !== "decoy" && protein.coverage_mode !== "list_only" && (
          <SequenceRows sequence={sequence} segments={mappedSegments} />
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
}: {
  sequence: string;
  segments: BuProteinDetailOut["coverage_segments"];
}) {
  const residueStates = buildResidueStates(sequence.length, segments);
  const rows = [];
  for (let start = 0; start < sequence.length; start += LINE_LENGTH) {
    rows.push({ start, text: sequence.slice(start, start + LINE_LENGTH) });
  }

  return (
    <div className="overflow-x-auto rounded-md border border-border bg-muted/20 p-3">
      <div className="min-w-max space-y-2 font-mono text-sm leading-7">
        {rows.map((row) => (
          <div key={row.start} className="flex items-start gap-3">
            <span className="w-10 shrink-0 select-none text-right text-xs text-muted-foreground">{row.start + 1}</span>
            <div className="tracking-wide">
              {Array.from(row.text).map((aa, offset) => {
                const index = row.start + offset;
                const state = residueStates[index];
                return (
                  <span
                    key={index}
                    title={state?.label}
                    className={
                      state?.ambiguous
                        ? "rounded-sm bg-amber-300/50 text-foreground"
                        : state
                          ? "rounded-sm bg-primary/25 text-foreground"
                          : "text-muted-foreground"
                    }
                  >
                    {aa}
                  </span>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted-foreground">
        <Legend color="bg-primary/25" label="mapped peptide" />
        <Legend color="bg-amber-300/50" label="ambiguous peptide" />
      </div>
    </div>
  );
}

function buildResidueStates(
  length: number,
  segments: BuProteinDetailOut["coverage_segments"],
): Array<{ ambiguous: boolean; label: string } | null> {
  const states: Array<{ ambiguous: boolean; label: string } | null> = Array.from({ length }, () => null);
  for (const segment of segments) {
    if (segment.start === null || segment.end === null) continue;
    const start = Math.max(0, segment.start);
    const end = Math.min(length, segment.end);
    for (let index = start; index < end; index += 1) {
      const previous = states[index];
      states[index] = {
        ambiguous: Boolean(previous?.ambiguous || segment.is_ambiguous),
        label: previous?.label
          ? `${previous.label}; ${segment.sequence}`
          : `${segment.sequence} [${segment.start}, ${segment.end})`,
      };
    }
  }
  return states;
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

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-3 w-5 rounded-sm ${color}`} />
      {label}
    </span>
  );
}
