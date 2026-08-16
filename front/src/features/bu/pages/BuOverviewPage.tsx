import { useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";

import { DataEmptyState, DataLoadError } from "@/components/common/data-state";
import { ChartRenderBoundary } from "@/components/common/chart-render-boundary";
import { PageLoading } from "@/components/common/page-loading";
import { PlotStatus } from "@/components/common/plot-status";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchBuOverview,
  fetchBuRtMzHeatmap,
  fetchBuRunChromatogram,
  fetchBuRunDiaWindows,
} from "@/features/bu/api/buClient";
import { BuSummaryCards } from "@/features/bu/components/BuSummaryCards";
import { BuQcStats } from "@/features/bu/components/overview/BuQcStats";
import { RunSelector } from "@/features/bu/components/overview/RunSelector";
import { RtMzMiniHeatmap } from "@/features/bu/components/overview/RtMzMiniHeatmap";
import { BuChartModal } from "@/features/bu/components/spectrum/BuChartModal";
import { BuChromatogramChart } from "@/features/bu/components/spectrum/BuChromatogramChart";
import { DiaWindowMap } from "@/features/bu/components/spectrum/DiaWindowMap";
import { BU_CHART, DEFAULT_ZOOM, isZoomed, type Zoom } from "@/features/bu/components/spectrum/chartTheme";
import type { BuDatasetContext } from "@/features/bu/layout/BuDatasetLayout";
import { DIACLIP_DISPLAY_NAME, formatCount, isDiaclipSourceSoftware } from "@/features/bu/utils";
import { chartQueryRetry, parseApiError } from "@/lib/apiError";
import {
  usePageTransition,
  usePageTransitionReady,
  useTransitionSignal,
} from "@/features/page-transition";

const ZOOM_HINT = "wheel to zoom (Shift = Y) · brush-drag = X";

