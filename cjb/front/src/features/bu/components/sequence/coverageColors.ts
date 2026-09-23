import { CHART_COLORS } from "@/features/theme/chartColors";

export const COVERAGE_PEPTIDE_COLORS = CHART_COLORS.series;

export const SELECTED_PEPTIDE_HIGHLIGHT = CHART_COLORS.selection;

export function coverageMarkerBackground(color: string, alpha = 0.2): string {
  return `color-mix(in srgb, ${color} ${Math.round(alpha * 100)}%, transparent)`;
}
