export type SpectrumLabelMode = "top" | "all" | "none";

export interface SpectrumLabelCandidate {
  id: string;
  x: number;
  y: number;
  intensity: number;
  width: number;
  height: number;
}

interface LabelBounds {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export function layoutSpectrumLabels(
  candidates: SpectrumLabelCandidate[],
  mode: SpectrumLabelMode,
  plotWidth: number,
  plotHeight: number,
  topLimit: number,
): SpectrumLabelCandidate[] {
  if (mode === "none") return [];

  const inBounds = candidates.filter((candidate) => {
    const bounds = candidateBounds(candidate);
    return bounds.x0 >= 0 && bounds.x1 <= plotWidth && bounds.y0 >= 0 && bounds.y1 <= plotHeight;
  });
  if (mode === "all") return inBounds;

  const placed: LabelBounds[] = [];
  const selected: SpectrumLabelCandidate[] = [];
  const strongest = [...inBounds].sort((a, b) => b.intensity - a.intensity || a.x - b.x);
  for (const candidate of strongest) {
    if (selected.length >= topLimit) break;
    const bounds = candidateBounds(candidate);
    if (placed.some((other) => overlaps(bounds, other))) continue;
    placed.push(bounds);
    selected.push(candidate);
  }
  return selected;
}

function candidateBounds(candidate: SpectrumLabelCandidate): LabelBounds {
  return {
    x0: candidate.x - candidate.width / 2,
    x1: candidate.x + candidate.width / 2,
    y0: candidate.y - candidate.height,
    y1: candidate.y,
  };
}

function overlaps(a: LabelBounds, b: LabelBounds): boolean {
  return !(a.x1 <= b.x0 || a.x0 >= b.x1 || a.y1 <= b.y0 || a.y0 >= b.y1);
}
