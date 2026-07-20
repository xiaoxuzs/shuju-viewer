import { useCallback, useEffect, useState, type RefObject } from "react";
import { DataLoadError } from "@/components/common/data-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { FollowPfmbSlotControls } from "@/features/bu/components/match-detail/FollowPfmbSlotControls";
import { BuPfmbFragmentTable } from "@/features/bu/components/match-detail/BuPfmbFragmentTable";
import { BuPfmbHeatmap } from "@/features/bu/components/match-detail/BuPfmbHeatmap";
import { BuPfmbQualitySummary } from "@/features/bu/components/match-detail/BuPfmbQualitySummary";
import { BuSequenceCoverage } from "@/features/bu/components/match-detail/BuSequenceCoverage";
import {
  useBuPfmbEvidence,
  type BuPfmbEvidence,
} from "@/features/bu/components/match-detail/useBuPfmbEvidence";
import type { BuMs2AnnotationOut, BuMs2SlotItem } from "@/features/bu/types";
import {
  RT_LINK_TOLERANCE_MIN,
  formatCount,
  inspectedRtSourceLabel,
  type InspectedRtSource,
} from "@/features/bu/utils";

interface Props {
  slug: string;
  matchId: number;
  hasPfmb: boolean;
  selectedRt: number | null;
  selectedRtSource: InspectedRtSource | null;
  onSelectRt: (rt: number) => void;
  onSelectSlot?: (slot: BuMs2SlotItem) => void;
  followPfmbSlot?: boolean;
  onFollowPfmbSlotChange?: (next: boolean) => void;
  onLockMs2Scan?: () => void;
  heatmapSectionRef?: RefObject<HTMLDivElement>;
  pfmbEvidence?: BuPfmbEvidence;
  embedded?: boolean;
}

export function BuPfmbAnnotationCard(props: Props) {
  if (props.pfmbEvidence) {
    return <BuPfmbAnnotationCardInner {...props} pfmbEvidence={props.pfmbEvidence} />;
  }
  return <BuPfmbAnnotationCardWithHook {...props} />;
}

function BuPfmbAnnotationCardWithHook(props: Props) {
  const pfmbEvidence = useBuPfmbEvidence({
    slug: props.slug,
    matchId: props.matchId,
    hasPfmb: props.hasPfmb,
    pfmbSelectedRt: props.selectedRt,
  });
  return <BuPfmbAnnotationCardInner {...props} pfmbEvidence={pfmbEvidence} />;
}

function BuPfmbAnnotationCardInner({
  slug,
  matchId,
  hasPfmb,
  selectedRt,
  selectedRtSource,
  onSelectRt,
  onSelectSlot,
  followPfmbSlot = true,
  onFollowPfmbSlotChange,
  onLockMs2Scan,
  heatmapSectionRef,
  pfmbEvidence,
  embedded = false,
}: Props & { pfmbEvidence: BuPfmbEvidence }) {
  const {
    slots,
    slotData,
    hasSlots,
    activeSlot,
    activePrsm,
    nearestDistance,
    outOfTolerance,
    annotation,
    matrix,
  } = pfmbEvidence;

  // Cross-component highlight, keyed by charge-merged fragment family (e.g. "b5").
  const [highlight, setHighlight] = useState<ReadonlySet<string>>(new Set());

  useEffect(() => {
    setHighlight(new Set());
  }, [slug, matchId]);

  const toggleFamily = useCallback((key: string) => {
    setHighlight((prev) => (prev.size === 1 && prev.has(key) ? new Set() : new Set([key])));
  }, []);
  const setFamilies = useCallback((keys: string[]) => {
    setHighlight(new Set(keys));
  }, []);

  const selectSlot = useCallback(
    (slot: BuMs2SlotItem) => {
      if (onSelectSlot) {
        onSelectSlot(slot);
        return;
      }
      onSelectRt(slot.rt_minutes);
    },
    [onSelectRt, onSelectSlot],
  );
  const selectRt = useCallback(
    (rt: number) => {
      const slot = slotData?.slots.find((item) => Math.abs(item.rt_minutes - rt) < 1e-6);
      if (slot) {
        selectSlot(slot);
        return;
      }
      onSelectRt(rt);
    },
    [onSelectRt, selectSlot, slotData?.slots],
  );

  if (!hasPfmb) return null;

  const header = (
    <PfmbHeader
      showTitle={embedded}
      selectedRt={selectedRt}
      selectedRtSource={selectedRtSource}
      nearestDistance={nearestDistance}
      outOfTolerance={outOfTolerance}
      annotation={annotation.data}
      matrix={matrix.data}
      selectedSlotRt={activeSlot?.rt_minutes ?? null}
      onSelectRt={selectRt}
    />
  );
  const slotPanel = (
    <PfmbSlotPanel
      slots={slots}
      slotData={slotData}
      hasSlots={hasSlots}
      activePrsm={activePrsm}
      activeSlot={activeSlot}
      annotation={annotation.data}
      followPfmbSlot={followPfmbSlot}
      onFollowPfmbSlotChange={onFollowPfmbSlotChange}
      onLockMs2Scan={onLockMs2Scan}
      onSelectSlot={selectSlot}
      isUpdating={annotation.isFetching && !annotation.isLoading}
    />
  );
  const content = (
    <>
      {header}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(260px,0.8fr)]" data-testid="pfmb-body-grid">
        <div ref={heatmapSectionRef} className="min-w-0 scroll-mt-20" data-testid="pfmb-heatmap-section">
          <div data-testid="pfmb-heatmap-column">
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
                onSelectRt={selectRt}
                onSelectSlot={selectSlot}
                onHighlight={toggleFamily}
              />
            )}
          </div>
        </div>
        {slotPanel}
      </div>
      {annotation.isLoading && !annotation.data && (
        <Skeleton className="h-56" data-testid="pfmb-annotation-loading" />
      )}
      {annotation.error && (
        <div data-testid="pfmb-annotation-error">
          <DataLoadError compact />
        </div>
      )}
      {annotation.data && (
        <BuSequenceCoverage
          peptide={annotation.data.peptide}
          ions={annotation.data.matched_ions}
          highlight={highlight}
          onHighlight={setFamilies}
        />
      )}
      {annotation.data && (
        <BuPfmbFragmentTable
          ions={annotation.data.matched_ions}
          highlight={highlight}
          onHighlight={toggleFamily}
        />
      )}
    </>
  );

  if (embedded) {
    return (
      <section data-testid="pfmb-card">
        <div data-testid="fragment-match-slot-detail">
          {content}
        </div>
      </section>
    );
  }

  return (
    <Card data-testid="pfmb-card">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Fragment Match Slot Detail</CardTitle>
      </CardHeader>
      <CardContent>
        <div data-testid="fragment-match-slot-detail">
          {content}
        </div>
      </CardContent>
    </Card>
  );
}