export function BuOverviewPage() {
  const { dataset } = useOutletContext<BuDatasetContext>();
  const { beginManualTransition } = usePageTransition();
  const [chromType, setChromType] = useState<"tic" | "bpc">("tic");
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [chromFullOpen, setChromFullOpen] = useState(false);
  const [chromModalBatchId, setChromModalBatchId] = useState<number | null>(null);
  const [chromModalZoom, setChromModalZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const { data, isLoading, error } = useQuery({
    queryKey: ["bu", dataset.slug, "overview"],
    queryFn: () => fetchBuOverview(dataset.slug),
  });
  const defaultRun = data?.runs.find((run) => run.raw_format === "mzml") ?? data?.runs[0];
  const selectedRun = data?.runs.find((run) => run.run_id === selectedRunId) ?? defaultRun;
  const qMax = data?.q_value_cutoff ?? 0.01;
  const chromatogram = useQuery({
    queryKey: ["bu", dataset.slug, "chromatogram", selectedRun?.run_id, chromType],
    queryFn: () => fetchBuRunChromatogram(dataset.slug, selectedRun!.run_id, chromType),
    enabled: !!selectedRun,
    retry: chartQueryRetry,
  });
  const diaWindows = useQuery({
    queryKey: ["bu", dataset.slug, "dia-windows", selectedRun?.run_id],
    queryFn: () => fetchBuRunDiaWindows(dataset.slug, selectedRun!.run_id),
    enabled: selectedRun?.raw_format === "bruker_d",
    retry: chartQueryRetry,
  });
  const rtMz = useQuery({
    queryKey: ["bu", dataset.slug, "rt-mz", selectedRun?.run_id, qMax],
    queryFn: () =>
      fetchBuRtMzHeatmap(dataset.slug, {
        run_id: selectedRun?.run_id,
        q_max: qMax,
        bins_rt: 80,
        bins_mz: 80,
        decoy: false,
      }),
    enabled: !!data && !!selectedRun,
    retry: chartQueryRetry,
  });
  const chromatogramKey = `${dataset.slug}:${selectedRun?.run_id ?? "none"}:${chromType}`;
  const [chromatogramReady, markChromatogramReady] = useTransitionSignal(chromatogramKey);
  const [chromModalReady, markChromModalReady] = useTransitionSignal(chromModalBatchId);
  const mainContentReady = !isLoading && (
    !data
    || !selectedRun
    || (!chromatogram.isLoading && chromatogramReady)
  );
  usePageTransitionReady(mainContentReady && (!chromFullOpen || chromModalReady));

  useEffect(() => {
    if (
      !selectedRun
      || chromatogram.isError
      || (!chromatogram.isLoading && (!chromatogram.data || chromatogram.data.rt.length === 0))
    ) markChromatogramReady();
  }, [
    chromatogram.data,
    chromatogram.isError,
    chromatogram.isLoading,
    markChromatogramReady,
    selectedRun,
  ]);

  useEffect(() => {
    setChromFullOpen(false);
    setChromModalZoom(DEFAULT_ZOOM);
  }, [chromType, selectedRun?.run_id]);

  useEffect(() => {
    if (!data) return;
    const fallback = data.runs.find((run) => run.raw_format === "mzml") ?? data.runs[0];
    if (!fallback) return;
    setSelectedRunId((current) => (data.runs.some((run) => run.run_id === current) ? current : fallback.run_id));
  }, [data]);

  const selectRun = (runId: number) => {
    if (runId !== selectedRun?.run_id) beginManualTransition();
    setSelectedRunId(runId);
  };

  const openChromatogram = () => {
    const batchId = beginManualTransition();
    setChromModalBatchId(batchId);
    setChromFullOpen(true);
  };

  if (isLoading) return <PageLoading />;
  if (error && !data) return <DataLoadError />;
  if (!data) return <DataEmptyState />;
  const isDiaclip = isDiaclipSourceSoftware(data.source_software);

  return (
    <div className="space-y-5">
      <BuSummaryCards overview={data} />
      <BuQcStats overview={data} />

      <Card>
        <CardHeader className="flex flex-col gap-3 pb-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle className="text-base">Run Chromatogram</CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">{ZOOM_HINT}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <RunSelector runs={data.runs} selectedRunId={selectedRun?.run_id ?? null} onChange={selectRun} />
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
          </div>
        </CardHeader>
        <CardContent>
          {chromatogram.isLoading ? (
            <PlotStatus kind="loading" title={`Loading ${chromType.toUpperCase()} chromatogram...`} />
          ) : chromatogram.error ? (
            <ChromatogramErrorState
              error={chromatogram.error}
              command={
                selectedRun
                  ? `python scripts/backfill_dataset_derived_data.py --dataset-id ${dataset.id} --run-id ${selectedRun.run_id}`
                  : null
              }
            />
          ) : chromatogram.data?.rt.length === 0 ? (
            <PlotStatus kind="empty" title="No chromatogram data available." />
          ) : chromatogram.data ? (
            <ChartRenderBoundary
              key={chromatogramKey}
              fallback={<PlotStatus kind="error" title="Failed to draw the chromatogram." />}
              onError={markChromatogramReady}
            >
              <BuChromatogramChart
                chromatogram={chromatogram.data}
                onOpenFull={openChromatogram}
                onFirstRender={markChromatogramReady}
              />
            </ChartRenderBoundary>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">RT-m/z Identifications</CardTitle>
        </CardHeader>
        <CardContent>
          {rtMz.isLoading ? (
            <PlotStatus kind="loading" title="Loading RT-m/z heatmap..." className="min-h-72" />
          ) : rtMz.error ? (
            <PlotStatus kind="error" className="min-h-72" />
          ) : rtMz.data?.total_points === 0 ? (
            <PlotStatus kind="empty" title="No RT-m/z identifications available." className="min-h-72" />
          ) : rtMz.data ? (
            <RtMzMiniHeatmap heatmap={rtMz.data} />
          ) : null}
        </CardContent>
      </Card>

      {selectedRun?.raw_format === "bruker_d" && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">DIA Isolation Windows</CardTitle>
          </CardHeader>
          <CardContent>
            {diaWindows.isLoading ? (
              <PlotStatus kind="loading" title="Loading DIA isolation windows..." className="min-h-72" />
            ) : diaWindows.error ? (
              <PlotStatus kind="error" className="min-h-72" />
            ) : diaWindows.data ? (
              <DiaWindowMap diaWindows={diaWindows.data} />
            ) : null}
          </CardContent>
        </Card>
      )}

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
                <span className="col-span-2 break-all">
                  {isDiaclip ? `${DIACLIP_DISPLAY_NAME} run` : "DIA-NN"}: {run.diann_run_name ?? "-"}
                </span>
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
          <ChartRenderBoundary
            key={chromModalBatchId}
            fallback={<PlotStatus kind="error" title="Failed to draw the chromatogram." />}
            onError={markChromModalReady}
          >
            <BuChromatogramChart
              chromatogram={chromatogram.data}
              height={Math.max(BU_CHART.chromatogramHeight, 560)}
              zoom={chromModalZoom}
              onZoomChange={setChromModalZoom}
              onFirstRender={markChromModalReady}
            />
          </ChartRenderBoundary>
        </BuChartModal>
      )}
    </div>
  );
}

function ChromatogramErrorState({ error, command }: { error: unknown; command: string | null }) {
  const parsed = parseApiError(error);
  if (parsed.kind === "chromatogram_summary_missing") {
    return (
      <PlotStatus
        kind="derived_missing"
        title="Derived chromatogram data is not ready."
        command={parsed.backfillCommand ?? command}
      />
    );
  }
  if (parsed.kind === "chromatogram_summary_stale") {
    return (
      <PlotStatus
        kind="derived_stale"
        title="Derived chromatogram data is stale."
        command={parsed.backfillCommand ?? command}
      />
    );
  }
  if (parsed.kind === "unsupported_raw_format") {
    return <PlotStatus kind="unsupported" />;
  }
  return <PlotStatus kind="error" />;
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
