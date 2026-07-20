import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { PlotStatus } from "@/components/common/plot-status";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DetectedPeaksTable } from "@/features/spectra-only/components/DetectedPeaksTable";
import { fetchSpectraSpectrum } from "@/features/spectra-only/api/spectraClient";
import { SpectrumModal } from "@/features/prsm/SpectrumModal";
import {
  DEFAULT_ZOOM,
  SpectrumChart,
  type ChartPeak,
  type Zoom,
} from "@/features/prsm/SpectrumChart";
import {
  findNearestPeakByMz,
  formatMassError,
} from "@/features/spectra-only/utils/scanRelations";
import {
  DEFAULT_PEAK_LABEL_MODE,
  PEAK_LABEL_OPTIONS,
  buildPeakAnnotations,
  findNearestPeakByMz as findNearestAnnotatedPeakByMz,
  formatPeakIntensity,
  formatPeakMz,
  getBasePeak,
  getRelativeIntensity,
  normalizePeaks,
  type NormalizedPeak,
  type PeakAnnotation,
  type PeakAnnotationResult,
  type PeakLabelMode,
} from "@/features/spectra-only/utils/peakAnnotations";
import { chartQueryRetry, parseApiError } from "@/lib/apiError";
import { formatNumber } from "@/lib/utils";
import { CHART_COLORS } from "@/features/theme/chartColors";
import { ChartRenderBoundary } from "@/components/common/chart-render-boundary";

const DEFAULT_PRECURSOR_MATCH_TOLERANCE_DA = 0.05;
const RAW_PEAK_LABEL_COLOR = CHART_COLORS.series[7];
const RAW_SELECTED_PEAK_COLOR = CHART_COLORS.series[3];
const SPECTRA_ONLY_MS2_Y_HEADROOM_RATIO = 0.12;

interface SpectrumHighlight {
  targetMz: number | null | undefined;
  label?: string;
  toleranceDa?: number;
}

