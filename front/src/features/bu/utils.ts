import type { DatasetOut } from "@/api/types";

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
