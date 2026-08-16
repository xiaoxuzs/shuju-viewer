import type { DatasetOut } from "@/api/types";

// Max RT distance (minutes) for linking a selected RT to a PFMB slot or mzML
// MS2 scan. Beyond this we surface a hint instead of forcing the association.
// Matches the backend MS2 scan resolve window (scan_resolver max_delta_minutes).
export const RT_LINK_TOLERANCE_MIN = 0.5;
export const SCAN_UNAVAILABLE_REASON = "Not available from imported match metadata";
export const DIACLIP_DISPLAY_NAME = "πdia-clip";

export type InspectedRtSource = "xic" | "pfmb";

export function isDiaclipSourceSoftware(sourceSoftware: string | null | undefined): boolean {
  return sourceSoftware === "DIA-CLIP";
}

export function formatSourceSoftwareName(sourceSoftware: string | null | undefined): string | null {
  if (!sourceSoftware) return null;
  return isDiaclipSourceSoftware(sourceSoftware) ? DIACLIP_DISPLAY_NAME : sourceSoftware;
}

export function getBuDatasetDisplayDescription(dataset: DatasetOut): string {
  const isDiaclip = isDiaclipSourceSoftware(dataset.source_software);
  const description = dataset.description
    ?? `Bottom-Up DIA dataset imported from ${isDiaclip ? DIACLIP_DISPLAY_NAME : "DIA-NN"} results.`;
  return isDiaclip
    ? description.replace(/DIA-CLIP/gi, DIACLIP_DISPLAY_NAME).replace(/DIA-NN/gi, "reference")
    : description;
}

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

export function formatScanValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "N/A";
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric) || numeric < 0) return "N/A";
  return String(value);
}

export function inspectedRtSourceLabel(source: InspectedRtSource): string {
  return source === "xic" ? "XIC selection" : "Fragment Match slot";
}
