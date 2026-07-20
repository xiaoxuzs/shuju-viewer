import { CHART_COLORS } from "@/features/theme/chartColors";

export interface Zoom {
  x: [number, number] | null;
  y: [number, number] | null;
}

export const DEFAULT_ZOOM: Zoom = { x: null, y: null };

export function isZoomed(zoom: Zoom): boolean {
  return zoom.x !== null || zoom.y !== null;
}

export const BU_CHART = {
  unmatched: CHART_COLORS.unmatched,
  b: CHART_COLORS.series[0],
  y: CHART_COLORS.series[1],
  tic: CHART_COLORS.series[0],
  bpc: CHART_COLORS.series[1],
  isotopeM1: CHART_COLORS.series[3],
  isotopeM2: CHART_COLORS.series[4],
  rtWindow: CHART_COLORS.series[2],
  apex: CHART_COLORS.series[1],
  grid: CHART_COLORS.grid,
  text: CHART_COLORS.text,
  axis: CHART_COLORS.axis,
  margin: { top: 22, right: 20, bottom: 48, left: 72 },
  ms2Height: 360,
  xicHeight: 280,
  chromatogramHeight: 240,
};

export function formatIntensity(value: number): string {
  if (!Number.isFinite(value)) return "-";
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(1)}G`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(value >= 100e6 ? 0 : 1)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(value >= 100e3 ? 0 : 1)}K`;
  return value.toFixed(0);
}
