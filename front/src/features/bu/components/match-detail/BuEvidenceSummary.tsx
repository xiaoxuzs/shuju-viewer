import { useMemo } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { BuMatchDetailOut, BuSpectrumV1, BuXicOut } from "@/features/bu/types";
import type { BuXicPointSelection } from "@/features/bu/components/spectrum/BuXicChart";
import {
  buildBuEvidenceSummary,
  type EvidenceDataState,
  type EvidenceSection,
} from "@/features/bu/components/match-detail/evidenceSummaryModel";
import {
  useBuPfmbEvidence,
  type BuPfmbEvidence,
} from "@/features/bu/components/match-detail/useBuPfmbEvidence";
import type { InspectedRtSource } from "@/features/bu/utils";

interface Props {
  slug: string;
  matchId: number;
  match: BuMatchDetailOut;
  hasPfmb: boolean;
  inspectedRt: { rt: number; source: InspectedRtSource } | null;
  selectedXicPoint: BuXicPointSelection | null;
  xic: EvidenceDataState<BuXicOut>;
  ms2: EvidenceDataState<BuSpectrumV1>;
  pfmbEvidence?: BuPfmbEvidence;
}

export function BuEvidenceSummary(props: Props) {
  if (props.pfmbEvidence) {
    return <BuEvidenceSummaryInner {...props} pfmbEvidence={props.pfmbEvidence} />;
  }
  return <BuEvidenceSummaryWithHook {...props} />;
}

function BuEvidenceSummaryWithHook(props: Props) {
  const pfmbEvidence = useBuPfmbEvidence({
    slug: props.slug,
    matchId: props.matchId,
    hasPfmb: props.hasPfmb,
    pfmbSelectedRt: props.inspectedRt?.rt ?? null,
  });
  return <BuEvidenceSummaryInner {...props} pfmbEvidence={pfmbEvidence} />;
}

function BuEvidenceSummaryInner({
  slug,
  matchId,
  match,
  hasPfmb,
  inspectedRt,
  selectedXicPoint,
  xic,
  ms2,
  pfmbEvidence: pfmb,
}: Props & { pfmbEvidence: BuPfmbEvidence }) {
  const sections = useMemo(
    () =>
      buildBuEvidenceSummary({
        match,
        xic,
        ms2,
        hasPfmb,
        pfmbSlots: {
          data: pfmb.slots.data,
          isLoading: pfmb.slots.isLoading,
          isError: pfmb.slots.isError,
        },
        pfmbAnnotation: {
          data: pfmb.annotation.data,
          isLoading: pfmb.annotation.isLoading,
          isError: pfmb.annotation.isError,
        },
        activePfmbSlot: pfmb.activeSlot,
        inspectedRt,
        selectedXicPoint,
      }),
    [
      hasPfmb,
      inspectedRt,
      match,
      ms2.data,
      ms2.isError,
      ms2.isLoading,
      pfmb.activeSlot,
      pfmb.annotation.data,
      pfmb.annotation.isError,
      pfmb.annotation.isLoading,
      pfmb.slots.data,
      pfmb.slots.isError,
      pfmb.slots.isLoading,
      selectedXicPoint,
      slug,
      matchId,
      xic.data,
      xic.isError,
      xic.isLoading,
    ],
  );

  return <BuEvidenceSummaryView sections={sections} />;
}

export function BuEvidenceSummaryView({ sections }: { sections: EvidenceSection[] }) {
  return (
    <Card data-testid="bu-evidence-summary">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Evidence Summary</CardTitle>
        <p className="text-xs text-muted-foreground">
          Source-specific evidence summary; these metrics are not a combined identification score.
        </p>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {sections.map((section) => (
          <section
            key={section.key}
            className="min-w-0 rounded-md border border-border/70 bg-muted/20 p-3"
            data-testid={`evidence-${section.key}`}
          >
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              {section.title}
            </h3>
            {section.empty ? (
              <p className="mt-2 text-sm text-muted-foreground">{section.empty}</p>
            ) : (
              <dl className="mt-2 space-y-2">
                {section.rows.map((row) => (
                  <div key={row.label}>
                    <dt className="text-[11px] text-muted-foreground">{row.label}</dt>
                    <dd className="break-words text-sm font-medium">{row.value}</dd>
                    {row.detail && <div className="min-h-4 text-[11px] text-muted-foreground">{row.detail}</div>}
                  </div>
                ))}
              </dl>
            )}
          </section>
        ))}
      </CardContent>
    </Card>
  );
}
