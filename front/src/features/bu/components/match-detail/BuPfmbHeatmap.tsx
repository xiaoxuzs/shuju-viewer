import { useMemo, useState } from "react";
import * as d3 from "d3";

import type { BuMs2AnnotationMatrixOut } from "@/features/bu/types";
import { PFMB_SERIES_COLOR, seriesLabel } from "@/features/bu/components/match-detail/pfmbSeries";
import { formatIntensity } from "@/features/bu/components/spectrum/chartTheme";

const DEFAULT_MAX_ROWS = 20;
const CELL_W = 20;
const CELL_H = 18;
const LABEL_W = 48;
const HEADER_H = 22;

export function BuPfmbHeatmap({
  matrix,
  selectedRt,
  highlight,
  onSelectRt,
  onHighlight,
  maxRows = DEFAULT_MAX_ROWS,
}: {
  matrix: BuMs2AnnotationMatrixOut;
  selectedRt: number | null;
  highlight?: ReadonlySet<string>;
  onSelectRt: (rt: number) => void;
  onHighlight: (familyKey: string) => void;
  maxRows?: number;
}) {
  const [showAll, setShowAll] = useState(false);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);

  const { slots, fragments, intensity, apex_slot } = matrix;
  const rows = showAll ? fragments : fragments.slice(0, maxRows);

  const maxIntensity = useMemo(() => {
    let m = 0;
    for (const row of intensity) for (const v of row) if (v > m) m = v;
    return m;
  }, [intensity]);
  const logMax = Math.log1p(maxIntensity);

  const color = (v: number): string => {
    if (v <= 0 || logMax <= 0) return "transparent";
    return d3.interpolateViridis(Math.log1p(v) / logMax);
  };

  const apexCol = useMemo(
    () => slots.findIndex((s) => s.slot_index === apex_slot),
    [slots, apex_slot],
  );
  const currentCol = useMemo(() => {
    if (selectedRt == null) return apexCol;
    let best = -1;
    let bestD = Infinity;
    slots.forEach((s, i) => {
      const d = Math.abs(s.rt_minutes - selectedRt);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    return best;
  }, [slots, selectedRt, apexCol]);

  if (slots.length === 0 || fragments.length === 0) {
    return (
      <p className="py-4 text-xs text-muted-foreground" data-testid="pfmb-heatmap-empty">
        No PFMB fragment matrix is available for this match.
      </p>
    );
  }

  const width = LABEL_W + slots.length * CELL_W;
  const height = HEADER_H + rows.length * CELL_H;

  return (
    <div className="mb-4" data-testid="pfmb-heatmap">
      <div className="mb-1 flex items-center justify-between">
        <div className="text-xs uppercase tracking-wider text-muted-foreground">
          RT x fragment intensity (log scale)
        </div>
        {fragments.length > maxRows && (
          <button
            type="button"
            data-testid="pfmb-heatmap-toggle"
            onClick={() => setShowAll((v) => !v)}
            className="rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground"
          >
            {showAll ? `Show top ${maxRows}` : `Show all ${fragments.length}`}
          </button>
        )}
      </div>
      <div className="relative overflow-x-auto">
        <svg width={width} height={height} role="img" aria-label="PFMB slot RT by fragment intensity heatmap">
          {/* apex column marker */}
          {apexCol >= 0 && (
            <text
              x={LABEL_W + apexCol * CELL_W + CELL_W / 2}
              y={10}
              textAnchor="middle"
              fontSize={9}
              fill="currentColor"
              data-testid="pfmb-heatmap-apex"
            >
              PFMB apex
            </text>
          )}
          {/* column headers (slot index), clickable to switch RT */}
          {slots.map((slot, col) => (
            <text
              key={`h-${slot.prsm_index}`}
              x={LABEL_W + col * CELL_W + CELL_W / 2}
              y={HEADER_H - 4}
              textAnchor="middle"
              fontSize={10}
              className="cursor-pointer fill-muted-foreground hover:fill-foreground"
              onClick={() => onSelectRt(slot.rt_minutes)}
            >
              {slot.slot_index}
            </text>
          ))}
          {/* rows */}
          {rows.map((row, r) => {
            const rowHighlighted = highlight?.has(row.key) ?? false;
            return (
              <g key={row.key} transform={`translate(0, ${HEADER_H + r * CELL_H})`}>
                <text
                  x={LABEL_W - 4}
                  y={CELL_H / 2}
                  textAnchor="end"
                  dominantBaseline="middle"
                  fontSize={11}
                  fontWeight={rowHighlighted ? 700 : 500}
                  style={{ fill: PFMB_SERIES_COLOR[row.ion_type] }}
                >
                  {`${seriesLabel(row.ion_type)}${row.fragment_ordinal}`}
                </text>
                {slots.map((slot, col) => {
                  const v = intensity[fragments.indexOf(row)]?.[col] ?? 0;
                  return (
                    <rect
                      key={`${row.key}-${slot.prsm_index}`}
                      data-testid="pfmb-heatmap-cell"
                      data-family={row.key}
                      data-col={col}
                      x={LABEL_W + col * CELL_W}
                      y={0}
                      width={CELL_W - 1}
                      height={CELL_H - 1}
                      fill={color(v)}
                      stroke={rowHighlighted ? "hsl(var(--primary))" : "hsl(var(--border))"}
                      strokeWidth={rowHighlighted ? 1 : 0.3}
                      className="cursor-pointer"
                      onClick={() => {
                        onSelectRt(slot.rt_minutes);
                        onHighlight(row.key);
                      }}
                      onMouseMove={(e) => {
                        const rect = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
                        setTooltip({
                          x: e.clientX - rect.left,
                          y: e.clientY - rect.top,
                          text: `${row.key} @ ${slot.rt_minutes.toFixed(2)} min: ${formatIntensity(v)}`,
                        });
                      }}
                      onMouseLeave={() => setTooltip(null)}
                    />
                  );
                })}
              </g>
            );
          })}
          {/* current slot column outline */}
          {currentCol >= 0 && (
            <rect
              data-testid="pfmb-heatmap-current-col"
              data-col={currentCol}
              x={LABEL_W + currentCol * CELL_W}
              y={HEADER_H}
              width={CELL_W - 1}
              height={rows.length * CELL_H}
              fill="none"
              stroke="hsl(var(--primary))"
              strokeWidth={1.5}
              pointerEvents="none"
            />
          )}
        </svg>
        {tooltip && (
          <div
            className="pointer-events-none absolute z-10 rounded-md border border-border bg-popover px-2 py-1 text-[11px] text-popover-foreground shadow-md"
            style={{ left: tooltip.x + 10, top: tooltip.y + 10 }}
          >
            {tooltip.text}
          </div>
        )}
      </div>
      <p className="mt-1 text-[11px] text-muted-foreground">
        Columns are RT slots (x-axis label = slot index); click a cell to jump to that RT and highlight the fragment.
      </p>
    </div>
  );
}
