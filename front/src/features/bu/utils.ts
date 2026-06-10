import type { DatasetOut } from "@/api/types";

// Max RT distance (minutes) for linking a selected RT to a PFMB slot or mzML
// MS2 scan. Beyond this we surface a hint instead of forcing the association.
// Matches the backend MS2 scan resolve window (scan_resolver max_delta_minutes).
export const RT_LINK_TOLERANCE_MIN = 0.5;

export function getBuDefaultQMax(dataset: DatasetOut): number | undefined {
  const value = dataset.extra_metadata?.q_value_cutoff;
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString();
}

export function formatDecimal(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  if (value !== 0 && Math.abs(value) < 0.001) return value.toExponential(2);
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}
