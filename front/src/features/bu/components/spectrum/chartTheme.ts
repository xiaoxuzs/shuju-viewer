export interface Zoom {
  x: [number, number] | null;
  y: [number, number] | null;
}

export const DEFAULT_ZOOM: Zoom = { x: null, y: null };

export function isZoomed(zoom: Zoom): boolean {
  return zoom.x !== null || zoom.y !== null;
}

export const BU_CHART = {
  unmatched: "#bbbbbb",
  b: "#1f77b4",
  y: "#d62728",
  tic: "#1f77b4",
  bpc: "#d62728",
  isotopeM1: "#c57a12",
  isotopeM2: "#7952b3",
  rtWindow: "#2ca02c",
  apex: "#ff0000",
  grid: "hsl(var(--border))",
  text: "hsl(var(--muted-foreground))",
  axis: "hsl(var(--border))",
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
