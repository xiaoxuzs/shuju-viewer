export const PRODUCT_ION_COLORS = [
  "#2563eb",
  "#dc2626",
  "#16a34a",
  "#9333ea",
  "#ea580c",
  "#0891b2",
  "#ca8a04",
  "#db2777",
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
