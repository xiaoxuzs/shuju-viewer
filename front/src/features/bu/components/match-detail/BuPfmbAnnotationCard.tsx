import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { DataLoadError } from "@/components/common/data-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  fetchBuMatchMs2Annotation,
  fetchBuMatchMs2AnnotationMatrix,
  fetchBuMatchMs2Slots,
} from "@/features/bu/api/buClient";
import { BuPfmbFragmentTable } from "@/features/bu/components/match-detail/BuPfmbFragmentTable";
import { BuPfmbHeatmap } from "@/features/bu/components/match-detail/BuPfmbHeatmap";
import { BuPfmbQualitySummary } from "@/features/bu/components/match-detail/BuPfmbQualitySummary";
import { BuSequenceCoverage } from "@/features/bu/components/match-detail/BuSequenceCoverage";
import { BuPfmbSpectrumChart, type PfmbMassMode } from "@/features/bu/components/spectrum/BuPfmbSpectrumChart";
import { BuChartModal } from "@/features/bu/components/spectrum/BuChartModal";
import type { BuMs2AnnotationOut, BuMs2SlotItem } from "@/features/bu/types";
import { RT_LINK_TOLERANCE_MIN, formatCount } from "@/features/bu/utils";

interface Props {
  slug: string;
  matchId: number;
  hasPfmb: boolean;
  selectedRt: number | null;
  onSelectRt: (rt: number) => void;
}

