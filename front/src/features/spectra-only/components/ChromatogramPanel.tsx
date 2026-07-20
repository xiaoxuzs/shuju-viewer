import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { PlotStatus } from "@/components/common/plot-status";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchSpectraChromatogram } from "@/features/spectra-only/api/spectraClient";
import { BuChromatogramChart } from "@/features/bu/components/spectrum/BuChromatogramChart";
import { chartQueryRetry, parseApiError } from "@/lib/apiError";
import { ChartRenderBoundary } from "@/components/common/chart-render-boundary";

export function ChromatogramPanel({
  datasetId,
  runId,
  onReady,
}: {
  datasetId: number;
  runId: number | null;
  onReady?: () => void;
}) {
  const [chromType, setChromType] = useState<"tic" | "bpc">("tic");
  const chromatogram = useQuery({
    queryKey: ["spectra-only", datasetId, runId, "chromatogram", chromType],
    queryFn: () => fetchSpectraChromatogram(datasetId, runId!, chromType),
    enabled: runId != null,
    retry: chartQueryRetry,
  });

  useEffect(() => {
    if (
      runId == null
      || chromatogram.isError
      || (!chromatogram.isLoading && (!chromatogram.data || chromatogram.data.rt.length === 0))
    ) onReady?.();
  }, [chromatogram.data, chromatogram.isError, chromatogram.isLoading, onReady, runId]);

  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 pb-2 sm:flex-row sm:items-start sm:justify-between">
        <CardTitle className="text-base">Run Chromatogram</CardTitle>
        <div className="flex rounded-md border border-border bg-muted/30 p-1 text-xs">
          {(["tic", "bpc"] as const).map((type) => (
            <button
              key={type}
              type="button"
              onClick={() => setChromType(type)}
              className={`rounded px-3 py-1 uppercase transition-colors ${
                chromType === type ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {type}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent>
        {runId == null ? (
          <PlotStatus kind="empty" title="No run selected." />
        ) : chromatogram.isLoading ? (
          <PlotStatus kind="loading" title={`Loading ${chromType.toUpperCase()} chromatogram...`} />
        ) : chromatogram.error ? (
          <ChromatogramErrorState error={chromatogram.error} />
        ) : chromatogram.data?.rt.length === 0 ? (
          <PlotStatus kind="empty" title="No chromatogram data available." />
        ) : chromatogram.data ? (
          <ChartRenderBoundary
            key={`${runId}:${chromType}`}
            fallback={<PlotStatus kind="error" title="Failed to draw the chromatogram." />}
            onError={onReady}
          >
            <BuChromatogramChart chromatogram={chromatogram.data} onFirstRender={onReady} />
          </ChartRenderBoundary>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ChromatogramErrorState({ error }: { error: unknown }) {
  const parsed = parseApiError(error);
  if (parsed.kind === "chromatogram_summary_missing") {
    return (
      <PlotStatus
        kind="derived_missing"
        title="Derived chromatogram data is not ready."
        command={parsed.backfillCommand}
      />
    );
  }
  if (parsed.kind === "chromatogram_summary_stale") {
    return (
      <PlotStatus
        kind="derived_stale"
        title="Derived chromatogram data is stale."
        command={parsed.backfillCommand}
      />
    );
  }
  return <PlotStatus kind="error" title="Failed to load chromatogram data." />;
}
