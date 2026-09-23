export const COVERAGE_PEPTIDE_COLORS = [
  "#1d4ed8",
  "#dc2626",
  "#16a34a",
  "#ea580c",
  "#7c3aed",
  "#0f766e",
  "#be185d",
  "#0891b2",
  "#475569",
  "#9333ea",
  "#15803d",
  "#c2410c",
] as const;

export const SELECTED_PEPTIDE_HIGHLIGHT = "#fde047";
export const SELECTED_PEPTIDE_HIGHLIGHT_SOFT = "#fef08a";

export function coverageMarkerBackground(color: string, alpha = 0.2): string {
  const normalized = color.trim().replace(/^#/, "");
  const expanded =
    normalized.length === 3
      ? Array.from(normalized, (part) => `${part}${part}`).join("")
      : normalized;

  if (!/^[0-9a-fA-F]{6}$/.test(expanded)) return color;

  const value = Number.parseInt(expanded, 16);
  const red = (value >> 16) & 255;
  const green = (value >> 8) & 255;
  const blue = value & 255;

  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}
