import { useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { LoaderCircle, X } from "lucide-react";

import { PlotStatus } from "@/components/common/plot-status";
import { cn } from "@/lib/utils";
import { chartQueryRetry, parseApiError } from "@/lib/apiError";
import { fetchBuMatchProductXics } from "@/features/bu/api/buClient";
import { BuProductIonXicChart } from "@/features/bu/components/spectrum/BuProductIonXicChart";
import type { BuMatchedIon } from "@/features/bu/types";
import {
  MAX_PRODUCT_ION_XICS,
  productIonLabel,
  type ProductIonSelection,
} from "@/features/bu/components/match-detail/productIonSelection";
import { assignProductIonColors } from "@/features/bu/components/match-detail/productIonColors";
import {
  type ProductIonYAxisMode,
} from "@/features/bu/components/match-detail/productIonXicViewModel";
import {
  buildProductIonBatchQueryKey,
  buildProductIonBatchRequest,
  buildProductIonBatchTraces,
  productIonBatchTraceMap,
} from "@/features/bu/components/match-detail/productIonBatch";

const PRODUCT_XIC_STALE_TIME_MS = 5 * 60_000;

export function BuProductIonXicCard({
  datasetId,
  slug,
  matchId,
  runId,
  ms2Scan,
  available,
  matchedIons,
  selections,
  mode,
  ppm,
  rtWindow,
  identificationRt,
  inspectedRt,
  ms2ScanRt,
  warning,
  onRemove,
  onAddTop,
  onClear,
  onModeChange,
}: {
  datasetId: number;
  slug: string;
  matchId: number;
  runId: number | null;
  ms2Scan: number | null;
  available: boolean;
  matchedIons: BuMatchedIon[];
  selections: ProductIonSelection[];
  mode: ProductIonYAxisMode;
  ppm: number;
  rtWindow: { start: number | null; stop: number | null };
  identificationRt: number | null;
  inspectedRt: number | null;
  ms2ScanRt: number | null;
  warning?: string | null;
  onRemove: (ionId: string) => void;
  onAddTop: () => void;
  onClear: () => void;
  onModeChange: (mode: ProductIonYAxisMode) => void;
}) {
  const colorAssignmentsRef = useRef<Record<string, string>>({});
  const colors = useMemo(() => {
    const result = assignProductIonColors(
      selections.map((selection) => selection.id),
      colorAssignmentsRef.current,
    );
    colorAssignmentsRef.current = result.assignments;
    return result.colors;
  }, [selections]);
  const request = useMemo(
    () => buildProductIonBatchRequest(selections, ppm, null),
    [ppm, selections],
  );
  const queryKey = useMemo(
    () =>
      buildProductIonBatchQueryKey({
        datasetId,
        slug,
        matchId,
        runId,
        ms2Scan,
        selections,
        tolerancePpm: ppm,
        rtWindowOverride: null,
      }),
    [datasetId, matchId, ms2Scan, ppm, runId, selections, slug],
  );
  const batchQuery = useQuery({
    queryKey,
    queryFn: () => fetchBuMatchProductXics(slug, matchId, request),
    enabled: available && selections.length > 0,
    staleTime: PRODUCT_XIC_STALE_TIME_MS,
    retry: chartQueryRetry,
  });
  const traceById = useMemo(
    () => productIonBatchTraceMap(batchQuery.data),
    [batchQuery.data],
  );
  const traces = useMemo(
    () => buildProductIonBatchTraces(selections, batchQuery.data, colors, mode),
    [batchQuery.data, colors, mode, selections],
  );
  const allFailed =
    selections.length > 0
    && selections.every((selection) => traceById.get(selection.id)?.status === "error");
  const allNoSignal =
    selections.length > 0
    && batchQuery.data !== undefined
    && (
      batchQuery.data.traces.length === 0
      || selections.every((selection) => traceById.get(selection.id)?.status === "no_signal")
    );
  const addTopDisabled =
    !available
    || matchedIons.length === 0
    || selections.length >= MAX_PRODUCT_ION_XICS;

  return (
    <section
      className="min-w-0 rounded-lg border border-border/70 bg-background/70 p-3"
      data-testid="product-ion-xic-card"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="text-sm font-semibold">Product ion XIC comparison</h4>
          <p className="mt-1 text-xs text-muted-foreground">
            Compare XIC traces for selected matched fragment ions.
          </p>
          <div className="mt-1 text-xs font-medium">
            Selected product ions: {selections.length} / {MAX_PRODUCT_ION_XICS}
          </div>
        </div>
        <div
          className="flex flex-wrap items-center justify-end gap-1.5"
          data-testid="product-ion-xic-controls"
        >
          <button
            type="button"
            onClick={onAddTop}
            disabled={addTopDisabled}
            title="Add the top 3 live matched fragments by intensity."
            className="rounded-md border border-border bg-background px-2 py-1 text-xs text-muted-foreground transition-colors enabled:hover:text-foreground disabled:opacity-40"
          >
            Add top 3 fragments
          </button>
          <button
            type="button"
            onClick={onClear}
            disabled={selections.length === 0}
            className="rounded-md border border-border bg-background px-2 py-1 text-xs text-muted-foreground transition-colors enabled:hover:text-foreground disabled:opacity-40"
          >
            Clear all
          </button>
          <div
            className="inline-flex overflow-hidden rounded-md border border-border bg-background text-xs"
            data-testid="product-ion-y-axis-mode"
          >
            {([
              ["raw", "Raw intensity"],
              ["normalized", "Normalized"],
            ] as const).map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => onModeChange(value)}
                aria-pressed={mode === value}
                className={cn(
                  "px-2 py-1 transition-colors",
                  mode === value ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {selections.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2" data-testid="selected-product-ion-chips">
          {selections.map((selection) => {
            return (
              <button
                key={selection.id}
                type="button"
                onClick={() => onRemove(selection.id)}
                aria-label={`Remove ${productIonLabel(selection)} product ion XIC`}
                className="inline-flex items-center gap-1.5 rounded-full border bg-background px-2.5 py-1 text-xs"
                style={{ borderColor: colors[selection.id] }}
              >
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: colors[selection.id] }}
                />
                <span>{productIonLabel(selection)} {selection.theoreticalMz.toFixed(4)} m/z</span>
                {batchQuery.isPending || batchQuery.isFetching ? (
                  <LoaderCircle className="h-3 w-3 animate-spin text-muted-foreground" />
                ) : (
                  <X className="h-3 w-3 text-muted-foreground" />
                )}
              </button>
            );
          })}
        </div>
      )}

      {warning && (
        <p className="mt-3 text-xs font-medium text-amber-600" role="alert">
          {warning}
        </p>
      )}

      {!available ? (
        <EmptyState text="Product ion XIC is not available for this data source." />
      ) : matchedIons.length === 0 ? (
        <EmptyState text="No matched fragment ions available for product ion XIC." />
      ) : selections.length === 0 ? (
        <EmptyState text="Select product ions to display product XIC." />
      ) : (
        <>
          {(batchQuery.isPending || batchQuery.isFetching) && traces.length === 0 && (
            <PlotStatus kind="loading" title="Loading product XIC..." className="mt-3 min-h-[180px]" />
          )}
          {batchQuery.isError && <ProductXicErrorState error={batchQuery.error} />}
          {!batchQuery.isError && allFailed && (
            <PlotStatus kind="error" title="Failed to load product ion XIC." className="mt-3 min-h-[180px]" />
          )}
          {!batchQuery.isError && !allFailed && allNoSignal && (
            <PlotStatus
              kind="no_signal"
              title="No product ion signal in the selected range."
              className="mt-3 min-h-[180px]"
            />
          )}
          {!batchQuery.isError && !allFailed && !allNoSignal && traces.length > 0 && (
            <BuProductIonXicChart
              traces={traces}
              mode={mode}
              height={280}
              rtWindow={rtWindow}
              rtMarkers={[
                ...(inspectedRt !== null
                  ? [{ rt: inspectedRt, label: "Current inspected RT", color: "#7c3aed", dashed: true }]
                  : []),
                ...(ms2ScanRt !== null
                  ? [{ rt: ms2ScanRt, label: "MS2 scan RT", color: "#0f766e" }]
                  : []),
                ...(identificationRt !== null
                  ? [{ rt: identificationRt, label: "Identification RT apex", color: "#dc2626", dashed: true }]
                  : []),
              ]}
            />
          )}
          {!allNoSignal && (
            <div className="mt-2 space-y-1 text-xs">
              {selections.map((selection) => {
                const trace = traceById.get(selection.id);
                if (trace?.status === "error") {
                  return (
                    <p key={selection.id} className="text-destructive">
                      Failed to load product ion XIC for {productIonLabel(selection)}.
                    </p>
                  );
                }
                if (trace?.status === "no_signal") {
                  return (
                    <p key={selection.id} className="text-muted-foreground">
                      No signal detected for {productIonLabel(selection)} in the selected RT window.
                    </p>
                  );
                }
                return null;
              })}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function ProductXicErrorState({ error }: { error: unknown }) {
  const parsed = parseApiError(error);
  if (parsed.kind === "scan_index_missing") {
    return (
      <PlotStatus
        kind="derived_missing"
        title="Derived scan index is not ready."
        command={parsed.backfillCommand}
        className="mt-3 min-h-[180px]"
      />
    );
  }
  if (parsed.kind === "scan_index_stale") {
    return (
      <PlotStatus
        kind="derived_stale"
        title="Derived scan index is stale."
        command={parsed.backfillCommand}
        className="mt-3 min-h-[180px]"
      />
    );
  }
  if (parsed.kind === "unsupported_raw_format" || parsed.kind === "indexed_mzml_unsupported") {
    return <PlotStatus kind="unsupported" className="mt-3 min-h-[180px]" />;
  }
  return <PlotStatus kind="error" title="Failed to load product ion XIC." className="mt-3 min-h-[180px]" />;
}

function EmptyState({ text }: { text: string }) {
  return (
    <div
      className={cn(
        "mt-3 flex min-h-[170px] items-center justify-center rounded-md border border-dashed px-4 py-4 text-center text-sm",
        "text-muted-foreground",
      )}
      data-testid="product-ion-xic-empty-state"
    >
      {text}
    </div>
  );
}
