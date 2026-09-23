import { CHART_COLORS } from "@/features/theme/chartColors";

export const PRODUCT_ION_COLORS = [
  CHART_COLORS.series[0],
  CHART_COLORS.series[1],
  CHART_COLORS.series[2],
  CHART_COLORS.series[9],
  CHART_COLORS.series[3],
  CHART_COLORS.series[7],
  "hsl(var(--warning))",
  CHART_COLORS.series[6],
] as const;

export interface ProductIonColorAssignment {
  assignments: Record<string, string>;
  colors: Record<string, string>;
}

export function assignProductIonColors(
  ionIds: string[],
  previousAssignments: Record<string, string> = {},
): ProductIonColorAssignment {
  const assignments = { ...previousAssignments };
  const colors: Record<string, string> = {};
  const used = new Set<string>();

  for (const ionId of ionIds) {
    const previous = assignments[ionId];
    const color =
      previous && !used.has(previous)
        ? previous
        : PRODUCT_ION_COLORS.find((candidate) => !used.has(candidate)) ?? PRODUCT_ION_COLORS[0];
    assignments[ionId] = color;
    colors[ionId] = color;
    used.add(color);
  }

  return { assignments, colors };
}
