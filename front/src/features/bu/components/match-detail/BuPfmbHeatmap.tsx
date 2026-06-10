import { useEffect, useId, useMemo, useRef, useState } from "react";
import * as d3 from "d3";

import type { BuMs2AnnotationMatrixOut } from "@/features/bu/types";
import { PFMB_SERIES_COLOR, seriesLabel } from "@/features/bu/components/match-detail/pfmbSeries";
import { formatIntensity } from "@/features/bu/components/spectrum/chartTheme";

const DEFAULT_MAX_ROWS = 20;
const MIN_CELL_W = 24;
const MAX_CELL_W = 52;
const CELL_H = 24;
const LABEL_W = 76;
const HEADER_H = 34;

type DetectionState = "detected" | "matched-zero" | "not-detected" | "legacy-zero";

interface HeatmapTooltip {
  x: number;
  y: number;
  ion: string;
  slotIndex: number;
  rt: number;
  intensity: number;
  normalizedLog: number | null;
  state: DetectionState;
}

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
  const [tooltip, setTooltip] = useState<HeatmapTooltip | null>(null);
  const [containerWidth, setContainerWidth] = useState(760);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const patternId = `pfmb-legacy-${useId().replace(/:/g, "")}`;
  const { slots, fragments, intensity, apex_slot } = matrix;

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.width > 120) setContainerWidth(Math.floor(entry.contentRect.width));
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const rowEntries = useMemo(
    () => fragments.map((fragment, index) => ({ fragment, index })),
    [fragments],
  );
  const rows = showAll ? rowEntries : rowEntries.slice(0, maxRows);
  const maxIntensity = useMemo(() => {
    let maximum = 0;
    for (const row of intensity) {
      for (const value of row) if (Number.isFinite(value) && value > maximum) maximum = value;
    }
    return maximum;
  }, [intensity]);
  const logMax = Math.log1p(maxIntensity);
  const hasDetected = useMemo(
    () =>
      Array.isArray(matrix.detected)
      && matrix.detected.length === fragments.length
      && matrix.detected.every((row) => row.length === slots.length),
    [fragments.length, matrix.detected, slots.length],
  );
  const apexCol = useMemo(
    () => slots.findIndex((slot) => slot.slot_index === apex_slot),
    [apex_slot, slots],
  );
  const currentCol = useMemo(() => {
    if (selectedRt == null) return apexCol;
    let best = -1;
    let bestDistance = Infinity;
    slots.forEach((slot, index) => {
      const distance = Math.abs(slot.rt_minutes - selectedRt);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = index;
      }
    });
    return best;
  }, [apexCol, selectedRt, slots]);

  if (slots.length === 0 || fragments.length === 0) {
    return (
      <p className="py-6 text-sm text-muted-foreground" data-testid="pfmb-heatmap-empty">
        No PFMB fragment matrix is available for this match.
      </p>
    );
  }

  const availableWidth = Math.max(0, containerWidth - LABEL_W);
  const cellWidth = Math.max(MIN_CELL_W, Math.min(MAX_CELL_W, availableWidth / slots.length));
  const width = Math.max(containerWidth, LABEL_W + slots.length * cellWidth);
  const height = HEADER_H + rows.length * CELL_H;

  return (
    <div ref={containerRef} className="mb-6 w-full" data-testid="pfmb-heatmap">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-xs uppercase tracking-wider text-muted-foreground">
            PFMB slot RT x fragment intensity
          </div>
          <div className="text-[11px] text-muted-foreground">Color represents log intensity.</div>
        </div>
        {fragments.length > maxRows && (
          <button
            type="button"
            data-testid="pfmb-heatmap-toggle"
            onClick={() => setShowAll((value) => !value)}
            className="rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground"
          >
            {showAll ? `Show top ${maxRows}` : `Show all ${fragments.length}`}
          </button>
        )}
      </div>

      <HeatmapLegend hasDetected={hasDetected} />

      <div className="relative overflow-x-auto rounded-md border border-border/70 bg-background">
        <svg width={width} height={height} role="img" aria-label="PFMB slot RT by fragment intensity heatmap">
          <defs>
            <pattern id={patternId} width="6" height="6" patternUnits="userSpaceOnUse">
              <rect width="6" height="6" fill="hsl(var(--muted))" />
              <path d="M0 6L6 0" stroke="hsl(var(--muted-foreground))" strokeWidth="0.6" opacity="0.5" />
            </pattern>
          </defs>

          {currentCol >= 0 && (
            <rect
              x={LABEL_W + currentCol * cellWidth}
              y={HEADER_H}
              width={cellWidth}
              height={rows.length * CELL_H}
              fill="hsl(var(--primary))"
              opacity={0.08}
              pointerEvents="none"
            />
          )}

          {apexCol >= 0 && (
            <text
              x={LABEL_W + apexCol * cellWidth + cellWidth / 2}
              y={11}
              textAnchor="middle"
              fontSize={9}
              fontWeight={600}
              fill="currentColor"
              data-testid="pfmb-heatmap-apex"
            >
              PFMB apex
            </text>
          )}

          {slots.map((slot, column) => (
            <text
              key={`header-${slot.prsm_index}`}
              x={LABEL_W + column * cellWidth + cellWidth / 2}
              y={HEADER_H - 6}
              textAnchor="middle"
              fontSize={11}
              fontWeight={column === currentCol ? 700 : 500}
              className="cursor-pointer fill-muted-foreground hover:fill-foreground"
              onClick={() => onSelectRt(slot.rt_minutes)}
            >
              {slot.slot_index}
            </text>
          ))}

          {rows.map(({ fragment, index: fragmentIndex }, rowIndex) => {
            const rowHighlighted = highlight?.has(fragment.key) ?? false;
            const rowY = HEADER_H + rowIndex * CELL_H;
            return (
              <g key={fragment.key}>
                {rowHighlighted && (
                  <rect
                    x={0}
                    y={rowY}
                    width={width}
                    height={CELL_H - 1}
                    fill="hsl(var(--primary))"
                    opacity={0.1}
                    pointerEvents="none"
                  />
                )}
                <text
                  x={LABEL_W - 8}
                  y={rowY + CELL_H / 2}
                  textAnchor="end"
                  dominantBaseline="middle"
                  fontSize={13}
                  fontWeight={rowHighlighted ? 700 : 600}
                  className="cursor-pointer"
                  style={{ fill: PFMB_SERIES_COLOR[fragment.ion_type] }}
                  onClick={() => onHighlight(fragment.key)}
                >
                  {`${seriesLabel(fragment.ion_type)}${fragment.fragment_ordinal}`}
                </text>
                {slots.map((slot, column) => {
                  const value = intensity[fragmentIndex]?.[column] ?? 0;
                  const isDetected = hasDetected ? Boolean(matrix.detected?.[fragmentIndex]?.[column]) : null;
                  const state = detectionState(value, isDetected);
                  const normalizedLog = value > 0 && logMax > 0 ? Math.log1p(value) / logMax : null;
                  return (
                    <rect
                      key={`${fragment.key}-${slot.prsm_index}`}
                      data-testid="pfmb-heatmap-cell"
                      data-family={fragment.key}
                      data-col={column}
                      data-detection={state}
                      x={LABEL_W + column * cellWidth + 1}
                      y={rowY + 1}
                      width={cellWidth - 2}
                      height={CELL_H - 2}
                      rx={2}
                      fill={cellFill(state, normalizedLog, patternId)}
                      stroke={rowHighlighted ? "hsl(var(--primary))" : "hsl(var(--border))"}
                      strokeWidth={rowHighlighted ? 2 : 0.5}
                      className="cursor-pointer"
                      onClick={() => {
                        onSelectRt(slot.rt_minutes);
                        onHighlight(fragment.key);
                      }}
                      onMouseMove={(event) => {
                        const bounds = event.currentTarget.ownerSVGElement!.getBoundingClientRect();
                        setTooltip({
                          x: event.clientX - bounds.left,
                          y: event.clientY - bounds.top,
                          ion: `${seriesLabel(fragment.ion_type)}${fragment.fragment_ordinal}`,
                          slotIndex: slot.slot_index,
                          rt: slot.rt_minutes,
                          intensity: value,
                          normalizedLog,
                          state,
                        });
                      }}
                      onMouseLeave={() => setTooltip(null)}
                    />
                  );
                })}
              </g>
            );
          })}

          {currentCol >= 0 && (
            <rect
              data-testid="pfmb-heatmap-current-col"
              data-col={currentCol}
              x={LABEL_W + currentCol * cellWidth}
              y={HEADER_H}
              width={cellWidth}
              height={rows.length * CELL_H}
              fill="none"
              stroke="hsl(var(--primary))"
              strokeWidth={2.5}
              pointerEvents="none"
            />
          )}
        </svg>

        {tooltip && (
          <HeatmapTooltip tooltip={tooltip} />
        )}
      </div>
      <p className="mt-1 text-[11px] text-muted-foreground">
        Columns are PFMB slots; click a cell to select its PFMB slot RT and highlight the fragment across PFMB views.
      </p>
    </div>
  );
}

