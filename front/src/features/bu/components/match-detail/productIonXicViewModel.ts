import type { BuProductXicOut } from "@/features/bu/types";
import type { ProductIonSelection } from "@/features/bu/components/match-detail/productIonSelection";

export type ProductIonYAxisMode = "raw" | "normalized";

export interface ProductIonXicTrace {
  ionId: string;
  ion: string;
  series: string;
  position: number;
  charge: number;
  mz: number;
  color: string;
  points: Array<{ rt: number; intensity: number }>;
}

export function normalizeProductIonTrace(
  points: Array<{ rt: number; intensity: number }>,
): Array<{ rt: number; intensity: number }> {
  const valid = points.filter((point) => Number.isFinite(point.rt) && Number.isFinite(point.intensity));
  const maxIntensity = Math.max(0, ...valid.map((point) => point.intensity));
  return valid.map((point) => ({
    rt: point.rt,
    intensity: maxIntensity > 0 ? Math.max(0, point.intensity) / maxIntensity * 100 : 0,
  }));
}

export function buildProductIonXicTrace(
  selection: ProductIonSelection,
  xic: Pick<BuProductXicOut, "points">,
  color: string,
  mode: ProductIonYAxisMode,
): ProductIonXicTrace {
  const rawPoints = xic.points
    .filter((point) => Number.isFinite(point.rt) && Number.isFinite(point.intensity))
    .map((point) => ({ rt: point.rt, intensity: point.intensity }));
  return {
    ionId: selection.id,
    ion: selection.ion,
    series: selection.series,
    position: selection.position,
    charge: selection.charge,
    mz: selection.theoreticalMz,
    color,
    points: mode === "normalized" ? normalizeProductIonTrace(rawPoints) : rawPoints,
  };
}

export function hasProductIonSignal(xic: BuProductXicOut | undefined): boolean {
  return Boolean(xic?.points.some((point) => Number.isFinite(point.intensity) && point.intensity > 0));
}
