import type { DatasetOut } from "@/api/types";

export function isSpectraOnlyDataset(dataset: DatasetOut): boolean {
  const shape = String(dataset.capabilities?.analysis_shape ?? "").toLowerCase();
  return dataset.dataset_mode === "spectra_only" || shape === "mzml_only" || shape === "raw_mzml_only";
}