export function BuPfmbAnnotationCard({ slug, matchId, hasPfmb, selectedRt, onSelectRt }: Props) {
  const slots = useQuery({
    queryKey: ["bu", slug, "matches", matchId, "ms2-slots"],
    queryFn: () => fetchBuMatchMs2Slots(slug, matchId),
    enabled: hasPfmb && Number.isFinite(matchId),
  });

  const slotData = slots.data;
  const hasSlots = Boolean(slotData?.has_pfmb && slotData.slots.length > 0);

  // Active slot is derived from the shared selectedRt:
  //  - no RT selected -> apex slot (default)
  //  - RT selected and a slot is within tolerance -> that nearest slot
  //  - RT selected but nearest slot is too far -> keep apex, surface a hint
  const { activeSlot, nearestDistance } = useMemo(() => {
    if (!hasSlots) return { activeSlot: null as BuMs2SlotItem | null, nearestDistance: null as number | null };
    const list = slotData!.slots;
    const apexSlot = list.find((s) => s.slot_index === slotData!.apex_slot) ?? list[0];
    if (selectedRt == null) return { activeSlot: apexSlot, nearestDistance: null as number | null };
    let nearest = list[0];
    let best = Infinity;
    for (const slot of list) {
      const distance = Math.abs(slot.rt_minutes - selectedRt);
      if (distance < best) {
        best = distance;
        nearest = slot;
      }
    }
    if (best > RT_LINK_TOLERANCE_MIN) return { activeSlot: apexSlot, nearestDistance: best };
    return { activeSlot: nearest, nearestDistance: best };
  }, [hasSlots, slotData, selectedRt]);

  const outOfTolerance =
    selectedRt != null && nearestDistance != null && nearestDistance > RT_LINK_TOLERANCE_MIN;
  const activePrsm = activeSlot?.prsm_index ?? null;

  const annotation = useQuery({
    queryKey: ["bu", slug, "matches", matchId, "ms2-annotation", activePrsm],
    queryFn: () => fetchBuMatchMs2Annotation(slug, matchId, activePrsm!),
    enabled: hasPfmb && activePrsm !== null,
  });

  // Single request for the whole RT x fragment matrix (no per-slot N+1).
  const matrix = useQuery({
    queryKey: ["bu", slug, "matches", matchId, "ms2-annotation-matrix"],
    queryFn: () => fetchBuMatchMs2AnnotationMatrix(slug, matchId),
    enabled: hasPfmb && hasSlots,
  });

  // Cross-component highlight, keyed by charge-merged fragment family (e.g. "b5").
  const [highlight, setHighlight] = useState<ReadonlySet<string>>(new Set());
  const [massMode, setMassMode] = useState<PfmbMassMode>("neutral");
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    setHighlight(new Set());
    setMassMode("neutral");
    setFullscreen(false);
  }, [slug, matchId]);

  const toggleFamily = useCallback((key: string) => {
    setHighlight((prev) => (prev.size === 1 && prev.has(key) ? new Set() : new Set([key])));
  }, []);
  const setFamilies = useCallback((keys: string[]) => {
    setHighlight(new Set(keys));
  }, []);

  if (!hasPfmb) return null;

  return (
    <Card data-testid="pfmb-card">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Pre-computed PFMB annotation</CardTitle>
        <p className="text-xs text-muted-foreground">
          Pre-computed, deconvoluted peak-to-fragment matches (b / y / c / z.) for each
          retention-time slot of this precursor. These are not the same peaks as the live
          mzML MS2 matching shown above, so peak totals are not directly comparable.
        </p>

        {selectedRt != null && (
          <p className="pt-1 text-xs font-medium text-foreground" data-testid="pfmb-selected-rt">
            Selected RT: {selectedRt.toFixed(4)} min
          </p>
        )}
        {outOfTolerance && (
          <p className="text-xs font-medium text-amber-600" data-testid="pfmb-rt-out-of-tolerance">
            Nearest PFMB slot is {nearestDistance!.toFixed(2)} min from the selected RT (over
            {" "}{RT_LINK_TOLERANCE_MIN.toFixed(1)} min); showing the apex slot instead.
          </p>
        )}

        {slots.isLoading && <Skeleton className="mt-2 h-7 w-72" data-testid="pfmb-slots-loading" />}
        {slots.error && (
          <div className="pt-2" data-testid="pfmb-slots-error">
            <DataLoadError compact />
          </div>
        )}
        {!slots.isLoading && !slots.error && !hasSlots && (
          <p className="pt-2 text-xs text-muted-foreground" data-testid="pfmb-no-slots">
            PFMB is enabled for this dataset, but no retention-time slot is available for this match.
          </p>
        )}
        {hasSlots && (
          <div className="flex flex-wrap gap-1.5 pt-2" data-testid="pfmb-slot-buttons">
            {slotData!.slots.map((slot) => (
              <SlotButton
                key={slot.prsm_index}
                slot={slot}
                isApex={slot.slot_index === slotData!.apex_slot}
                isSelected={slot.prsm_index === activePrsm}
                onSelect={() => onSelectRt(slot.rt_minutes)}
              />
            ))}
          </div>
        )}
      </CardHeader>

      {hasSlots && (
        <CardContent>
          {/* Quality summary (active slot + per-slot trend); leads with the
              "match rate != accuracy" disclaimer. */}
          {annotation.data && (
            <BuPfmbQualitySummary
              annotation={annotation.data}
              matrix={matrix.data}
              selectedRt={activeSlot?.rt_minutes ?? null}
              onSelectRt={onSelectRt}
            />
          )}

          {/* RT x fragment heatmap (one request, all slots) */}
          {matrix.isLoading && <Skeleton className="mb-4 h-40" data-testid="pfmb-matrix-loading" />}
          {matrix.error && (
            <div className="mb-4" data-testid="pfmb-matrix-error">
              <DataLoadError compact />
            </div>
          )}
          {matrix.data && (
            <BuPfmbHeatmap
              matrix={matrix.data}
              selectedRt={activeSlot?.rt_minutes ?? null}
              highlight={highlight}
              onSelectRt={onSelectRt}
              onHighlight={toggleFamily}
            />
          )}

          {annotation.isLoading && (
            <Skeleton className="h-56" data-testid="pfmb-annotation-loading" />
          )}
          {annotation.error && (
            <div data-testid="pfmb-annotation-error">
              <DataLoadError compact />
            </div>
          )}
          {annotation.data && (
            <>
              <BuSequenceCoverage
                peptide={annotation.data.peptide}
                ions={annotation.data.matched_ions}
                highlight={highlight}
                onHighlight={setFamilies}
              />
              <div className="mb-1 flex items-center justify-between">
                <div className="text-xs uppercase tracking-wider text-muted-foreground">
                  PFMB annotation spectrum
                </div>
                <MassModeToggle massMode={massMode} onChange={setMassMode} />
              </div>
              <BuPfmbSpectrumChart
                ions={annotation.data.matched_ions}
                massMode={massMode}
                highlight={highlight}
                onHighlight={setFamilies}
                onOpenFull={() => setFullscreen(true)}
                className="mb-3"
              />
              <SlotSummary slot={activeSlot} annotation={annotation.data} />
              <BuPfmbFragmentTable
                ions={annotation.data.matched_ions}
                highlight={highlight}
                onHighlight={toggleFamily}
              />
            </>
          )}
        </CardContent>
      )}

      {fullscreen && annotation.data && (
        <BuChartModal
          title={`PFMB annotation spectrum: ${annotation.data.peptide}`}
          subtitle={`${activeSlot ? `Slot ${activeSlot.slot_index} (RT ${activeSlot.rt_minutes.toFixed(2)} min) | ` : ""}${massMode === "mz" ? "m/z" : "neutral mass"}`}
          onClose={() => setFullscreen(false)}
          actions={<MassModeToggle massMode={massMode} onChange={setMassMode} />}
        >
          <BuPfmbSpectrumChart
            ions={annotation.data.matched_ions}
            massMode={massMode}
            highlight={highlight}
            onHighlight={setFamilies}
            height={640}
            className="h-full"
          />
        </BuChartModal>
      )}
    </Card>
  );
}

