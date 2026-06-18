import { useEffect, useMemo, useState } from "react";
import { useOutletContext, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";

import { DataEmptyState, DataLoadError } from "@/components/common/data-state";
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
import { BuPfmbAnnotationCard } from "@/features/bu/components/match-detail/BuPfmbAnnotationCard";
import { BuProductIonXicCard } from "@/features/bu/components/match-detail/BuProductIonXicCard";
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
import type { BuSpectrumV1, BuXicOut } from "@/features/bu/types";
import {
  RT_LINK_TOLERANCE_MIN,
  SCAN_UNAVAILABLE_REASON,
  formatDecimal,
  formatScanValue,
  inspectedRtSourceLabel,
  type InspectedRtSource,
} from "@/features/bu/utils";
import { chartQueryRetry, parseApiError } from "@/lib/apiError";

const MS2_PPM = 20;
const XIC_PPM = 10;
const EMPTY_MS2_EXTERNAL_ANNOTATIONS: SpectrumExternalAnnotation[] = [];
const PRODUCT_ION_LIMIT_WARNING =
  "Maximum 8 product ions can be compared at once. Remove one before adding another.";
const ZOOM_HINT = "wheel to zoom (Shift = Y) · brush-drag = X";

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
  // Single source of truth linking the XIC, live MS2 and PFMB cards.
  const [inspectedRt, setInspectedRt] = useState<{ rt: number; source: InspectedRtSource } | null>(null);
  const selectedRt = inspectedRt?.rt ?? null;
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
    queryKey: ["bu", dataset.slug, "matches", parsedMatchId, "ms2", MS2_PPM, selectedRt ?? "default"],
    queryFn: () =>
      fetchBuMatchMs2(
        dataset.slug,
        parsedMatchId,
        MS2_PPM,
        selectedRt !== null ? { rt: selectedRt } : {},
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
    selectedRt,
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
    setInspectedRt(null);
  }, [parsedMatchId]);

  useEffect(() => {
    setSelectedProductIons([]);
    setProductIonWarning(null);
  }, [
    data?.run.run_id,
    data?.precursor_mz,
    data?.precursor_charge,
    ms2.data?.scan,
    selectedRt,
  ]);

  const selectXicPoint = (selection: BuXicPointSelection) => {
    setSelectedXicPoint(selection);
    setInspectedRt({ rt: selection.rt, source: "xic" });
    setSelectedProductIons([]);
    setProductIonWarning(null);
  };

  // Driven by a PFMB slot click: RT becomes canonical, the XIC marker is cleared.
  const selectRtFromPfmb = (rt: number) => {
    setInspectedRt({ rt, source: "pfmb" });
    setSelectedXicPoint(null);
    setSelectedProductIons([]);
    setProductIonWarning(null);
  };

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

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>{data.modified_sequence ?? data.sequence}</CardTitle>
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
                <BuXicChart
                  xic={xic.data}
                  sequence={data.sequence}
                  precursorCharge={data.precursor_charge}
                  ppm={XIC_PPM}
                  onPointClick={selectXicPoint}
                  onOpenFull={() => setXicFullOpen(true)}
                />
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
                <BuSpectrumChart
                  spectrum={ms1.data}
                  sequence={data.sequence}
                  precursorCharge={data.precursor_charge}
                  precursorMz={data.precursor_mz}
                  onOpenFull={() => setMs1FullOpen(true)}
                />
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
            <Card className="[overflow-anchor:none]" data-testid="ms2-pfmb-evidence">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">MS2 / PFMB Evidence</CardTitle>
                <p className="text-xs text-muted-foreground">
                  Raw mzML MS2 peaks are shown once. PFMB annotations are used as primary labels when available, with live mzML matches used as fallback evidence.
                </p>
              </CardHeader>
              <CardContent className="space-y-6">
                <section data-testid="ms2-spectrum-section">
                  <div className="mb-2">
                    <h3 className="text-sm font-semibold">MS2 spectrum</h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Matched fragments are calculated from the selected mzML MS2 scan. Click a live-primary b/y fragment peak to add or remove its product ion XIC.
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground" data-testid="ms2-current-rt">
                      MS2 scan #{ms2.data.scan}. MS2 scan RT: {ms2.data.rt_minutes.toFixed(4)} min. {ZOOM_HINT}
                    </p>
                    {selectedRt !== null &&
                      Math.abs(ms2.data.rt_minutes - selectedRt) > RT_LINK_TOLERANCE_MIN && (
                        <p className="mt-1 text-xs font-medium text-amber-600" data-testid="ms2-rt-out-of-tolerance">
                          Nearest MS2 scan is {Math.abs(ms2.data.rt_minutes - selectedRt).toFixed(2)} min from the
                          current inspected RT.
                        </p>
                      )}
                    {pfmbOverlay && pfmbOverlay.unmappedCount > 0 && (
                      <p className="mt-1 text-xs font-medium text-amber-600" data-testid="ms2-pfmb-unmapped">
                        Some PFMB annotations could not be mapped to raw mzML peaks within the current tolerance and are not drawn.
                      </p>
                    )}
                  </div>
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
                  />
                </section>

                <section className="border-t border-border/70 pt-5" data-testid="product-ion-evidence-section">
                  <h3 className="text-sm font-semibold">Product ion evidence</h3>
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
                    inspectedRt={selectedRt}
                    ms2ScanRt={ms2.data.rt_minutes}
                    warning={productIonWarning}
                    onRemove={removeProductIon}
                    onAddTop={addTopFragments}
                    onClear={clearProductIons}
                    onModeChange={setProductIonYAxisMode}
                  />
                  <BuFragmentTable
                    ions={ms2.data.matched_ions}
                    selectedProductIonIds={selectedProductIonIds}
                    selectionLimitReached={selectedProductIons.length >= MAX_PRODUCT_ION_XICS}
                    onToggleProductIon={toggleProductIon}
                  />
                </section>

                <BuPfmbAnnotationCard
                  slug={dataset.slug}
                  matchId={parsedMatchId}
                  hasPfmb={hasPfmb}
                  selectedRt={selectedRt}
                  selectedRtSource={inspectedRt?.source ?? null}
                  onSelectRt={selectRtFromPfmb}
                  pfmbEvidence={pfmbEvidence}
                  embedded
                />
              </CardContent>
            </Card>
          ) : null}
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
                inspectedRt={selectedRt}
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
          selectedRt={selectedRt}
          selectedRtSource={inspectedRt?.source ?? null}
          onSelectRt={selectRtFromPfmb}
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
