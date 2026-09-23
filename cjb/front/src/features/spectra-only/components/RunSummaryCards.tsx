import { useQuery } from "@tanstack/react-query";

import { PlotStatus } from "@/components/common/plot-status";
import { fetchSpectraScanIndex } from "@/features/spectra-only/api/spectraClient";
import { chartQueryRetry, parseApiError } from "@/lib/apiError";
import { formatNumber } from "@/lib/utils";

export function RunSummaryCards({
  datasetId,
  runId,
}: {
  datasetId: number;
  runId: number | null;
}) {
  const scanIndex = useQuery({
    queryKey: ["spectra-only", datasetId, runId, "scan-index", "summary"],
    queryFn: () => fetchSpectraScanIndex(datasetId, runId!, { limit: 1 }),
    enabled: runId != null,
    retry: chartQueryRetry,
  });
  const summary = scanIndex.data?.summary;

  return (
    <section className="mb-5 space-y-3" aria-labelledby="run-summary-title">
      <div>
        <h2 id="run-summary-title" className="text-base font-semibold">
          Run Summary
        </h2>
        {summary && summary.ms1_count > summary.ms2_count && (
          <p className="mt-1 text-xs text-muted-foreground">
            Scan counts reflect the acquisition method and trigger settings.
          </p>
        )}
      </div>

      {runId == null ? (
        <PlotStatus kind="empty" title="No run selected." className="min-h-32" />
      ) : scanIndex.isLoading ? (
        <PlotStatus kind="loading" title="Loading run summary..." className="min-h-32" />
      ) : scanIndex.error ? (
        <RunSummaryErrorState error={scanIndex.error} />
      ) : summary ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
          <SummaryMetric label="Total scans" value={formatInteger(summary.total_scans)} />
          <SummaryMetric label="MS1 scans" value={formatInteger(summary.ms1_count)} />
          <SummaryMetric label="MS2 scans" value={formatInteger(summary.ms2_count)} />
          <SummaryMetric label="Other scans" value={formatInteger(summary.other_count)} />
          <SummaryMetric label="MS2 fraction" value={formatPercent(summary.ms2_fraction)} />
          <SummaryMetric
            label="Precursor-linked MS2"
            value={formatInteger(summary.precursor_linked_ms2_count)}
          />
          <SummaryMetric label="RT range" value={formatRange(summary.rt_min, summary.rt_max, " min")} />
          <SummaryMetric label="Scan range" value={formatIntegerRange(summary.scan_min, summary.scan_max)} />
          <SummaryMetric label="Max TIC" value={formatOptionalNumber(summary.max_tic)} />
          <SummaryMetric label="Max BPC" value={formatOptionalNumber(summary.max_bpc)} />
        </div>
      ) : (
        <PlotStatus kind="empty" title="Run summary is not available." className="min-h-32" />
      )}
    </section>
  );
}

function SummaryMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md border border-border/60 bg-card p-3">
      <div className="text-xs uppercase text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-foreground">{value}</div>
    </div>
  );
}

function formatInteger(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString() : "-";
}

function formatOptionalNumber(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? formatNumber(value, 2) : "-";
}

function formatPercent(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? `${formatNumber(value * 100, 1)}%` : "-";
}

function formatRange(start: number | null, end: number | null, suffix: string): string {
  if (typeof start !== "number" || typeof end !== "number" || !Number.isFinite(start) || !Number.isFinite(end)) {
    return "-";
  }
  return `${formatNumber(start, 2)}-${formatNumber(end, 2)}${suffix}`;
}

function formatIntegerRange(start: number | null, end: number | null): string {
  if (typeof start !== "number" || typeof end !== "number" || !Number.isFinite(start) || !Number.isFinite(end)) {
    return "-";
  }
  return `${formatInteger(start)}-${formatInteger(end)}`;
}

function RunSummaryErrorState({ error }: { error: unknown }) {
  const parsed = parseApiError(error);
  if (parsed.kind === "scan_index_missing") {
    return (
      <PlotStatus
        kind="derived_missing"
        title="Scan index is not available."
        message="Run derived-data backfill or re-import this dataset."
        command={parsed.backfillCommand}
        className="min-h-32"
      />
    );
  }
  if (parsed.kind === "scan_index_stale") {
    return (
      <PlotStatus
        kind="derived_stale"
        title="Scan index is stale."
        message="Run derived-data backfill or re-import this dataset."
        command={parsed.backfillCommand}
        className="min-h-32"
      />
    );
  }
  return <PlotStatus kind="error" title="Failed to load run summary." className="min-h-32" />;
}
