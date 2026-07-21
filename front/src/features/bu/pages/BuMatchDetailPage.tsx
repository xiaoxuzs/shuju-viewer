import { useEffect, useMemo, useRef, useState } from "react";
import { useOutletContext, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";

import { DataEmptyState, DataLoadError } from "@/components/common/data-state";
import { ChartRenderBoundary } from "@/components/common/chart-render-boundary";
import { PageLoading } from "@/components/common/page-loading";
import { PlotStatus } from "@/components/common/plot-status";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  fetchBuMatch,
  fetchBuMatchMobilitySlice,
  fetchBuMatchMs1,
  fetchBuMatchMs2,
  fetchBuMatchXic,
} from "@/features/bu/api/buClient";
import { BuFragmentTable } from "@/features/bu/components/match-detail/BuFragmentTable";
import { BuEvidenceSummary } from "@/features/bu/components/match-detail/BuEvidenceSummary";
import { EvidenceJumpControls } from "@/features/bu/components/match-detail/EvidenceJumpControls";
import { EvidenceUpdateNotice } from "@/features/bu/components/match-detail/EvidenceUpdateNotice";
import { BuPfmbAnnotationCard } from "@/features/bu/components/match-detail/BuPfmbAnnotationCard";
import { BuProductIonXicCard } from "@/features/bu/components/match-detail/BuProductIonXicCard";
import {
  SelectedEvidenceBar,
  type SelectedEvidenceSourceMode,
} from "@/features/bu/components/match-detail/SelectedEvidenceBar";
import { useBuPfmbEvidence } from "@/features/bu/components/match-detail/useBuPfmbEvidence";
import {
  addTopProductIons,
  clearProductIonSelections,
  MAX_PRODUCT_ION_XICS,
  removeProductIonSelection,
  toggleProductIonSelection,
  toProductIonSelection,
  type ProductIonSelection,
} from "@/features/bu/components/match-detail/productIonSelection";
import type { ProductIonYAxisMode } from "@/features/bu/components/match-detail/productIonXicViewModel";
import { BuChartModal } from "@/features/bu/components/spectrum/BuChartModal";
import { MzMobilityScatter } from "@/features/bu/components/spectrum/MzMobilityScatter";
import { BuSpectrumChart } from "@/features/bu/components/spectrum/BuSpectrumChart";
import { buildPfmbSpectrumOverlay } from "@/features/bu/components/spectrum/pfmbSpectrumOverlay";
import type { SpectrumExternalAnnotation } from "@/features/bu/components/spectrum/spectrumAnnotation";
import { BuXicChart, type BuXicPointSelection } from "@/features/bu/components/spectrum/BuXicChart";
import { BU_CHART, DEFAULT_ZOOM, isZoomed, type Zoom } from "@/features/bu/components/spectrum/chartTheme";
import type { BuDatasetContext } from "@/features/bu/layout/BuDatasetLayout";
import type { BuMs2SlotItem, BuSpectrumV1, BuXicOut } from "@/features/bu/types";
import {
  RT_LINK_TOLERANCE_MIN,
  SCAN_UNAVAILABLE_REASON,
  formatDecimal,
  formatScanValue,
  inspectedRtSourceLabel,
  type InspectedRtSource,
} from "@/features/bu/utils";
import { formatModifiedSequenceForDisplay } from "@/features/bu/utils/modifiedSequenceFormatting";
import { chartQueryRetry, parseApiError } from "@/lib/apiError";
import {
  usePageTransitionReady,
  useTransitionSignal,
} from "@/features/page-transition";

const MS2_PPM = 20;
const XIC_PPM = 10;
const EMPTY_MS2_EXTERNAL_ANNOTATIONS: SpectrumExternalAnnotation[] = [];
const PRODUCT_ION_LIMIT_WARNING =
  "Maximum 8 product ions can be compared at once. Remove one before adding another.";
const ZOOM_HINT = "wheel to zoom (Shift = Y) · brush-drag = X";
type EvidenceSource = "xic" | "pfmb" | "manual" | "default";

type EvidenceRtSelection = {
  rt: number;
  source: EvidenceSource;
  slotIndex?: number | null;
};

type EvidenceNotice = {
  message: string;
  pendingFollow?: { rt: number; slotIndex: number };
};

