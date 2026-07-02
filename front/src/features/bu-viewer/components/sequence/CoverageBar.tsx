import type { MappedCoverageSegment, PeptideColorMap } from "./coverageLayout";
import { formatSegmentTooltip, getSegmentColor } from "./coverageLayout";

export function CoverageBar({
  sequenceLength,
  segments,
  colorMap,
  chunkSize = 50,
}: {
  sequenceLength: number;
  segments: MappedCoverageSegment[];
  colorMap: PeptideColorMap;
  chunkSize?: number;
}) {
  const safeLength = Number.isFinite(sequenceLength) ? sequenceLength : 0;
  if (safeLength <= 0) return null;

  const step = Number.isFinite(chunkSize) ? Math.max(1, Math.floor(chunkSize)) : 50;
  const dividers: number[] = [];
  for (let position = step; position < safeLength; position += step) {
    dividers.push(position);
  }

  return (
    <div
      aria-label="Sequence coverage bar"
      className="relative h-4 w-full overflow-hidden rounded-sm bg-[#f3f3f3]"
    >
      {segments.map((segment) => {
        const color = getSegmentColor(segment, colorMap);
        if (!color) return null;

        return (
          <div
            key={`${segment.peptide_id}-${segment.start}-${segment.end}-${segment.occurrence_index}`}
            title={formatSegmentTooltip(segment)}
            className="absolute inset-y-0"
            style={{
              left: `${(segment.start / safeLength) * 100}%`,
              width: `${((segment.end - segment.start) / safeLength) * 100}%`,
              backgroundColor: color,
              opacity: 0.92,
            }}
          />
        );
      })}
      {dividers.map((position) => (
        <span
          key={position}
          className="pointer-events-none absolute inset-y-0 border-l border-dashed border-[#cccccc]"
          style={{ left: `${(position / safeLength) * 100}%` }}
        />
      ))}
    </div>
  );
}