function HeatmapLegend({ hasDetected }: { hasDetected: boolean }) {
  return (
    <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground" data-testid="pfmb-heatmap-legend">
      <span className="font-medium text-foreground">Log intensity</span>
      {[
        ["Low", d3.interpolateViridis(0.2)],
        ["Medium", d3.interpolateViridis(0.55)],
        ["High", d3.interpolateViridis(0.9)],
      ].map(([label, color]) => (
        <span key={label} className="inline-flex items-center gap-1">
          <span className="h-3 w-5 rounded-sm border border-border" style={{ backgroundColor: color }} />
          {label}
        </span>
      ))}
      {hasDetected ? (
        <>
          <span className="inline-flex items-center gap-1">
            <span className="h-3 w-5 rounded-sm border border-amber-500 bg-amber-400/40" />
            Matched zero intensity
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-3 w-5 rounded-sm border border-border bg-muted/50" />
            Not detected
          </span>
        </>
      ) : (
        <span className="inline-flex items-center gap-1">
          <span className="h-3 w-5 rounded-sm border border-dashed border-muted-foreground bg-muted" />
          Zero / not detected (legacy)
        </span>
      )}
    </div>
  );
}

function HeatmapTooltip({ tooltip }: { tooltip: HeatmapTooltip }) {
  const status = {
    detected: "Matched peak",
    "matched-zero": "Matched peak with zero intensity",
    "not-detected": "Not detected",
    "legacy-zero": "Zero / not detected (legacy response)",
  }[tooltip.state];
  return (
    <div
      className="pointer-events-none absolute z-10 min-w-44 rounded-md border border-border bg-popover px-2 py-1.5 text-[11px] text-popover-foreground shadow-md"
      style={{ left: tooltip.x + 10, top: tooltip.y + 10 }}
      data-testid="pfmb-heatmap-tooltip"
    >
      <div className="font-semibold">{tooltip.ion}</div>
      <div>Slot {tooltip.slotIndex}</div>
      <div>PFMB slot RT {tooltip.rt.toFixed(4)} min</div>
      <div>Intensity {formatIntensity(tooltip.intensity)}</div>
      <div>
        Log intensity {tooltip.normalizedLog == null ? "N/A" : tooltip.normalizedLog.toFixed(3)} normalized
      </div>
      <div className="text-muted-foreground">{status}</div>
    </div>
  );
}

function detectionState(value: number, detected: boolean | null): DetectionState {
  if (detected === true) return value > 0 ? "detected" : "matched-zero";
  if (detected === false) return "not-detected";
  return value > 0 ? "detected" : "legacy-zero";
}

function cellFill(
  state: DetectionState,
  normalizedLog: number | null,
  patternId: string,
): string {
  if (state === "matched-zero") return "rgba(245, 158, 11, 0.38)";
  if (state === "not-detected") return "hsl(var(--muted) / 0.45)";
  if (state === "legacy-zero") return `url(#${patternId})`;
  return d3.interpolateViridis(normalizedLog ?? 0);
}