export function BuMatchDetailPage() {
  const { dataset } = useOutletContext<BuDatasetContext>();
  const { matchId = "" } = useParams();
  const parsedMatchId = Number(matchId);
  const [xicFullOpen, setXicFullOpen] = useState(false);
  const [ms1FullOpen, setMs1FullOpen] = useState(false);
  const [ms2FullOpen, setMs2FullOpen] = useState(false);
  const [xicModalZoom, setXicModalZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const [ms1ModalZoom, setMs1ModalZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const [ms2ModalZoom, setMs2ModalZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const [selectedXicPoint, setSelectedXicPoint] = useState<BuXicPointSelection | null>(null);
  const [selectedProductIons, setSelectedProductIons] = useState<ProductIonSelection[]>([]);
  const [productIonYAxisMode, setProductIonYAxisMode] = useState<ProductIonYAxisMode>("normalized");
  const [productIonWarning, setProductIonWarning] = useState<string | null>(null);
  const [followPfmbSlot, setFollowPfmbSlot] = useState(true);
  const [pfmbSelection, setPfmbSelection] = useState<EvidenceRtSelection | null>(null);
  const [ms2Selection, setMs2Selection] = useState<EvidenceRtSelection | null>(null);
  const [evidenceNotice, setEvidenceNotice] = useState<EvidenceNotice | null>(null);
  const liveMs2SectionRef = useRef<HTMLDivElement | null>(null);
  const pfmbHeatmapSectionRef = useRef<HTMLDivElement | null>(null);
  const selectedMs2Rt = ms2Selection?.rt ?? null;
  const selectedPfmbRt = pfmbSelection?.rt ?? null;
  const inspectedRt = toInspectedRt(ms2Selection);
  const pfmbInspectedRt = toInspectedRt(pfmbSelection);
  const { data, isLoading, error } = useQuery({
    queryKey: ["bu", dataset.slug, "matches", parsedMatchId],
    queryFn: () => fetchBuMatch(dataset.slug, parsedMatchId),
    enabled: Number.isFinite(parsedMatchId),
  });
  const isMzml = data?.run.raw_format === "mzml";
  const isBruker = data?.run.raw_format === "bruker_d";
  const hasPfmb = Boolean(dataset.capabilities?.has_ms2_pfmb);
  const xic = useQuery({
    queryKey: ["bu", dataset.slug, "matches", parsedMatchId, "xic", XIC_PPM],
    queryFn: () => fetchBuMatchXic(dataset.slug, parsedMatchId, XIC_PPM),
    enabled: !!isMzml && Number.isFinite(parsedMatchId),
    retry: chartQueryRetry,
  });
  const ms2 = useQuery({
    queryKey: ["bu", dataset.slug, "matches", parsedMatchId, "ms2", MS2_PPM, selectedMs2Rt ?? "default"],
    queryFn: () =>
      fetchBuMatchMs2(
        dataset.slug,
        parsedMatchId,
        MS2_PPM,
        selectedMs2Rt !== null ? { rt: selectedMs2Rt } : {},
    ),
    enabled: !!isMzml && Number.isFinite(parsedMatchId),
    retry: chartQueryRetry,
    placeholderData: (previousData) => previousData,
  });
  const ms1 = useQuery({
    queryKey: ["bu", dataset.slug, "matches", parsedMatchId, "ms1"],
    queryFn: () => fetchBuMatchMs1(dataset.slug, parsedMatchId),
    enabled: !!isMzml && Number.isFinite(parsedMatchId),
    retry: chartQueryRetry,
  });
  const mobility = useQuery({
    queryKey: ["bu", dataset.slug, "matches", parsedMatchId, "mobility-slice"],
    queryFn: () => fetchBuMatchMobilitySlice(dataset.slug, parsedMatchId),
    enabled: !!isBruker && Number.isFinite(parsedMatchId),
    retry: chartQueryRetry,
  });
  const pfmbEvidence = useBuPfmbEvidence({
    slug: dataset.slug,
    matchId: parsedMatchId,
    hasPfmb,
    pfmbSelectedRt: selectedPfmbRt,
  });
  const pfmbOverlay = useMemo(
    () =>
      ms2.data && pfmbEvidence.annotation.data
        ? buildPfmbSpectrumOverlay({
            ions: pfmbEvidence.annotation.data.matched_ions,
            rawMz: ms2.data.mz,
            rawIntensity: ms2.data.intensity,
            ppmTolerance: MS2_PPM,
          })
        : null,
    [ms2.data, pfmbEvidence.annotation.data],
  );
  const ms2ExternalAnnotations = pfmbOverlay?.mappedAnnotations ?? EMPTY_MS2_EXTERNAL_ANNOTATIONS;
  const ms2AnnotationMode = ms2ExternalAnnotations.length > 0 ? "both" : "live";
  const [xicRendered, markXicRendered] = useTransitionSignal(`${dataset.slug}:${parsedMatchId}:xic`);
  const [ms1Rendered, markMs1Rendered] = useTransitionSignal(`${dataset.slug}:${parsedMatchId}:ms1`);
  const [ms2Rendered, markMs2Rendered] = useTransitionSignal(
    `${dataset.slug}:${parsedMatchId}:ms2:${ms2.data?.scan ?? "none"}`,
  );
  const pfmbCriticalReady = !hasPfmb || (
    !pfmbEvidence.slots.isLoading
    && (!pfmbEvidence.hasSlots || !pfmbEvidence.annotation.isLoading)
  );
  const mzmlCriticalReady = !xic.isLoading
    && !ms1.isLoading
    && !ms2.isLoading
    && !ms2.isPlaceholderData
    && xicRendered
    && ms1Rendered
    && ms2Rendered;
  const formatCriticalReady = !data
    || (isMzml ? mzmlCriticalReady : isBruker ? !mobility.isLoading : true);
  usePageTransitionReady(!isLoading && (!data || (formatCriticalReady && pfmbCriticalReady)));

  useEffect(() => {
    if (xic.isError || (!xic.isLoading && (!xic.data || !hasXicSignal(xic.data)))) markXicRendered();
  }, [markXicRendered, xic.data, xic.isError, xic.isLoading]);

  useEffect(() => {
    if (ms1.isError || (!ms1.isLoading && (!ms1.data || !hasSpectrumPeaks(ms1.data)))) markMs1Rendered();
  }, [markMs1Rendered, ms1.data, ms1.isError, ms1.isLoading]);

  useEffect(() => {
    if (
      !ms2.isPlaceholderData
      && (ms2.isError || (!ms2.isLoading && (!ms2.data || !hasSpectrumPeaks(ms2.data))))
    ) markMs2Rendered();
  }, [markMs2Rendered, ms2.data, ms2.isError, ms2.isLoading, ms2.isPlaceholderData]);

  useEffect(() => {
    setXicFullOpen(false);
    setMs1FullOpen(false);
    setMs2FullOpen(false);
    setXicModalZoom(DEFAULT_ZOOM);
    setMs1ModalZoom(DEFAULT_ZOOM);
    setMs2ModalZoom(DEFAULT_ZOOM);
    setSelectedXicPoint(null);
    setSelectedProductIons([]);
    setProductIonYAxisMode("normalized");
    setProductIonWarning(null);
    setFollowPfmbSlot(true);
    setPfmbSelection(null);
    setMs2Selection(null);
    setEvidenceNotice(null);
  }, [parsedMatchId]);

  useEffect(() => {
    setSelectedProductIons([]);
    setProductIonWarning(null);
  }, [
    data?.run.run_id,
    data?.precursor_mz,
    data?.precursor_charge,
    ms2.data?.scan,
    selectedMs2Rt,
  ]);

  const selectXicPoint = (selection: BuXicPointSelection) => {
    const next: EvidenceRtSelection = { rt: selection.rt, source: "xic" };
    setSelectedXicPoint(selection);
    setMs2Selection(next);
    setPfmbSelection(next);
    setSelectedProductIons([]);
    setProductIonWarning(null);
  };

  const selectPfmbSlot = (slot: BuMs2SlotItem) => {
    const next: EvidenceRtSelection = { rt: slot.rt_minutes, source: "pfmb", slotIndex: slot.slot_index };
    setPfmbSelection(next);
    if (followPfmbSlot) {
      setMs2Selection(next);
      setSelectedXicPoint(null);
      setSelectedProductIons([]);
      setProductIonWarning(null);
      setEvidenceNotice({
        message: `Fragment Match slot ${slot.slot_index} selected at RT ${slot.rt_minutes.toFixed(2)} min; updating MS2 scan.`,
        pendingFollow: { rt: slot.rt_minutes, slotIndex: slot.slot_index },
      });
      return;
    }
    setEvidenceNotice({
      message: `Fragment Match slot changed to ${slot.slot_index} at RT ${slot.rt_minutes.toFixed(2)} min; MS2 scan remains locked.`,
    });
  };

  // Fallback for legacy RT-only PFMB controls.
  const selectRtFromPfmb = (rt: number) => {
    const slot = pfmbEvidence.slotData?.slots.find((item) => Math.abs(item.rt_minutes - rt) < 1e-6);
    if (slot) {
      selectPfmbSlot(slot);
      return;
    }
    const next: EvidenceRtSelection = { rt, source: "pfmb", slotIndex: null };
    setPfmbSelection(next);
    if (followPfmbSlot) {
      setMs2Selection(next);
      setSelectedXicPoint(null);
      setSelectedProductIons([]);
      setProductIonWarning(null);
      setEvidenceNotice({
        message: `Fragment Match RT ${rt.toFixed(2)} min selected; updating MS2 scan.`,
      });
      return;
    }
    setEvidenceNotice({ message: `Fragment Match RT changed to ${rt.toFixed(2)} min; MS2 scan remains locked.` });
  };

  const changeFollowPfmbSlot = (next: boolean) => {
    setFollowPfmbSlot(next);
    if (next) {
      if (pfmbSelection) {
        setMs2Selection(pfmbSelection);
        setSelectedXicPoint(null);
        setSelectedProductIons([]);
        setProductIonWarning(null);
      }
      setEvidenceNotice({ message: "MS2 now follows Fragment Match slot selection." });
      return;
    }
    setEvidenceNotice({ message: "Fragment Match slot selection no longer updates the live MS2 scan." });
  };

  const lockMs2Scan = () => {
    setFollowPfmbSlot(false);
    setEvidenceNotice({ message: "MS2 scan is locked; Fragment Match slot changes will not update the live scan." });
  };

  const scrollToLiveMs2 = () => {
    liveMs2SectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const scrollToPfmbHeatmap = () => {
    pfmbHeatmapSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  useEffect(() => {
    if (!evidenceNotice?.pendingFollow || ms2.isFetching || !ms2.data) return;
    setEvidenceNotice({
      message: `MS2 updated to scan ${formatEvidenceScan(ms2.data.scan)} at RT ${formatEvidenceRt(
        ms2.data.rt_minutes,
      )} from Fragment Match slot ${evidenceNotice.pendingFollow.slotIndex}.`,
    });
  }, [
    evidenceNotice?.pendingFollow,
    ms2.data,
    ms2.isFetching,
  ]);

  const selectedProductIonIds = useMemo(
    () => new Set(selectedProductIons.map((ion) => ion.id)),
    [selectedProductIons],
  );

  const toggleProductIon = (matchedIon: Parameters<typeof toProductIonSelection>[0]) => {
    const selection = toProductIonSelection(matchedIon);
    const result = toggleProductIonSelection(selectedProductIons, selection);
    setSelectedProductIons(result.selections);
    setProductIonWarning(result.limitReached ? PRODUCT_ION_LIMIT_WARNING : null);
  };

  const removeProductIon = (ionId: string) => {
    setSelectedProductIons((current) => removeProductIonSelection(current, ionId));
    setProductIonWarning(null);
  };

  const addTopFragments = () => {
    const result = addTopProductIons(selectedProductIons, ms2.data?.matched_ions ?? []);
    setSelectedProductIons(result.selections);
    setProductIonWarning(result.limitReached ? PRODUCT_ION_LIMIT_WARNING : null);
  };

  const clearProductIons = () => {
    setSelectedProductIons(clearProductIonSelections());
    setProductIonWarning(null);
  };

  if (isLoading) return <PageLoading />;
  if (error && !data) return <DataLoadError />;
  if (!data) return <DataEmptyState />;

  const identificationRt = data.identification_rt_apex ?? data.rt_window.rt_apex;
  const activePfmbSlot = pfmbEvidence.activeSlot;
  const evidenceSourceMode = selectedEvidenceSourceMode(followPfmbSlot, ms2Selection);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle title={data.modified_sequence ?? data.sequence}>
            {formatModifiedSequenceForDisplay(data.modified_sequence ?? data.sequence)}
          </CardTitle>
        </CardHeader>
        <CardContent
          className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4"
          data-testid="match-metadata"
        >
          <Field label="Run" value={data.run.file_name} />
          <Field label="Charge" value={data.precursor_charge ? `${data.precursor_charge}+` : "-"} />
          <Field label="m/z" value={formatDecimal(data.precursor_mz)} />
          <Field label="Q.Value" value={formatDecimal(data.q_value)} />
          <Field
            label="Identification RT apex"
            value={formatDecimal(data.identification_rt_apex ?? data.rt_window.rt_apex)}
          />
          <Field
            label="Scan"
            value={formatScanValue(data.scan_number)}
            hint={
              formatScanValue(data.scan_number) === "N/A"
                ? data.scan_unavailable_reason ?? SCAN_UNAVAILABLE_REASON
                : undefined
            }
          />
          <Field label="Proteins" value={data.proteins.map((p) => p.accession).join(", ") || "-"} />
          <Field label="Spectrum" value={isMzml ? "mzML precursor XIC + MS1/MS2" : "match-level spectra unsupported"} />
        </CardContent>
      </Card>

      <BuEvidenceSummary
        slug={dataset.slug}
        matchId={parsedMatchId}
        match={data}
        hasPfmb={hasPfmb}
        inspectedRt={inspectedRt}
        selectedXicPoint={selectedXicPoint}
        xic={{ data: xic.data, isLoading: xic.isLoading, isError: xic.isError }}
        ms2={{ data: ms2.data, isLoading: ms2.isLoading, isError: ms2.isError }}
        pfmbEvidence={pfmbEvidence}
      />

      {isMzml ? (
        <>
          {xic.isLoading ? (
            <PlotStatus kind="loading" title="Loading precursor XIC..." />
          ) : xic.error ? (
            <MatchPlotErrorState error={xic.error} plot="xic" />
          ) : xic.data && !hasXicSignal(xic.data) ? (
            <PlotStatus kind="no_signal" title="No precursor signal in the selected range." />
          ) : xic.data ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Precursor XIC</CardTitle>
                <p className="text-xs text-muted-foreground">
                  MS1 extracted ion chromatogram for the precursor; used as chromatographic context for the MS2 spectrum.
                </p>
                <p className="text-xs text-muted-foreground">
                  Click a point on the XIC to inspect the corresponding MS2 scan. {ZOOM_HINT}
                </p>
                <div className="min-h-4">
                  {inspectedRt !== null && (
                    <p className="text-xs font-medium text-foreground" data-testid="xic-selected-rt">
                      Current inspected RT: {inspectedRt.rt.toFixed(4)} min from{" "}
                      {inspectedRtSourceLabel(inspectedRt.source)}
                      {selectedXicPoint
                        ? `, ${selectedXicPoint.traceLabel} intensity ${formatDecimal(selectedXicPoint.intensity, 0)}`
                        : ""}
                    </p>
                  )}
                </div>
              </CardHeader>
              <CardContent>
                <ChartRenderBoundary
                  key={`${dataset.slug}:${parsedMatchId}:xic`}
                  fallback={<PlotStatus kind="error" title="Failed to draw the precursor XIC." />}
                  onError={markXicRendered}
                >
                  <BuXicChart
                    xic={xic.data}
                    sequence={data.sequence}
                    precursorCharge={data.precursor_charge}
                    ppm={XIC_PPM}
                    onPointClick={selectXicPoint}
                    onOpenFull={() => setXicFullOpen(true)}
                    onFirstRender={markXicRendered}
                  />
                </ChartRenderBoundary>
              </CardContent>
            </Card>
          ) : null}
          {ms1.isLoading ? (
            <PlotStatus kind="loading" title="Loading MS1 spectrum..." className="min-h-64" />
          ) : ms1.error ? (
            <MatchPlotErrorState error={ms1.error} plot="spectrum" />
          ) : ms1.data && !hasSpectrumPeaks(ms1.data) ? (
            <PlotStatus kind="empty" title="No MS1 spectrum peaks are available." className="min-h-64" />
          ) : ms1.data ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">MS1 spectrum from mzML</CardTitle>
                <p className="text-xs text-muted-foreground">
                  MS1 scan #{ms1.data.scan}. MS1 scan RT: {ms1.data.rt_minutes.toFixed(4)} min. {ZOOM_HINT}
                </p>
              </CardHeader>
              <CardContent>
                <ChartRenderBoundary
                  key={`${dataset.slug}:${parsedMatchId}:ms1`}
                  fallback={<PlotStatus kind="error" title="Failed to draw the MS1 spectrum." />}
                  onError={markMs1Rendered}
                >
                  <BuSpectrumChart
                    spectrum={ms1.data}
                    sequence={data.sequence}
                    precursorCharge={data.precursor_charge}
                    precursorMz={data.precursor_mz}
                    onOpenFull={() => setMs1FullOpen(true)}
                    onFirstRender={markMs1Rendered}
                  />
                </ChartRenderBoundary>
              </CardContent>
            </Card>
          ) : null}
          {ms2.isLoading ? (
            <PlotStatus kind="loading" title="Loading MS2 spectrum..." className="min-h-64" />
          ) : ms2.error ? (
            <MatchPlotErrorState error={ms2.error} plot="spectrum" />
          ) : ms2.data && !hasSpectrumPeaks(ms2.data) ? (
            <PlotStatus kind="empty" title="No MS2 spectrum peaks are available." className="min-h-64" />
          ) : ms2.data ? (
            <Card className="[overflow-anchor:none]" data-testid="live-ms2-evidence-section">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Live mzML MS2 Evidence</CardTitle>
                <p className="text-xs text-muted-foreground">
                  Raw mzML MS2 peaks and live b/y fragment matches from the selected scan.
                </p>
              </CardHeader>
              <CardContent className="space-y-6">
                <SelectedEvidenceBar
                  identificationRt={identificationRt}
                  selectedMs2Rt={ms2.data?.rt_minutes ?? selectedMs2Rt}
                  liveScan={ms2.data?.scan}
                  pfmbSlotIndex={activePfmbSlot?.slot_index ?? pfmbSelection?.slotIndex ?? null}
                  pfmbSlotRt={activePfmbSlot?.rt_minutes ?? selectedPfmbRt}
                  isPfmbApex={Boolean(
                    activePfmbSlot
                    && pfmbEvidence.slotData
                    && activePfmbSlot.slot_index === pfmbEvidence.slotData.apex_slot,
                  )}
                  sourceMode={evidenceSourceMode}
                  matchedIonCount={ms2.data?.matched_ions.length ?? null}
                />
                <EvidenceUpdateNotice message={evidenceNotice?.message} />
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <EvidenceJumpControls
                    onJumpToMs2={scrollToLiveMs2}
                    onJumpToPfmb={scrollToPfmbHeatmap}
                  />
                </div>

                <section
                  ref={liveMs2SectionRef}
                  className="scroll-mt-20"
                  data-testid="live-ms2-spectrum-section"
                >
                  <div data-testid="ms2-spectrum-section">
                  <div className="mb-2">
                    <h3 className="text-sm font-semibold">MS2 spectrum</h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Matched fragments are calculated from the selected mzML MS2 scan. Click a live-primary b/y fragment peak to add or remove its product ion XIC.
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground" data-testid="ms2-current-rt">
                      MS2 scan {formatEvidenceScan(ms2.data.scan)}. MS2 scan RT: {ms2.data.rt_minutes.toFixed(4)} min. {ZOOM_HINT}
                    </p>
                    {selectedMs2Rt !== null &&
                      Math.abs(ms2.data.rt_minutes - selectedMs2Rt) > RT_LINK_TOLERANCE_MIN && (
                        <p className="mt-1 text-xs font-medium text-warning" data-testid="ms2-rt-out-of-tolerance">
                          Nearest MS2 scan is {Math.abs(ms2.data.rt_minutes - selectedMs2Rt).toFixed(2)} min from the
                          current inspected RT.
                        </p>
                      )}
                    {(ms2.data.annotation_warnings ?? []).map((warning) => (
                      <p
                        key={warning}
                        className="mt-1 text-xs font-medium text-warning"
                        data-testid="ms2-annotation-warning"
                      >
                        {warning}
                      </p>
                    ))}
                    {pfmbOverlay && pfmbOverlay.unmappedCount > 0 && (
                      <p className="mt-1 text-xs font-medium text-warning" data-testid="ms2-pfmb-unmapped">
                        Some Fragment Match annotations could not be mapped to raw mzML peaks within the current tolerance and are not drawn.
                      </p>
                      )}
                  </div>
                  <ChartRenderBoundary
                    key={`${dataset.slug}:${parsedMatchId}:ms2:${ms2.data.scan}`}
                    fallback={<PlotStatus kind="error" title="Failed to draw the MS2 spectrum." />}
                    onError={markMs2Rendered}
                  >
                    <BuSpectrumChart
                      spectrum={ms2.data}
                      sequence={data.sequence}
                      precursorCharge={data.precursor_charge}
                      precursorMz={data.precursor_mz}
                      ppm={MS2_PPM}
                      onMatchedIonClick={toggleProductIon}
                      selectedProductIonIds={selectedProductIonIds}
                      externalAnnotations={ms2ExternalAnnotations}
                      annotationMode={ms2AnnotationMode}
                      onOpenFull={() => setMs2FullOpen(true)}
                      onFirstRender={markMs2Rendered}
                    />
                  </ChartRenderBoundary>
                  </div>
                </section>

                <section className="border-t border-border/70 pt-5" data-testid="product-ion-evidence-section">
                  <h3 className="text-sm font-semibold">Product ion evidence</h3>
                  <div
                    className="mt-3 grid gap-3 xl:grid-cols-[minmax(520px,1.25fr)_minmax(420px,1fr)]"
                    data-testid="product-ion-evidence-layout"
                  >
                    <BuFragmentTable
                      ions={ms2.data.matched_ions}
                      selectedProductIonIds={selectedProductIonIds}
                      selectionLimitReached={selectedProductIons.length >= MAX_PRODUCT_ION_XICS}
                      onToggleProductIon={toggleProductIon}
                    />
                    <div className="min-w-0" data-testid="product-ion-xic-panel">
                      <BuProductIonXicCard
                        datasetId={dataset.id}
                        slug={dataset.slug}
                        matchId={parsedMatchId}
                        runId={data.run.run_id}
                        ms2Scan={ms2.data.scan}
                        available
                        matchedIons={ms2.data.matched_ions}
                        selections={selectedProductIons}
                        mode={productIonYAxisMode}
                        ppm={MS2_PPM}
                        rtWindow={{ start: data.rt_window.rt_start, stop: data.rt_window.rt_stop }}
                        identificationRt={data.identification_rt_apex ?? data.rt_window.rt_apex}
                        inspectedRt={selectedMs2Rt}
                        ms2ScanRt={ms2.data.rt_minutes}
                        warning={productIonWarning}
                        onRemove={removeProductIon}
                        onAddTop={addTopFragments}
                        onClear={clearProductIons}
                        onModeChange={setProductIonYAxisMode}
                      />
                    </div>
                  </div>
                </section>
              </CardContent>
            </Card>
          ) : null}
          {hasPfmb && (
            <Card className="[overflow-anchor:none]" data-testid="fragment-match-evidence-section">
              <CardHeader className="pb-1">
                <CardTitle className="text-base">Fragment Match Evidence</CardTitle>
              </CardHeader>
              <CardContent>
                <BuPfmbAnnotationCard
                  slug={dataset.slug}
                  matchId={parsedMatchId}
                  hasPfmb={hasPfmb}
                  selectedRt={selectedPfmbRt}
                  selectedRtSource={pfmbInspectedRt?.source ?? null}
                  onSelectRt={selectRtFromPfmb}
                  onSelectSlot={selectPfmbSlot}
                  followPfmbSlot={followPfmbSlot}
                  onFollowPfmbSlotChange={changeFollowPfmbSlot}
                  onLockMs2Scan={lockMs2Scan}
                  heatmapSectionRef={pfmbHeatmapSectionRef}
                  pfmbEvidence={pfmbEvidence}
                  embedded
                />
              </CardContent>
            </Card>
          )}
        </>
      ) : (
        <>
          <Card>
            <CardContent className="p-6 text-sm text-muted-foreground">
              {isBruker
                ? "Bruker .d match-level Precursor XIC and MS1/MS2 spectra are not supported."
                : "This raw format does not support match-level Precursor XIC or MS1/MS2 spectra."}
              <BuProductIonXicCard
                datasetId={dataset.id}
                slug={dataset.slug}
                matchId={parsedMatchId}
                runId={data.run.run_id}
                ms2Scan={null}
                available={false}
                matchedIons={[]}
                selections={[]}
                mode={productIonYAxisMode}
                ppm={MS2_PPM}
                rtWindow={{ start: data.rt_window.rt_start, stop: data.rt_window.rt_stop }}
                identificationRt={data.identification_rt_apex ?? data.rt_window.rt_apex}
                inspectedRt={selectedMs2Rt}
                ms2ScanRt={null}
                onRemove={() => {}}
                onAddTop={() => {}}
                onClear={() => {}}
                onModeChange={setProductIonYAxisMode}
              />
            </CardContent>
          </Card>
          {isBruker && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">m/z × 1/K0 slice</CardTitle>
                <p className="text-xs text-muted-foreground">
                  Bruker .d MS1 frame nearest to the Identification RT apex
                </p>
              </CardHeader>
              <CardContent>
                {mobility.isLoading && <Skeleton className="h-72" />}
                {Boolean(mobility.error) && <DataLoadError compact />}
                {mobility.data && <MzMobilityScatter slice={mobility.data} />}
              </CardContent>
            </Card>
          )}
        </>
      )}

      {!isMzml && (
        <BuPfmbAnnotationCard
          slug={dataset.slug}
          matchId={parsedMatchId}
          hasPfmb={hasPfmb}
          selectedRt={selectedPfmbRt}
          selectedRtSource={pfmbInspectedRt?.source ?? null}
          onSelectRt={selectRtFromPfmb}
          onSelectSlot={selectPfmbSlot}
          pfmbEvidence={pfmbEvidence}
        />
      )}

      {xicFullOpen && xic.data && (
        <BuChartModal
          title="Precursor XIC"
          subtitle={`${data.sequence} · ${ZOOM_HINT}`}
          onClose={() => setXicFullOpen(false)}
          actions={<ResetZoomButton zoom={xicModalZoom} onReset={() => setXicModalZoom(DEFAULT_ZOOM)} />}
        >
          <BuXicChart
            xic={xic.data}
            sequence={data.sequence}
            precursorCharge={data.precursor_charge}
            ppm={XIC_PPM}
            height={Math.max(BU_CHART.xicHeight, 560)}
            zoom={xicModalZoom}
            onZoomChange={setXicModalZoom}
            onPointClick={selectXicPoint}
          />
        </BuChartModal>
      )}

      {ms1FullOpen && ms1.data && (
        <BuChartModal
          title="MS1 spectrum from mzML"
          subtitle={`${data.sequence} · ${ZOOM_HINT}`}
          onClose={() => setMs1FullOpen(false)}
          actions={<ResetZoomButton zoom={ms1ModalZoom} onReset={() => setMs1ModalZoom(DEFAULT_ZOOM)} />}
        >
          <BuSpectrumChart
            spectrum={ms1.data}
            sequence={data.sequence}
            precursorCharge={data.precursor_charge}
            precursorMz={data.precursor_mz}
            height={Math.max(BU_CHART.ms2Height, 620)}
            zoom={ms1ModalZoom}
            onZoomChange={setMs1ModalZoom}
          />
        </BuChartModal>
      )}

      {ms2FullOpen && ms2.data && (
        <BuChartModal
          title="Live mzML MS2 matching"
          subtitle={`${data.sequence} · ${ZOOM_HINT}`}
          onClose={() => setMs2FullOpen(false)}
          actions={<ResetZoomButton zoom={ms2ModalZoom} onReset={() => setMs2ModalZoom(DEFAULT_ZOOM)} />}
        >
          <BuSpectrumChart
            spectrum={ms2.data}
            sequence={data.sequence}
            precursorCharge={data.precursor_charge}
            precursorMz={data.precursor_mz}
            ppm={MS2_PPM}
            height={Math.max(BU_CHART.ms2Height, 620)}
            zoom={ms2ModalZoom}
            onZoomChange={setMs2ModalZoom}
            onMatchedIonClick={toggleProductIon}
            selectedProductIonIds={selectedProductIonIds}
            externalAnnotations={ms2ExternalAnnotations}
            annotationMode={ms2AnnotationMode}
          />
        </BuChartModal>
      )}
    </div>
  );
}

function toInspectedRt(selection: EvidenceRtSelection | null): { rt: number; source: InspectedRtSource } | null {
  if (!selection) return null;
  if (selection.source === "pfmb") return { rt: selection.rt, source: "pfmb" };
  if (selection.source === "xic") return { rt: selection.rt, source: "xic" };
  return null;
}

function selectedEvidenceSourceMode(
  followPfmbSlot: boolean,
  ms2Selection: EvidenceRtSelection | null,
): SelectedEvidenceSourceMode {
  if (ms2Selection?.source === "xic") return "live-ms2";
  if (!followPfmbSlot) return "locked-ms2-scan";
  if (ms2Selection?.source === "pfmb") return "follow-pfmb-slot";
  return "unknown";
}

function formatEvidenceRt(value: number | null | undefined): string {
  return Number.isFinite(value) ? `${value!.toFixed(4)} min` : "N/A";
}

function formatEvidenceScan(value: number | null | undefined): string {
  return Number.isFinite(value) && value! > 0 ? `#${value}` : "N/A";
}

function hasXicSignal(xic: BuXicOut): boolean {
  if (xic.rt.length === 0) return false;
  const traces = xic.traces.length > 0 ? xic.traces.map((trace) => trace.intensity) : [xic.intensity];
  return traces.some((intensities) => intensities.some((value) => Number.isFinite(value) && value > 0));
}

function hasSpectrumPeaks(spectrum: BuSpectrumV1): boolean {
  return spectrum.mz.length > 0 && spectrum.intensity.length > 0;
}

function MatchPlotErrorState({ error, plot }: { error: unknown; plot: "xic" | "spectrum" }) {
  const parsed = parseApiError(error);
  if (parsed.kind === "scan_index_missing") {
    return (
      <PlotStatus
        kind="derived_missing"
        title="Derived scan index is not ready."
        command={parsed.backfillCommand}
      />
    );
  }
  if (parsed.kind === "scan_index_stale") {
    return (
      <PlotStatus
        kind="derived_stale"
        title="Derived scan index is stale."
        command={parsed.backfillCommand}
      />
    );
  }
  if (parsed.kind === "unsupported_raw_format") {
    return <PlotStatus kind="unsupported" />;
  }
  if (parsed.kind === "indexed_mzml_unsupported") {
    return (
      <PlotStatus
        kind="unsupported"
        title="This mzML file does not support indexed spectrum access."
      />
    );
  }
  if (parsed.kind === "not_found") {
    return (
      <PlotStatus
        kind="not_found"
        title={plot === "spectrum" ? "The requested spectrum could not be found." : undefined}
      />
    );
  }
  if (parsed.kind === "no_signal") {
    return <PlotStatus kind="no_signal" />;
  }
  return (
    <PlotStatus
      kind="error"
      title={plot === "spectrum" ? "Something went wrong while loading this spectrum." : undefined}
    />
  );
}

function Field({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-border/60 bg-muted/30 p-3">
      <div className="text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1 break-words font-medium">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

function ResetZoomButton({ zoom, onReset }: { zoom: Zoom; onReset: () => void }) {
  return (
    <button
      type="button"
      onClick={onReset}
      disabled={!isZoomed(zoom)}
      className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-xs text-muted-foreground transition-colors enabled:hover:text-foreground disabled:opacity-40"
    >
      <RotateCcw className="h-3.5 w-3.5" />
      reset
    </button>
  );
}
