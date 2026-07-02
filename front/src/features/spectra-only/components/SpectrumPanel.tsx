import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { PlotStatus } from "@/components/common/plot-status";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchSpectraSpectrum } from "@/features/spectra-only/api/spectraClient";
import { Lcms3DPanel } from "@/features/lcms3d/Lcms3DPanel";
import { chartQueryRetry, parseApiError } from "@/lib/apiError";
import { formatNumber } from "@/lib/utils";

export function SpectrumPanel({
  datasetId,
  runId,
  scanNumber,
}: {
  datasetId: number;
  runId: number | null;
  scanNumber: number | null;
}) {
  const spectrum = useQuery({
    queryKey: ["spectra-only", datasetId, runId, "spectrum", scanNumber],
    queryFn: () => fetchSpectraSpectrum(datasetId, runId!, scanNumber!),
    enabled: runId != null && scanNumber != null,
    retry: chartQueryRetry,
  });
  const peaks = useMemo(() => {
    if (!spectrum.data) return [];
    return spectrum.data.mz.map((mz, index) => ({
      mz,
      intensity: spectrum.data?.intensity[index] ?? 0,
    }));
  }, [spectrum.data]);

  if (spectrum.data) {
    return (
      <div>
        <div className="mb-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground md:grid-cols-4">
          <Metric label="Peaks" value={peaks.length.toLocaleString()} />
          <Metric label="Native ID" value={spectrum.data.native_id ?? "-"} />
          <Metric label="MS Level" value={`MS${spectrum.data.ms_level}`} />
          <Metric label="RT" value={`${formatNumber(spectrum.data.rt_seconds / 60, 2)} min`} />
        </div>
        <Lcms3DPanel
          peaks={peaks}
          scan={spectrum.data.scan}
          retentionTimeSeconds={spectrum.data.rt_seconds}
        />
      </div>
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
