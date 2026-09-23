import type { BuRtMzHeatmapOut } from "@/features/bu/types";
import { formatCount } from "@/features/bu/utils";
import { CHART_COLORS } from "@/features/theme/chartColors";

const VIRIDIS = CHART_COLORS.heat;

export function RtMzMiniHeatmap({ heatmap, height = 300 }: { heatmap: BuRtMzHeatmapOut; height?: number }) {
  const binsRt = heatmap.counts.length;
  const binsMz = heatmap.counts[0]?.length ?? 0;
  if (heatmap.total_points === 0 || binsRt === 0 || binsMz === 0 || heatmap.max_count === 0) {
    return (
      <div className="flex h-56 items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
        No identifications for RT-m/z heatmap
      </div>
    );
  }

  const width = 900;
  const left = 66;
  const right = 72;
  const top = 24;
  const bottom = 48;
  const innerW = width - left - right;
  const innerH = height - top - bottom;
  const cellW = innerW / binsRt;
  const cellH = innerH / binsMz;
  const rtMin = heatmap.rt_edges[0] ?? 0;
  const rtMax = heatmap.rt_edges[heatmap.rt_edges.length - 1] ?? 0;
  const mzMin = heatmap.mz_edges[0] ?? 0;
  const mzMax = heatmap.mz_edges[heatmap.mz_edges.length - 1] ?? 0;
  const rtTicks = ticks(rtMin, rtMax, 5);
  const mzTicks = ticks(mzMin, mzMax, 5);

  return (
    <div>
      <div className="mb-2 text-center">
        <div className="text-base font-medium">RT vs precursor m/z</div>
        <div className="text-sm text-muted-foreground">
          {formatCount(heatmap.total_points)} identifications · max bin {formatCount(heatmap.max_count)}
          {heatmap.run_id != null ? ` · run ${heatmap.run_id}` : ""}
        </div>
      </div>
      <div className="overflow-x-auto rounded-md border border-border/60 bg-background">
        <svg width={width} height={height} role="img" aria-label="RT by precursor m/z heatmap">
          <rect x={left} y={top} width={innerW} height={innerH} fill="hsl(var(--muted) / 0.35)" />
          {heatmap.counts.map((row, rtIndex) =>
            row.map((count, mzIndex) => {
              if (count <= 0) return null;
              return (
                <rect
                  key={`${rtIndex}-${mzIndex}`}
                  x={left + rtIndex * cellW}
                  y={top + innerH - (mzIndex + 1) * cellH}
                  width={Math.max(0.8, cellW)}
                  height={Math.max(0.8, cellH)}
                  fill={colorFor(count, heatmap.max_count)}
                >
                  <title>
                    {`${heatmap.rt_edges[rtIndex]?.toFixed(2)}-${heatmap.rt_edges[rtIndex + 1]?.toFixed(2)} min · ${heatmap.mz_edges[mzIndex]?.toFixed(1)}-${heatmap.mz_edges[mzIndex + 1]?.toFixed(1)} Th · ${count}`}
                  </title>
                </rect>
              );
            }),
          )}
          {rtTicks.map((tick) => {
            const x = left + ((tick - rtMin) / Math.max(1e-9, rtMax - rtMin)) * innerW;
            return (
              <g key={`rt-${tick}`}>
                <line x1={x} x2={x} y1={top + innerH} y2={top + innerH + 5} stroke={CHART_COLORS.axis} />
                <text x={x} y={top + innerH + 20} textAnchor="middle" fontSize={11} fill={CHART_COLORS.text}>
                  {tick.toFixed(0)}
                </text>
              </g>
            );
          })}
          {mzTicks.map((tick) => {
            const y = top + innerH - ((tick - mzMin) / Math.max(1e-9, mzMax - mzMin)) * innerH;
            return (
              <g key={`mz-${tick}`}>
                <line x1={left - 5} x2={left} y1={y} y2={y} stroke={CHART_COLORS.axis} />
                <text x={left - 9} y={y + 4} textAnchor="end" fontSize={11} fill={CHART_COLORS.text}>
                  {tick.toFixed(0)}
                </text>
              </g>
            );
          })}
          <text x={left + innerW / 2} y={height - 10} textAnchor="middle" fontSize={12} fill={CHART_COLORS.text}>
            RT ({heatmap.unit_rt})
          </text>
          <text
            transform={`rotate(-90) translate(${-top - innerH / 2},18)`}
            textAnchor="middle"
            fontSize={12}
            fill={CHART_COLORS.text}
          >
            Precursor m/z ({heatmap.unit_mz})
          </text>
          {VIRIDIS.map((color, index) => (
            <rect key={color} x={left + innerW + 24} y={top + innerH - ((index + 1) * innerH) / VIRIDIS.length} width={14} height={innerH / VIRIDIS.length} fill={color} />
          ))}
          <text x={left + innerW + 44} y={top + 4} fontSize={10} fill={CHART_COLORS.text}>
            {formatCount(heatmap.max_count)}
          </text>
          <text x={left + innerW + 44} y={top + innerH} fontSize={10} fill={CHART_COLORS.text}>
            1
          </text>
        </svg>
      </div>
    </div>
  );
}

function colorFor(count: number, maxCount: number): string {
  const t = Math.max(0, Math.min(1, Math.log1p(count) / Math.log1p(maxCount)));
  const index = Math.min(VIRIDIS.length - 1, Math.floor(t * (VIRIDIS.length - 1)));
  return VIRIDIS[index];
}

function ticks(min: number, max: number, count: number): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return [min];
  return Array.from({ length: count }, (_item, index) => min + ((max - min) * index) / (count - 1));
}
