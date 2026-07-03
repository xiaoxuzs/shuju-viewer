import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { PlotStatus } from "@/components/common/plot-status";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { chartQueryRetry, parseApiError } from "@/lib/apiError";
import { formatNumber } from "@/lib/utils";

const DEFAULT_PRECURSOR_MATCH_TOLERANCE_DA = 0.05;

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
}: {
  datasetId: number;
  runId: number | null;
  scanNumber: number | null;
  titlePrefix?: string;
  highlight?: SpectrumHighlight | null;
}) {
  const [zoom, setZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const [showLargeSpectrum, setShowLargeSpectrum] = useState(false);
  const spectrum = useQuery({
    queryKey: ["spectra-only", datasetId, runId, "spectrum", scanNumber],
    queryFn: () => fetchSpectraSpectrum(datasetId, runId!, scanNumber!),
    enabled: runId != null && scanNumber != null,
    retry: chartQueryRetry,
  });
  const peaks = useMemo<ChartPeak[]>(() => {
    if (!spectrum.data) return [];
    return spectrum.data.mz.map((mz, index) => ({
      mz,
      intensity: spectrum.data?.intensity[index] ?? 0,
    }));
  }, [spectrum.data]);
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
  }, [runId, scanNumber]);

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
          <CardHeader className="flex flex-row items-baseline justify-between gap-3">
            <div>
              <CardTitle className="text-base">{title}</CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
            </div>
          </CardHeader>
          <CardContent className="space-y-3" data-testid="spectra-only-2d-spectrum-chart">
            {highlight && (
              <PrecursorHighlightStatus
                targetMz={highlightTargetMz}
                match={precursorPeakMatch}
                toleranceDa={highlightToleranceDa}
              />
            )}
            <SpectrumChart
              peaks={peaks}
              xLabel="m/z"
              yLabel="Intensity"
              height={420}
              marker={highlightMarker}
              highlightPeak={highlightPeak}
              zoom={zoom}
              onZoomChange={setZoom}
              onOpenFull={() => setShowLargeSpectrum(true)}
              emptyHint="No peaks to display for this scan."
            />
          </CardContent>
        </Card>
        {showLargeSpectrum && (
          <SpectrumModal title={title} subtitle={subtitle} onClose={() => setShowLargeSpectrum(false)}>
            <SpectrumChart
              peaks={peaks}
              xLabel="m/z"
              yLabel="Intensity"
              height={720}
              marker={highlightMarker}
              highlightPeak={highlightPeak}
              zoom={zoom}
              onZoomChange={setZoom}
              emptyHint="No peaks to display for this scan."
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
