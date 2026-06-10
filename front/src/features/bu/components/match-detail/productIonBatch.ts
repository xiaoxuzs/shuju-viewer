import type {
  BuProductXicBatchIn,
  BuProductXicBatchOut,
  BuProductXicBatchTraceOut,
} from "@/features/bu/types";
import type { ProductIonSelection } from "@/features/bu/components/match-detail/productIonSelection";
import {
  buildProductIonXicTrace,
  type ProductIonXicTrace,
  type ProductIonYAxisMode,
} from "@/features/bu/components/match-detail/productIonXicViewModel";

export type ProductIonRtWindowOverride = { start: number; end: number } | null;

export function canonicalProductIonSelections(
  selections: ProductIonSelection[],
): ProductIonSelection[] {
  return [...selections].sort((a, b) => a.id.localeCompare(b.id));
}

export function buildProductIonBatchRequest(
  selections: ProductIonSelection[],
  tolerancePpm: number,
  rtWindowOverride: ProductIonRtWindowOverride = null,
): BuProductXicBatchIn {
  const request: BuProductXicBatchIn = {
    tolerance_ppm: tolerancePpm,
    ions: canonicalProductIonSelections(selections).map((selection) => ({
      id: selection.id,
      ion: selection.ion,
      series: selection.series,
      position: selection.position,
      charge: selection.charge,
      mz: selection.theoreticalMz,
    })),
  };
  if (rtWindowOverride !== null) request.rt_window = rtWindowOverride;
  return request;
}

export function buildProductIonBatchQueryKey(input: {
  datasetId: number;
  slug: string;
  matchId: number;
  runId: number | null;
  ms2Scan: number | null;
  selections: ProductIonSelection[];
  tolerancePpm: number;
  rtWindowOverride?: ProductIonRtWindowOverride;
}): readonly unknown[] {
  return [
    "bu",
    input.datasetId,
    input.slug,
    "matches",
    input.matchId,
    "run",
    input.runId,
    "ms2-scan",
    input.ms2Scan,
    "product-xics",
    input.tolerancePpm,
    input.rtWindowOverride ?? null,
    canonicalProductIonSelections(input.selections).map((selection) => ({
      id: selection.id,
      mz: selection.theoreticalMz,
      charge: selection.charge,
    })),
  ] as const;
}

export function productIonBatchTraceMap(
  response: BuProductXicBatchOut | undefined,
): Map<string, BuProductXicBatchTraceOut> {
  return new Map((response?.traces ?? []).map((trace) => [trace.id, trace]));
}

export function buildProductIonBatchTraces(
  selections: ProductIonSelection[],
  response: BuProductXicBatchOut | undefined,
  colors: Record<string, string>,
  mode: ProductIonYAxisMode,
): ProductIonXicTrace[] {
  const byId = productIonBatchTraceMap(response);
  return selections.flatMap((selection) => {
    const trace = byId.get(selection.id);
    if (!trace || trace.status === "error") return [];
    return [buildProductIonXicTrace(selection, trace, colors[selection.id], mode)];
  });
}