export function SpectrumPanel({
  datasetId,
  runId,
  scanNumber,
  titlePrefix,
  highlight,
  enablePeakAnnotations = false,
  onReady,
}: {
  datasetId: number;
  runId: number | null;
  scanNumber: number | null;
  titlePrefix?: string;
  highlight?: SpectrumHighlight | null;
  enablePeakAnnotations?: boolean;
  onReady?: () => void;
}) {
  const [zoom, setZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const [showLargeSpectrum, setShowLargeSpectrum] = useState(false);
  const [peakLabelMode, setPeakLabelMode] = useState<PeakLabelMode>(DEFAULT_PEAK_LABEL_MODE);
  const [selectedPeakKey, setSelectedPeakKey] = useState<string | null>(null);
  const spectrum = useQuery({
    queryKey: ["spectra-only", datasetId, runId, "spectrum", scanNumber],
    queryFn: () => fetchSpectraSpectrum(datasetId, runId!, scanNumber!),
    enabled: runId != null && scanNumber != null,
    retry: chartQueryRetry,
  });
  const normalizedPeaks = useMemo<NormalizedPeak[]>(() => {
    if (!spectrum.data) return [];
    return normalizePeaks(spectrum.data.mz.map((mz, index) => ({
      mz,
      intensity: spectrum.data?.intensity[index] ?? 0,
    })));
  }, [spectrum.data]);
  const chartBasePeak = useMemo(() => getBasePeak(normalizedPeaks), [normalizedPeaks]);
  const peaks = useMemo<ChartPeak[]>(
    () =>
      normalizedPeaks.map((peak) => ({
        mz: peak.mz,
        intensity: peak.intensity,
        peakKey: peak.key,
        relativeIntensity: enablePeakAnnotations
          ? getRelativeIntensity(peak, chartBasePeak?.intensity ?? 0)
          : null,
      })),
    [chartBasePeak, enablePeakAnnotations, normalizedPeaks],
  );
  const selectedPeak = useMemo(
    () => normalizedPeaks.find((peak) => peak.key === selectedPeakKey) ?? null,
    [normalizedPeaks, selectedPeakKey],
  );
  const showPeakAnnotations = Boolean(enablePeakAnnotations && spectrum.data?.ms_level === 2);
  const peakAnnotations = useMemo(
    () =>
      showPeakAnnotations
        ? buildPeakAnnotations(normalizedPeaks, peakLabelMode, selectedPeak)
        : null,
    [normalizedPeaks, peakLabelMode, selectedPeak, showPeakAnnotations],
  );
  const peakLabelOverlays = useMemo(
    () =>
      peakAnnotations?.labelAnnotations.map((annotation) => ({
        key: `label:${annotation.peak.key}`,
        mz: annotation.peak.mz,
        intensity: annotation.peak.intensity,
        color: RAW_PEAK_LABEL_COLOR,
        label: formatPeakMz(annotation.peak.mz),
      })) ?? [],
    [peakAnnotations],
  );
  const selectedPeakOverlay = peakAnnotations?.selectedAnnotation
    ? {
        key: `selected:${peakAnnotations.selectedAnnotation.peak.key}`,
        mz: peakAnnotations.selectedAnnotation.peak.mz,
        intensity: peakAnnotations.selectedAnnotation.peak.intensity,
        color: RAW_SELECTED_PEAK_COLOR,
      }
    : null;

  useEffect(() => {
    if (
      runId == null
      || scanNumber == null
      || spectrum.isError
      || (!spectrum.isLoading && (!spectrum.data || peaks.length === 0))
    ) onReady?.();
  }, [onReady, peaks.length, runId, scanNumber, spectrum.data, spectrum.isError, spectrum.isLoading]);
  const highlightTargetMz = highlight?.targetMz ?? null;
  const highlightToleranceDa = highlight?.toleranceDa ?? DEFAULT_PRECURSOR_MATCH_TOLERANCE_DA;
  const highlightLabel = highlight?.label ?? "precursor";
  const precursorPeakMatch = useMemo(
    () => (highlight ? findNearestPeakByMz(peaks, highlightTargetMz, highlightToleranceDa) : null),
    [highlight, highlightTargetMz, highlightToleranceDa, peaks],
  );
  const highlightMarker = isFiniteNumber(highlightTargetMz)
    ? { x: highlightTargetMz, label: highlightLabel }
    : null;
  const highlightPeak = precursorPeakMatch
    ? {
        mz: precursorPeakMatch.peak.mz,
        intensity: precursorPeakMatch.peak.intensity,
        color: "hsl(var(--primary))",
        label: highlightLabel,
      }
    : null;

  useEffect(() => {
    setZoom(DEFAULT_ZOOM);
    setShowLargeSpectrum(false);
    setSelectedPeakKey(null);
  }, [runId, scanNumber]);

  useEffect(() => {
    if (!showPeakAnnotations) setSelectedPeakKey(null);
  }, [showPeakAnnotations]);

  const handleChartPeakClick = useCallback(
    (peak: ChartPeak) => {
      if (!showPeakAnnotations) return;
      if (peak.peakKey) {
        setSelectedPeakKey(peak.peakKey);
        return;
      }
      const match = findNearestAnnotatedPeakByMz(normalizedPeaks, peak.mz, 0.000001);
      if (match) setSelectedPeakKey(match.key);
    },
    [normalizedPeaks, showPeakAnnotations],
  );

  const handleTablePeakSelect = useCallback((annotation: PeakAnnotation) => {
    setSelectedPeakKey(annotation.peak.key);
  }, []);

  if (spectrum.data) {
    const title = titlePrefix
      ? `${titlePrefix} - Scan ${spectrum.data.scan}`
      : `MS${spectrum.data.ms_level} Spectrum - Scan ${spectrum.data.scan}`;
    const subtitleParts = [
      `RT ${formatNumber(spectrum.data.rt_seconds / 60, 2)} min`,
      `${peaks.length.toLocaleString()} peaks`,
    ];
    if (spectrum.data.native_id) {
      subtitleParts.push(`Native ID ${spectrum.data.native_id}`);
    }
    const subtitle = subtitleParts.join(" | ");

    return (
      <>
        <div className="mb-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground md:grid-cols-4">
          <Metric label="Peaks" value={peaks.length.toLocaleString()} />
          <Metric label="Native ID" value={spectrum.data.native_id ?? "-"} />
          <Metric label="MS Level" value={`MS${spectrum.data.ms_level}`} />
          <Metric label="RT" value={`${formatNumber(spectrum.data.rt_seconds / 60, 2)} min`} />
        </div>
        <Card className="mb-6" data-testid="spectra-only-2d-spectrum-panel">
          <CardHeader className="space-y-3">
            <div className="flex flex-row items-baseline justify-between gap-3">
              <div>
                <CardTitle className="text-base">{title}</CardTitle>
                <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
              </div>
            </div>
            {showPeakAnnotations && (
              <PeakAnnotationToolbar
                mode={peakLabelMode}
                annotations={peakAnnotations}
                onModeChange={setPeakLabelMode}
              />
            )}
          </CardHeader>
          <CardContent className="space-y-3" data-testid="spectra-only-2d-spectrum-chart">
            {highlight && (
              <PrecursorHighlightStatus
                targetMz={highlightTargetMz}
                match={precursorPeakMatch}
                toleranceDa={highlightToleranceDa}
              />
            )}
            <ChartRenderBoundary
              key={`${runId}:${scanNumber}`}
              fallback={<PlotStatus kind="error" title="Failed to draw the spectrum." />}
              onError={onReady}
            >
              <SpectrumChart
                peaks={peaks}
                xLabel="m/z"
                yLabel="Intensity"
                yHeadroomRatio={showPeakAnnotations ? SPECTRA_ONLY_MS2_Y_HEADROOM_RATIO : undefined}
                height={420}
                marker={highlightMarker}
                highlightPeak={highlightPeak}
                peakLabels={showPeakAnnotations ? peakLabelOverlays : undefined}
                selectedPeak={showPeakAnnotations ? selectedPeakOverlay : null}
                onPeakClick={showPeakAnnotations ? handleChartPeakClick : undefined}
                zoom={zoom}
                onZoomChange={setZoom}
                onOpenFull={() => setShowLargeSpectrum(true)}
                onFirstRender={onReady}
                emptyHint={
                  showPeakAnnotations
                    ? "No peaks are available for this MS2 spectrum."
                    : "No peaks to display for this scan."
                }
              />
            </ChartRenderBoundary>
            {showPeakAnnotations && peakAnnotations && (
              <DetectedPeaksTable
                annotations={peakAnnotations.tableAnnotations}
                selectedPeakKey={peakAnnotations.selectedAnnotation?.peak.key ?? null}
                onSelectPeak={handleTablePeakSelect}
              />
            )}
          </CardContent>
        </Card>
        {showLargeSpectrum && (
          <SpectrumModal title={title} subtitle={subtitle} onClose={() => setShowLargeSpectrum(false)}>
            <SpectrumChart
              peaks={peaks}
              xLabel="m/z"
              yLabel="Intensity"
              yHeadroomRatio={showPeakAnnotations ? SPECTRA_ONLY_MS2_Y_HEADROOM_RATIO : undefined}
              height={720}
              marker={highlightMarker}
              highlightPeak={highlightPeak}
              peakLabels={showPeakAnnotations ? peakLabelOverlays : undefined}
              selectedPeak={showPeakAnnotations ? selectedPeakOverlay : null}
              onPeakClick={showPeakAnnotations ? handleChartPeakClick : undefined}
              zoom={zoom}
              onZoomChange={setZoom}
              emptyHint={
                showPeakAnnotations
                  ? "No peaks are available for this MS2 spectrum."
                  : "No peaks to display for this scan."
              }
            />
          </SpectrumModal>
        )}
      </>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Spectrum</CardTitle>
      </CardHeader>
      <CardContent>
        {runId == null ? (
          <PlotStatus kind="empty" title="No run selected." />
        ) : scanNumber == null ? (
          <PlotStatus kind="empty" title="Select a scan to view its spectrum." />
        ) : spectrum.isLoading ? (
          <PlotStatus kind="loading" title="Loading spectrum..." />
        ) : spectrum.error ? (
          <SpectrumErrorState error={spectrum.error} />
        ) : null}
      </CardContent>
    </Card>
  );
}

function PeakAnnotationToolbar({
  mode,
  annotations,
  onModeChange,
}: {
  mode: PeakLabelMode;
  annotations: PeakAnnotationResult | null;
  onModeChange: (mode: PeakLabelMode) => void;
}) {
  const basePeak = annotations?.basePeak ?? null;
  const selectedPeak = annotations?.selectedAnnotation?.peak ?? null;

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-border/60 bg-muted/20 p-2 text-xs">
      <span className="font-medium text-muted-foreground">Peak labels</span>
      <div className="inline-flex overflow-hidden rounded-md border border-border/70 bg-background">
        {PEAK_LABEL_OPTIONS.map((option) => (
          <Button
            key={option.value}
            type="button"
            variant={mode === option.value ? "secondary" : "ghost"}
            size="sm"
            className="h-7 rounded-none px-2 text-xs"
            onClick={() => onModeChange(option.value)}
          >
            {option.label}
          </Button>
        ))}
      </div>
      {basePeak && (
        <span className="text-muted-foreground">
          Base peak: mz {formatPeakMz(basePeak.mz)}, int {formatPeakIntensity(basePeak.intensity)}
        </span>
      )}
      {selectedPeak && (
        <span className="text-muted-foreground">
          Selected peak: mz {formatPeakMz(selectedPeak.mz)}, int {formatPeakIntensity(selectedPeak.intensity)}
        </span>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md border border-border/60 bg-muted/30 p-2">
      <div className="uppercase tracking-wider">{label}</div>
      <div className="mt-1 truncate font-medium text-foreground">{value}</div>
    </div>
  );
}

function PrecursorHighlightStatus({
  targetMz,
  match,
  toleranceDa,
}: {
  targetMz: number | null;
  match: ReturnType<typeof findNearestPeakByMz>;
  toleranceDa: number;
}) {
  if (!isFiniteNumber(targetMz)) {
    return (
      <div className="rounded-md border border-border/60 bg-muted/30 p-2 text-xs text-muted-foreground">
        No precursor m/z is available for this MS2 scan.
      </div>
    );
  }
  if (!match) {
    return (
      <div className="rounded-md border border-border/60 bg-muted/30 p-2 text-xs text-muted-foreground">
        No matching precursor peak was found in the parent MS1 spectrum.
      </div>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-2 rounded-md border border-border/60 bg-muted/30 p-2 text-xs text-muted-foreground md:grid-cols-4">
      <Metric label="Precursor m/z" value={formatNumber(match.targetMz, 4)} />
      <Metric label="Matched peak m/z" value={formatNumber(match.peak.mz, 4)} />
      <Metric label="Mass error" value={formatMassError(match)} />
      <Metric label="Intensity" value={formatNumber(match.peak.intensity, 2)} />
      <div className="col-span-2 text-[11px] md:col-span-4">
        Match tolerance: {formatNumber(toleranceDa, 4)} Da
      </div>
    </div>
  );
}

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function SpectrumErrorState({ error }: { error: unknown }) {
  const parsed = parseApiError(error);
  if (parsed.kind === "not_found") {
    return <PlotStatus kind="not_found" title="Scan not found in this run." />;
  }
  if (parsed.kind === "indexed_mzml_unsupported") {
    return (
      <PlotStatus
        kind="unsupported"
        title="This mzML file does not support indexed random access."
        message="Use an indexed, uncompressed mzML file for direct scan viewing."
      />
    );
  }
  return <PlotStatus kind="error" title="Failed to load spectrum." />;
}
