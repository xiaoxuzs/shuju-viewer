import { useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchBuOverview, fetchBuRunChromatogram } from "@/features/bu/api/buClient";
import { BuSummaryCards } from "@/features/bu/components/BuSummaryCards";
import { BuChartModal } from "@/features/bu/components/spectrum/BuChartModal";
import { BuChromatogramChart } from "@/features/bu/components/spectrum/BuChromatogramChart";
import { BU_CHART, DEFAULT_ZOOM, isZoomed, type Zoom } from "@/features/bu/components/spectrum/chartTheme";
import type { BuDatasetContext } from "@/features/bu/layout/BuDatasetLayout";
import { formatCount } from "@/features/bu/utils";

const ZOOM_HINT = "wheel to zoom (Shift = Y) · brush-drag = X";

export function BuOverviewPage() {
  const { dataset } = useOutletContext<BuDatasetContext>();
  const [chromType, setChromType] = useState<"tic" | "bpc">("tic");
  const [chromFullOpen, setChromFullOpen] = useState(false);
  const [chromModalZoom, setChromModalZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const { data, isLoading, error } = useQuery({
    queryKey: ["bu", dataset.slug, "overview"],
    queryFn: () => fetchBuOverview(dataset.slug),
  });
  const mzmlRun = data?.runs.find((run) => run.raw_format === "mzml");
  const chromatogram = useQuery({
    queryKey: ["bu", dataset.slug, "chromatogram", mzmlRun?.run_id, chromType],
    queryFn: () => fetchBuRunChromatogram(dataset.slug, mzmlRun!.run_id, chromType),
    enabled: !!mzmlRun,
  });

  useEffect(() => {
    setChromFullOpen(false);
    setChromModalZoom(DEFAULT_ZOOM);
  }, [chromType, mzmlRun?.run_id]);

  if (isLoading) return <Skeleton className="h-64" />;
  if (error) return <p className="text-destructive">{(error as Error).message}</p>;
  if (!data) return null;

  return (
    <div className="space-y-5">
      <BuSummaryCards overview={data} />

      <Card>
        <CardHeader className="flex flex-col gap-3 pb-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle className="text-base">Run Chromatogram</CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">{ZOOM_HINT}</p>
          </div>
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
          {chromatogram.isLoading && <Skeleton className="h-60" />}
          {chromatogram.error && <p className="text-destructive">{(chromatogram.error as Error).message}</p>}
          {chromatogram.data && (
            <BuChromatogramChart chromatogram={chromatogram.data} onOpenFull={() => setChromFullOpen(true)} />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Runs</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {data.runs.map((run) => (
            <div key={run.run_id} className="rounded-md border border-border/60 bg-muted/30 p-3">
              <div className="break-all font-medium">{run.file_name}</div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                <span>Format: {run.raw_format ?? "-"}</span>
                <span>Matches: {formatCount(run.match_count)}</span>
                <span className="col-span-2 break-all">DIA-NN: {run.diann_run_name ?? "-"}</span>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      {chromFullOpen && chromatogram.data && (
        <BuChartModal
          title={`${chromatogram.data.type.toUpperCase()} Chromatogram`}
          subtitle={ZOOM_HINT}
          onClose={() => setChromFullOpen(false)}
          actions={<ResetZoomButton zoom={chromModalZoom} onReset={() => setChromModalZoom(DEFAULT_ZOOM)} />}
        >
          <BuChromatogramChart
            chromatogram={chromatogram.data}
            height={Math.max(BU_CHART.chromatogramHeight, 560)}
            zoom={chromModalZoom}
            onZoomChange={setChromModalZoom}
          />
        </BuChartModal>
      )}
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
