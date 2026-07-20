import type { BuDiaWindowsOut } from "@/features/bu/types";
import { CHART_COLORS } from "@/features/theme/chartColors";

const WINDOW_COLOR = CHART_COLORS.series[4];

export function DiaWindowMap({ diaWindows, height = 300 }: { diaWindows: BuDiaWindowsOut; height?: number }) {
  const windows = diaWindows.windows;
  if (windows.length === 0) {
    return <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">No DIA windows</div>;
  }
  const minMz = Math.min(...windows.map((w) => w.mz - w.width / 2));
  const maxMz = Math.max(...windows.map((w) => w.mz + w.width / 2));
  const rowHeight = 16;
  const left = 56;
  const right = 24;
  const top = 22;
  const bottom = 38;
  const innerWidth = 860;
  const innerHeight = Math.max(120, windows.length * rowHeight);
  const svgHeight = Math.max(height, top + innerHeight + bottom);
  const scaleX = (mz: number) => left + ((mz - minMz) / Math.max(1, maxMz - minMz)) * innerWidth;
  const ticks = Array.from({ length: 6 }, (_item, index) => minMz + ((maxMz - minMz) * index) / 5);

  return (
    <div>
      <div className="mb-2 text-center">
        <div className="text-base font-medium">DIA Isolation Windows ({diaWindows.window_count} windows)</div>
        <div className="text-sm text-muted-foreground">Run {diaWindows.run_id}</div>
      </div>
      <div className="overflow-x-auto rounded-md border border-border/60 bg-background">
        <svg width={left + innerWidth + right} height={svgHeight} role="img" aria-label="DIA isolation windows">
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={scaleX(tick)}
                x2={scaleX(tick)}
                y1={top}
                y2={top + innerHeight}
                stroke={CHART_COLORS.grid}
                strokeDasharray="2 3"
              />
              <text x={scaleX(tick)} y={top + innerHeight + 22} textAnchor="middle" fontSize={11} fill={CHART_COLORS.text}>
                {tick.toFixed(0)}
              </text>
            </g>
          ))}
          {windows.map((window, index) => {
            const x = scaleX(window.mz - window.width / 2);
            const width = Math.max(2, scaleX(window.mz + window.width / 2) - x);
            const y = top + index * rowHeight + 2;
            return (
              <g key={`${window.label}-${window.mz}`}>
                <text x={left - 8} y={y + 10} textAnchor="end" fontSize={9} fill={CHART_COLORS.text}>
                  {window.label}
                </text>
                <rect x={x} y={y} width={width} height={12} rx={2} fill={WINDOW_COLOR} opacity={0.72} />
                {width > 26 && (
                  <text x={x + width / 2} y={y + 9} textAnchor="middle" fontSize={8} fill="hsl(var(--chart-series-foreground))">
                    {window.mz.toFixed(0)}
                  </text>
                )}
              </g>
            );
          })}
          <text x={left + innerWidth / 2} y={svgHeight - 8} textAnchor="middle" fontSize={12} fill={CHART_COLORS.text}>
            m/z
          </text>
        </svg>
      </div>
    </div>
  );
}
