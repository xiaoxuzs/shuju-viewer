import type { BuMobilitySliceOut } from "@/features/bu-viewer/types";
import { formatIntensity } from "@/features/bu-viewer/components/spectrum/chartTheme";

export function MzMobilityScatter({ slice, height = 320 }: { slice: BuMobilitySliceOut; height?: number }) {
  const points = slice.mz
    .map((mz, index) => ({
      mz,
      mobility: slice.one_over_k0[index],
      intensity: slice.intensity[index] ?? 0,
    }))
    .filter((point) => Number.isFinite(point.mz) && Number.isFinite(point.mobility) && Number.isFinite(point.intensity));
  if (points.length === 0) {
    return <div className="flex h-52 items-center justify-center text-sm text-muted-foreground">No mobility slice points</div>;
  }
  const maxPoints = 4500;
  const step = Math.max(1, Math.ceil(points.length / maxPoints));
  const sampled = points.filter((_point, index) => index % step === 0);
  const minMz = Math.min(...sampled.map((p) => p.mz));
  const maxMz = Math.max(...sampled.map((p) => p.mz));
  const minMobility = Math.min(...sampled.map((p) => p.mobility));
  const maxMobility = Math.max(...sampled.map((p) => p.mobility));
  const maxLog = Math.max(...sampled.map((p) => Math.log10(p.intensity + 1)), 1);
  const left = 64;
  const right = 26;
  const top = 28;
  const bottom = 44;
  const width = 900;
  const innerWidth = width - left - right;
  const innerHeight = Math.max(160, height - top - bottom);
  const x = (mz: number) => left + ((mz - minMz) / Math.max(1, maxMz - minMz)) * innerWidth;
  const y = (mobility: number) => top + innerHeight - ((mobility - minMobility) / Math.max(1e-6, maxMobility - minMobility)) * innerHeight;
  const color = (intensity: number) => {
    const t = Math.max(0, Math.min(1, Math.log10(intensity + 1) / maxLog));
    return `hsl(${260 - t * 190}, 78%, ${62 - t * 20}%)`;
  };

  return (
    <div>
      <div className="mb-2 text-center">
        <div className="text-base font-medium">m/z vs Ion Mobility</div>
        <div className="text-sm text-muted-foreground">
          {sampled.length.toLocaleString()} / {points.length.toLocaleString()} points
          {slice.rt_min != null ? ` · RT ${slice.rt_min.toFixed(2)} min` : ""}
          {slice.frame_id != null ? ` · frame ${slice.frame_id}` : ""}
        </div>
      </div>
      <div className="overflow-x-auto rounded-md border border-border/60 bg-background">
        <svg width={width} height={height} role="img" aria-label="m/z by ion mobility">
          <rect x={left} y={top} width={innerWidth} height={innerHeight} fill="transparent" />
          {Array.from({ length: 6 }, (_item, index) => minMz + ((maxMz - minMz) * index) / 5).map((tick) => (
            <g key={`x-${tick}`}>
              <line x1={x(tick)} x2={x(tick)} y1={top} y2={top + innerHeight} stroke="hsl(var(--border))" strokeDasharray="2 3" />
              <text x={x(tick)} y={top + innerHeight + 20} textAnchor="middle" fontSize={11} fill="hsl(var(--muted-foreground))">
                {tick.toFixed(0)}
              </text>
            </g>
          ))}
          {Array.from({ length: 5 }, (_item, index) => minMobility + ((maxMobility - minMobility) * index) / 4).map((tick) => (
            <g key={`y-${tick}`}>
              <line x1={left} x2={left + innerWidth} y1={y(tick)} y2={y(tick)} stroke="hsl(var(--border))" strokeDasharray="2 3" />
              <text x={left - 8} y={y(tick) + 4} textAnchor="end" fontSize={11} fill="hsl(var(--muted-foreground))">
                {tick.toFixed(3)}
              </text>
            </g>
          ))}
          {sampled.map((point, index) => (
            <circle key={`${point.mz}-${index}`} cx={x(point.mz)} cy={y(point.mobility)} r={1.8} fill={color(point.intensity)} opacity={0.72}>
              <title>{`m/z ${point.mz.toFixed(4)} · 1/K0 ${point.mobility.toFixed(4)} · ${formatIntensity(point.intensity)}`}</title>
            </circle>
          ))}
          <text x={left + innerWidth / 2} y={height - 8} textAnchor="middle" fontSize={12} fill="hsl(var(--muted-foreground))">
            m/z
          </text>
          <text
            transform={`rotate(-90) translate(${-top - innerHeight / 2},18)`}
            textAnchor="middle"
            fontSize={12}
            fill="hsl(var(--muted-foreground))"
          >
            1/K0
          </text>
        </svg>
      </div>
    </div>
  );
}