function PfmbHeader({
  showTitle,
  selectedRt,
  selectedRtSource,
  nearestDistance,
  outOfTolerance,
  annotation,
  matrix,
  selectedSlotRt,
  onSelectRt,
}: {
  showTitle: boolean;
  selectedRt: number | null;
  selectedRtSource: InspectedRtSource | null;
  nearestDistance: number | null;
  outOfTolerance: boolean;
  annotation?: BuMs2AnnotationOut;
  matrix?: Parameters<typeof BuPfmbQualitySummary>[0]["matrix"];
  selectedSlotRt: number | null;
  onSelectRt: (rt: number) => void;
}) {
  return (
    <div className="mb-3 space-y-3" data-testid="pfmb-header">
      <div
        className="flex flex-wrap items-center gap-2 text-xs"
        data-testid="fragment-match-evidence-header"
      >
        {showTitle && (
          <span className="font-medium text-muted-foreground">Selected slot detail</span>
        )}
        <span
          className="rounded-md border border-border bg-background px-2 py-1 font-medium text-foreground"
          data-testid="pfmb-selected-rt"
        >
          Slot RT: {formatSlotRt(selectedSlotRt)}
        </span>
        <span
          className="rounded-md border border-border/70 bg-muted/30 px-2 py-1 text-muted-foreground"
          data-testid="fragment-match-slot-meta"
        >
          Pre-computed slot-level matches
        </span>
        <span className="rounded-md border border-border/70 bg-muted/30 px-2 py-1 text-muted-foreground">
          not live mzML MS2 peaks
        </span>
      </div>

      <details className="text-xs text-muted-foreground" data-testid="fragment-match-source-details">
        <summary className="cursor-pointer font-medium text-muted-foreground hover:text-foreground">
          Details
        </summary>
        <div className="mt-2 rounded-md border border-border/70 bg-muted/20 px-3 py-2" data-testid="pfmb-source-note">
          <div className="font-semibold uppercase tracking-wider">Annotation source</div>
          <p className="mt-1">
            Pre-computed, deconvoluted peak-to-fragment matches for the selected retention-time slot.
            These peaks are not the same as live mzML MS2 matched peaks.
          </p>
          {selectedRt != null && selectedRtSource != null && (
            <p className="mt-1">
              Inspected RT: {selectedRt.toFixed(4)} min from {inspectedRtSourceLabel(selectedRtSource)}.
            </p>
          )}
        </div>
      </details>

      <div className="min-h-4">
        {outOfTolerance && (
          <p className="text-xs font-medium text-warning" data-testid="pfmb-rt-out-of-tolerance">
            Nearest Fragment Match slot is {nearestDistance!.toFixed(2)} min from the current inspected RT (over
            {" "}{RT_LINK_TOLERANCE_MIN.toFixed(1)} min); showing the Fragment Match apex slot instead.
          </p>
        )}
      </div>
      {annotation && (
        <BuPfmbQualitySummary
          annotation={annotation}
          matrix={matrix}
          selectedRt={selectedSlotRt}
          onSelectRt={onSelectRt}
        />
      )}
    </div>
  );
}