function MassModeToggle({
  massMode,
  onChange,
}: {
  massMode: PfmbMassMode;
  onChange: (mode: PfmbMassMode) => void;
}) {
  return (
    <div className="inline-flex overflow-hidden rounded-md border border-border text-[11px]" data-testid="pfmb-mass-mode">
      {(["neutral", "mz"] as PfmbMassMode[]).map((mode) => (
        <button
          key={mode}
          type="button"
          onClick={() => onChange(mode)}
          aria-pressed={massMode === mode}
          className={cn(
            "px-2 py-0.5 transition-colors",
            massMode === mode ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {mode === "mz" ? "m/z" : "neutral mass"}
        </button>
      ))}
    </div>
  );
}

function SlotSummary({
  slot,
  annotation,
}: {
  slot: BuMs2SlotItem | null;
  annotation: BuMs2AnnotationOut;
}) {
  const zeroRows = annotation.matched_ions.filter((ion) => ion.intensity === 0).length;
  return (
    <dl
      className="mb-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground"
      data-testid="pfmb-slot-summary"
    >
      {slot && <SummaryItem label="Slot" value={String(slot.slot_index)} />}
      {slot && <SummaryItem label="RT" value={`${slot.rt_minutes.toFixed(2)} min`} />}
      <SummaryItem label="PRSM index" value={String(annotation.prsm_index)} />
      <SummaryItem label="Matched peaks (by peak_id)" value={formatCount(annotation.matched_peak_count)} />
      <SummaryItem label="Matched ion rows" value={formatCount(annotation.matched_ions.length)} />
      <SummaryItem label="Zero-intensity rows" value={formatCount(zeroRows)} />
    </dl>
  );
}

function SummaryItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt>{label}</dt>
      <dd className="font-mono font-medium text-foreground">{value}</dd>
    </div>
  );
}

function SlotButton({
  slot,
  isApex,
  isSelected,
  onSelect,
}: {
  slot: BuMs2SlotItem;
  isApex: boolean;
  isSelected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={isSelected}
      data-testid="pfmb-slot-button"
      className={cn(
        "rounded-md border px-2 py-1 text-xs font-medium transition-colors",
        isSelected
          ? "border-primary bg-primary/10 text-primary"
          : "border-border text-muted-foreground hover:text-foreground",
      )}
    >
      {`Slot ${slot.slot_index} | ${slot.rt_minutes.toFixed(2)} min${isApex ? " | Apex" : ""}`}
    </button>
  );
}
