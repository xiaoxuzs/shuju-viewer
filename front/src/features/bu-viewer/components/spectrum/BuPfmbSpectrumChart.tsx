import { useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import { Maximize2, RotateCcw } from "lucide-react";

import { cn } from "@/lib/utils";
import type { BuPfmbMatchedIon } from "@/features/bu-viewer/types";
import {
  PFMB_SERIES_COLOR,
  ionFamilyKey,
  ionLabel,
  neutralToMz,
} from "@/features/bu-viewer/components/match-detail/pfmbSeries";
import { BU_CHART, DEFAULT_ZOOM, formatIntensity, isZoomed, type Zoom } from "@/features/bu-viewer/components/spectrum/chartTheme";

export type PfmbMassMode = "neutral" | "mz";

interface ChartPeak {
  x: number;
  intensity: number;
  peakId: number;
  ions: BuPfmbMatchedIon[];
  families: string[];
}

function peakMass(ion: BuPfmbMatchedIon, massMode: PfmbMassMode): number {
  return massMode === "mz"
    ? neutralToMz(ion.observed_neutral_mass, ion.charge)
    : ion.observed_neutral_mass;
}

export function BuPfmbSpectrumChart({
  ions,
  massMode,
  highlight,
  onHighlight,
  height = BU_CHART.ms2Height,
  zoom: zoomProp,
  onZoomChange,
  onOpenFull,
  className,
}: {
  ions: BuPfmbMatchedIon[];
  massMode: PfmbMassMode;
  highlight?: ReadonlySet<string>;
  onHighlight?: (familyKeys: string[]) => void;
  height?: number;
  zoom?: Zoom;
  onZoomChange?: (zoom: Zoom) => void;
  onOpenFull?: () => void;
  className?: string;
}) {
  const xLabel = massMode === "mz" ? "m/z" : "neutral mass (Da)";
  const peaks = useMemo(() => {
    const byPeak = new Map<number, BuPfmbMatchedIon[]>();
    for (const ion of ions) {
      const annotations = byPeak.get(ion.peak_id);
      if (annotations) annotations.push(ion);
      else byPeak.set(ion.peak_id, [ion]);
    }
    return [...byPeak.entries()]
      .map<ChartPeak>(([peakId, annotations]) => ({
        x: peakMass(annotations[0], massMode),
        intensity: Math.max(...annotations.map((ion) => ion.intensity)),
        peakId,
        ions: annotations,
        families: [...new Set(annotations.map(ionFamilyKey))],
      }))
      .sort((a, b) => a.x - b.x);
  }, [ions, massMode]);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [width, setWidth] = useState(760);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; peak: ChartPeak } | null>(null);
  const [internalZoom, setInternalZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const zoom = zoomProp ?? internalZoom;
  const controlled = zoomProp !== undefined;
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;
  const onHighlightRef = useRef(onHighlight);
  onHighlightRef.current = onHighlight;
  const highlightRef = useRef(highlight);
  highlightRef.current = highlight;
  const commitZoomRef = useRef<(zoom: Zoom) => void>(() => {});
  commitZoomRef.current = (next) => {
    onZoomChange?.(next);
    if (!controlled) setInternalZoom(next);
  };

  const fullX = useMemo<[number, number]>(() => {
    if (peaks.length === 0) return [0, 1];
    const lo = peaks[0].x;
    const hi = peaks[peaks.length - 1].x;
    const pad = Math.max(1, (hi - lo) * 0.02);
    return [lo - pad, hi + pad];
  }, [peaks]);

  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.width > 120) setWidth(Math.floor(entry.contentRect.width));
      }
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!controlled) setInternalZoom(DEFAULT_ZOOM);
  }, [peaks, controlled]);

  const applyZoomRef = useRef<((zoom: Zoom) => void) | null>(null);

  useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    const svg = d3.select(svgEl);
    svg.selectAll("*").remove();
    if (peaks.length === 0) {
      applyZoomRef.current = null;
      return;
    }

    const margin = BU_CHART.margin;
    const innerW = Math.max(80, width - margin.left - margin.right);
    const innerH = Math.max(80, height - margin.top - margin.bottom);
    svg.attr("viewBox", `0 0 ${width} ${height}`).attr("width", width).attr("height", height);

    const clipId = `bu-pfmb-clip-${Math.random().toString(36).slice(2, 9)}`;
    svg.append("defs").append("clipPath").attr("id", clipId).append("rect").attr("width", innerW).attr("height", innerH);
    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);
    const gridG = g.append("g");
    const xAxisG = g.append("g").attr("transform", `translate(0,${innerH})`);
    const yAxisG = g.append("g");
    const plotG = g.append("g").attr("clip-path", `url(#${clipId})`);
    const linesG = plotG.append("g");
    const labelsG = plotG.append("g").attr("pointer-events", "none");
    const brushG = g.append("g");

    g.append("text").attr("x", innerW / 2).attr("y", innerH + 38).attr("text-anchor", "middle").attr("fill", BU_CHART.text).attr("font-size", 12).text(xLabel);
    g.append("text").attr("transform", `rotate(-90) translate(${-innerH / 2},${-52})`).attr("text-anchor", "middle").attr("fill", BU_CHART.text).attr("font-size", 12).text("Intensity");

    let xScale = d3.scaleLinear().domain(fullX).range([0, innerW]);
    let yScale = d3.scaleLinear().domain([0, 1]).range([innerH, 0]);
    let visible = peaks;
    const bisect = d3.bisector<ChartPeak, number>((p) => p.x).left;

    const applyZoom = (nextZoom: Zoom) => {
      const [x0, x1] = nextZoom.x ?? fullX;
      xScale = d3.scaleLinear().domain([x0, x1]).range([0, innerW]);
      visible = peaks.filter((p) => p.x >= x0 && p.x <= x1);
      const yMax = Math.max(...visible.map((p) => p.intensity), 1);
      yScale = d3.scaleLinear().domain(nextZoom.y ?? [0, yMax]).range([innerH, 0]);

      xAxisG.call(d3.axisBottom(xScale).ticks(Math.max(5, Math.floor(innerW / 100))) as any).call((sel) => {
        sel.selectAll("text").attr("fill", BU_CHART.text).attr("font-size", 11);
        sel.selectAll("line, path").attr("stroke", BU_CHART.axis);
      });
      yAxisG.call(d3.axisLeft(yScale).ticks(5).tickFormat((d) => formatIntensity(Number(d))) as any).call((sel) => {
        sel.selectAll("text").attr("fill", BU_CHART.text).attr("font-size", 11);
        sel.selectAll("line, path").attr("stroke", BU_CHART.axis);
      });
      gridG.call(d3.axisLeft(yScale).tickSize(-innerW).tickFormat(() => "") as any).call((sel) => {
        sel.selectAll("line").attr("stroke", BU_CHART.grid).attr("stroke-dasharray", "2,3").attr("opacity", 0.7);
        sel.selectAll(".domain").remove();
      });

      const hl = highlightRef.current;
      const y0 = yScale(0);
      linesG
        .selectAll<SVGLineElement, ChartPeak>("line")
        .data(visible)
        .join("line")
        .attr("data-testid", "pfmb-spectrum-peak")
        .attr("data-family", (d) => d.families[0])
        .attr("data-families", (d) => d.families.join(","))
        .attr("data-peak-id", (d) => d.peakId)
        .attr("x1", (d) => xScale(d.x))
        .attr("x2", (d) => xScale(d.x))
        .attr("y1", y0)
        .attr("y2", (d) => yScale(d.intensity))
        .attr("stroke", (d) => PFMB_SERIES_COLOR[d.ions[0].ion_type])
        .attr("stroke-width", (d) => (d.families.some((family) => hl?.has(family)) ? 3 : 1.6))
        .attr("opacity", (d) => (!hl || hl.size === 0 || d.families.some((family) => hl.has(family)) ? 1 : 0.3));

      const LABEL_H = 18;
      const matched = [...visible].sort((a, b) => b.intensity - a.intensity);
      const placed: { x0: number; y0: number; x1: number; y1: number }[] = [];
      labelsG.selectAll("*").remove();
      for (const peak of matched) {
        const px = xScale(peak.x);
        const py = yScale(peak.intensity);
        if (px < 0 || px > innerW || py < 0 || py > innerH) continue;
        const x0 = px - 12;
        const x1 = px + 12;
        const y1 = py - 2;
        const y0b = y1 - LABEL_H;
        if (y0b < 0) continue;
        let collides = false;
        for (const slot of placed) {
          if (!(x1 <= slot.x0 || x0 >= slot.x1 || y1 <= slot.y0 || y0b >= slot.y1)) {
            collides = true;
            break;
          }
        }
        if (collides) continue;
        placed.push({ x0, y0: y0b, x1, y1 });
        labelsG
          .append("text")
          .attr("x", px)
          .attr("y", py - 4)
          .attr("text-anchor", "middle")
          .attr("font-family", "Arial, Helvetica, sans-serif")
          .attr("font-size", 11)
          .attr("font-weight", 600)
          .attr("fill", PFMB_SERIES_COLOR[peak.ions[0].ion_type])
          .text(peak.ions.map(ionLabel).join("/"));
      }
    };
    applyZoomRef.current = applyZoom;

    let suppressClickUntil = 0;
    let clickTimer: ReturnType<typeof setTimeout> | null = null;
    const brush = d3
      .brushX()
      .extent([[0, 0], [innerW, innerH]])
      .on("end", (event) => {
        if (!event.selection) return;
        const [a, b] = event.selection as [number, number];
        brushG.call(brush.move as any, null);
        if (Math.abs(b - a) < 4) return;
        suppressClickUntil = Date.now() + 250;
        commitZoomRef.current({ x: [xScale.invert(a), xScale.invert(b)], y: zoomRef.current.y });
      });
    brushG.call(brush as any);

    const onDblClick = (event: MouseEvent) => {
      if (clickTimer) {
        clearTimeout(clickTimer);
        clickTimer = null;
      }
      const rect = svgEl.getBoundingClientRect();
      const cx = event.clientX - rect.left - margin.left;
      const cy = event.clientY - rect.top - margin.top;
      if (cx >= 0 && cx <= innerW && cy >= 0 && cy <= innerH) commitZoomRef.current(DEFAULT_ZOOM);
    };
    const onClick = (event: MouseEvent) => {
      if (!onHighlightRef.current || Date.now() < suppressClickUntil || event.detail > 1) return;
      const rect = svgEl.getBoundingClientRect();
      const cx = event.clientX - rect.left - margin.left;
      const cy = event.clientY - rect.top - margin.top;
      if (cx < 0 || cx > innerW || cy < 0 || cy > innerH || visible.length === 0) return;
      const selected = [...visible].sort(
        (a, b) => Math.abs(xScale(a.x) - cx) - Math.abs(xScale(b.x) - cx),
      )[0];
      if (!selected || Math.abs(xScale(selected.x) - cx) > 10) return;
      clickTimer = setTimeout(() => {
        onHighlightRef.current?.(selected.families);
        clickTimer = null;
      }, 180);
    };
    const onMove = (event: MouseEvent) => {
      const rect = svgEl.getBoundingClientRect();
      const cx = event.clientX - rect.left - margin.left;
      const cy = event.clientY - rect.top - margin.top;
      if (cx < 0 || cx > innerW || cy < 0 || cy > innerH || visible.length === 0) {
        setTooltip(null);
        return;
      }
      const value = xScale.invert(cx);
      const idx = bisect(visible, value);
      const a = visible[Math.max(0, idx - 1)];
      const b = visible[Math.min(visible.length - 1, idx)];
      const peak = !a ? b : !b ? a : Math.abs(a.x - value) < Math.abs(b.x - value) ? a : b;
      if (peak) setTooltip({ x: cx + margin.left, y: cy + margin.top, peak });
    };
    const onLeave = () => setTooltip(null);
    const onWheel = (event: WheelEvent) => {
      const rect = svgEl.getBoundingClientRect();
      const cx = event.clientX - rect.left - margin.left;
      const cy = event.clientY - rect.top - margin.top;
      const onYAxis = cx < 0 && cx > -margin.left && cy >= 0 && cy <= innerH;
      const inPlot = cx >= 0 && cx <= innerW && cy >= 0 && cy <= innerH;
      if (!onYAxis && !inPlot) return;
      event.preventDefault();
      const factor = Math.pow(1.35, event.deltaY / 100);
      const current = zoomRef.current;
      if (onYAxis || event.shiftKey) {
        const vy = yScale.invert(Math.max(0, Math.min(innerH, cy)));
        const [yy0, yy1] = yScale.domain() as [number, number];
        const nextY0 = Math.max(0, vy - (vy - yy0) * factor);
        const nextY1 = vy + (yy1 - vy) * factor;
        if (nextY1 - nextY0 > 1e-6) commitZoomRef.current({ x: current.x, y: [nextY0, nextY1] });
        return;
      }
      const vx = xScale.invert(Math.max(0, Math.min(innerW, cx)));
      const [curX0, curX1] = xScale.domain() as [number, number];
      let nextX0 = vx - (vx - curX0) * factor;
      let nextX1 = vx + (curX1 - vx) * factor;
      if (nextX0 < fullX[0]) nextX0 = fullX[0];
      if (nextX1 > fullX[1]) nextX1 = fullX[1];
      if (nextX1 - nextX0 > 1e-6) {
        commitZoomRef.current({ x: nextX0 === fullX[0] && nextX1 === fullX[1] ? null : [nextX0, nextX1], y: current.y });
      }
    };
    svgEl.addEventListener("dblclick", onDblClick);
    svgEl.addEventListener("click", onClick);
    svgEl.addEventListener("mousemove", onMove);
    svgEl.addEventListener("mouseleave", onLeave);
    svgEl.addEventListener("wheel", onWheel, { passive: false });
    applyZoom(zoomRef.current);
    return () => {
      svgEl.removeEventListener("dblclick", onDblClick);
      svgEl.removeEventListener("click", onClick);
      svgEl.removeEventListener("mousemove", onMove);
      svgEl.removeEventListener("mouseleave", onLeave);
      svgEl.removeEventListener("wheel", onWheel);
      if (clickTimer) clearTimeout(clickTimer);
      applyZoomRef.current = null;
    };
  }, [fullX, height, peaks, width, xLabel]);

  useEffect(() => {
    applyZoomRef.current?.(zoom);
  }, [zoom, highlight]);

  if (peaks.length === 0) {
    return (
      <div className={cn("py-6 text-center text-sm text-muted-foreground", className)} data-testid="pfmb-spectrum-empty">
        No Fragment Match peaks to plot for this slot.
      </div>
    );
  }

  return (
    <div ref={containerRef} className={cn("relative w-full", className)}>
      <svg ref={svgRef} aria-label={`Pre-computed Fragment Match annotation spectrum (${xLabel})`} />
      <div className="absolute right-2 top-1 flex items-center gap-1">
        <button
          type="button"
          onClick={() => commitZoomRef.current(DEFAULT_ZOOM)}
          disabled={!isZoomed(zoom)}
          className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-0.5 text-[11px] text-muted-foreground shadow-sm transition-colors enabled:hover:text-foreground disabled:opacity-40"
        >
          <RotateCcw className="h-3 w-3" />
          reset
        </button>
        {onOpenFull && (
          <button
            type="button"
            onClick={onOpenFull}
            className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-0.5 text-[11px] text-muted-foreground shadow-sm hover:text-foreground"
          >
            <Maximize2 className="h-3 w-3" />
            enlarge
          </button>
        )}
      </div>
      {tooltip && (
        <div
          className="pointer-events-none absolute z-10 rounded-md border border-border bg-popover px-2 py-1 text-[11px] text-popover-foreground shadow-md"
          style={{ left: tooltip.x + 8, top: Math.max(0, tooltip.y + 16) }}
        >
          <div className="font-semibold" style={{ color: PFMB_SERIES_COLOR[tooltip.peak.ions[0].ion_type] }}>
            {tooltip.peak.ions.map(ionLabel).join(" / ")}
          </div>
          <div className="font-mono text-muted-foreground">peak #{tooltip.peak.peakId}</div>
          <div className="font-mono">{xLabel} {tooltip.peak.x.toFixed(4)}</div>
          <div className="font-mono text-muted-foreground">int {formatIntensity(tooltip.peak.intensity)}</div>
          {tooltip.peak.ions.map((ion, index) => (
            <div key={`${ionFamilyKey(ion)}-${ion.charge}-${index}`} className="font-mono text-muted-foreground">
              {ionLabel(ion)} {ion.mass_error_ppm.toFixed(2)} ppm
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