function formatSlotRt(value: number | null | undefined): string {
  return Number.isFinite(value) ? `${value!.toFixed(4)} min` : "N/A";
}

function PfmbSlotPanel({
  slots,
  slotData,
  hasSlots,
  activePrsm,
  activeSlot,
  annotation,
  followPfmbSlot,
  onFollowPfmbSlotChange,
  onLockMs2Scan,
  onSelectSlot,
  isUpdating,
}: {
  slots: BuPfmbEvidence["slots"];
  slotData: BuPfmbEvidence["slotData"];
  hasSlots: boolean;
  activePrsm: number | null;
  activeSlot: BuMs2SlotItem | null;
  annotation?: BuMs2AnnotationOut;
  followPfmbSlot: boolean;
  onFollowPfmbSlotChange?: (next: boolean) => void;
  onLockMs2Scan?: () => void;
  onSelectSlot: (slot: BuMs2SlotItem) => void;
  isUpdating: boolean;
}) {
  return (
    <aside
      className="min-w-0 space-y-3 rounded-lg border border-border/70 bg-muted/10 p-3 lg:min-h-[220px]"
      data-testid="pfmb-slot-panel"
    >
      <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Fragment Match slot selection
      </div>
      {onFollowPfmbSlotChange && onLockMs2Scan && (
        <FollowPfmbSlotControls
          followPfmbSlot={followPfmbSlot}
          onFollowChange={onFollowPfmbSlotChange}
          onLockMs2Scan={onLockMs2Scan}
        />
      )}
      {slots.isLoading && <Skeleton className="h-7 w-full" data-testid="pfmb-slots-loading" />}
      {slots.error && (
        <div data-testid="pfmb-slots-error">
          <DataLoadError compact />
        </div>
      )}
      {!slots.isLoading && !slots.error && !hasSlots && (
        <p className="text-xs text-muted-foreground" data-testid="pfmb-no-slots">
          Fragment Match evidence is enabled for this dataset, but no retention-time slot is available for this match.
        </p>
      )}
      {hasSlots && slotData && (
        <div>
          <div className="max-h-56 space-y-1.5 overflow-y-auto pr-1" data-testid="pfmb-slot-buttons">
            {slotData.slots.map((slot) => (
              <SlotButton
                key={slot.prsm_index}
                slot={slot}
                isApex={slot.slot_index === slotData.apex_slot}
                isSelected={slot.prsm_index === activePrsm}
                onSelect={() => onSelectSlot(slot)}
              />
            ))}
          </div>
        </div>
      )}
      <SlotSummary slot={activeSlot} annotation={annotation} compact />
      <p className="min-h-4 text-[11px] text-muted-foreground" data-testid="pfmb-slot-updating">
        {isUpdating ? "Updating selected slot..." : ""}
      </p>
    </aside>
  );
}

function SlotSummary({
  slot,
  annotation,
  compact = false,
}: {
  slot: BuMs2SlotItem | null;
  annotation?: BuMs2AnnotationOut;
  compact?: boolean;
}) {
  const zeroRows = annotation?.matched_ions.filter((ion) => ion.intensity === 0).length;
  return (
    <dl
      className={cn(
        "text-xs text-muted-foreground",
        compact
          ? "space-y-1 rounded-md border border-border/70 bg-background/70 p-3"
          : "mb-3 flex flex-wrap gap-x-5 gap-y-1",
      )}
      data-testid="pfmb-slot-summary"
    >
      <SummaryItem label="Slot" value={slot ? String(slot.slot_index) : "N/A"} />
      <SummaryItem label="Fragment Match slot RT" value={slot ? `${slot.rt_minutes.toFixed(2)} min` : "N/A"} />
      <SummaryItem label="PRSM index" value={annotation ? String(annotation.prsm_index) : "N/A"} />
      <SummaryItem
        label="Fragment Match matched peak rows"
        value={annotation ? formatCount(annotation.matched_peak_count) : "N/A"}
      />
      <SummaryItem
        label="Pre-computed matched rows"
        value={annotation ? formatCount(annotation.matched_ions.length) : "N/A"}
      />
      <SummaryItem
        label="Fragment Match zero-intensity rows"
        value={zeroRows == null ? "N/A" : formatCount(zeroRows)}
      />
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
        "min-h-8 w-full rounded-md border px-2 py-1 text-left text-xs font-medium leading-tight transition-colors",
        isSelected
          ? "border-primary bg-primary/10 text-primary"
          : "border-border text-muted-foreground hover:text-foreground",
      )}
    >
      {`Slot ${slot.slot_index} | Fragment Match slot RT ${slot.rt_minutes.toFixed(2)} min${isApex ? " | Fragment Match apex" : ""}`}
    </button>
  );
}
