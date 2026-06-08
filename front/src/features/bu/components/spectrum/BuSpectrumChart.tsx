import { useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import { Maximize2, RotateCcw } from "lucide-react";

import { cn } from "@/lib/utils";
import type { BuMatchedIon, BuSpectrumV1 } from "@/features/bu/types";
import { BU_CHART, DEFAULT_ZOOM, formatIntensity, isZoomed, type Zoom } from "@/features/bu/components/spectrum/chartTheme";

interface ChartPeak {
  mz: number;
  intensity: number;
  ion?: BuMatchedIon;
}

function ionLabel(ion: BuMatchedIon): string {
  return `${ion.ion_type}${ion.position}${ion.charge > 1 ? `^${ion.charge}+` : ""}`;
}

function colorFor(peak: ChartPeak): string {
  if (peak.ion?.ion_type === "b") return BU_CHART.b;
  if (peak.ion?.ion_type === "y") return BU_CHART.y;
  return BU_CHART.unmatched;
}

function nearestPeakIndex(peaks: ChartPeak[], expMz: number, tol = 1e-4): number | null {
  let best: number | null = null;
  let bestDelta = Infinity;
  for (let i = 0; i < peaks.length; i++) {
    const delta = Math.abs(peaks[i].mz - expMz);
    if (delta < bestDelta) {
      bestDelta = delta;
      best = i;
    }
  }
  return bestDelta <= tol ? best : null;
}

function theoreticalCount(sequence: string): number {
  return Math.max(0, sequence.length * 2 - 2);
}

export function BuSpectrumChart({
  spectrum,
  sequence,
  precursorCharge,
  precursorMz,
  ppm = 20,
  height = BU_CHART.ms2Height,
  zoom: zoomProp,
  onZoomChange,
  onMatchedIonClick,
  onOpenFull,
  className,
}: {
  spectrum: BuSpectrumV1;
  sequence: string;
  precursorCharge: number | null;
  precursorMz: number | null;
  ppm?: number;
  height?: number;
  zoom?: Zoom;
  onZoomChange?: (zoom: Zoom) => void;
  onMatchedIonClick?: (ion: BuMatchedIon) => void;
  onOpenFull?: () => void;
  className?: string;
}) {
  const markerMz = spectrum.markers?.find((marker) => marker.label === "precursor")?.mz ?? precursorMz;
  const title =
    spectrum.ms_level === 1
      ? `MS1 scan #${spectrum.scan} (RT=${spectrum.rt_minutes.toFixed(2)} min) precursor m/z ${markerMz?.toFixed(4) ?? "-"}`
      : `MS2 scan #${spectrum.scan} (RT=${spectrum.rt_minutes.toFixed(2)} min) peptide: ${sequence} +${precursorCharge ?? "?"} m/z ${precursorMz?.toFixed(3) ?? "-"}`;
  const subtitle =
    spectrum.ms_level === 1
      ? `precursor marker ${markerMz?.toFixed(4) ?? "-"}${precursorCharge ? ` · charge +${precursorCharge}` : ""}`
      : `matched ${spectrum.matched_ions.length}/${theoreticalCount(sequence)} theoretical b/y ions (±${ppm} ppm)`;
  const peaks = useMemo(() => {
    const mapped: ChartPeak[] = spectrum.mz.map((mz, index) => ({
      mz,
      intensity: spectrum.intensity[index] ?? 0,
    }));
    for (const ion of spectrum.matched_ions) {
      const idx = nearestPeakIndex(mapped, ion.exp_mz);
      if (idx !== null) mapped[idx] = { ...mapped[idx], ion };
    }
    return mapped.sort((a, b) => a.mz - b.mz);
  }, [spectrum]);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [width, setWidth] = useState(760);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; peak: ChartPeak } | null>(null);
  const [internalZoom, setInternalZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const zoom = zoomProp ?? internalZoom;
  const controlled = zoomProp !== undefined;
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;
  const onMatchedIonClickRef = useRef(onMatchedIonClick);
  onMatchedIonClickRef.current = onMatchedIonClick;
  const commitZoomRef = useRef<(zoom: Zoom) => void>(() => {});
  commitZoomRef.current = (next) => {
    onZoomChange?.(next);
    if (!controlled) setInternalZoom(next);
  };

  const fullX = useMemo<[number, number]>(() => {
    if (peaks.length === 0) return [0, 1];
    return [peaks[0].mz, peaks[peaks.length - 1].mz];
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

    const clipId = `bu-ms2-clip-${Math.random().toString(36).slice(2, 9)}`;
    svg.append("defs").append("clipPath").attr("id", clipId).append("rect").attr("width", innerW).attr("height", innerH);
    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);
    const gridG = g.append("g");
    const xAxisG = g.append("g").attr("transform", `translate(0,${innerH})`);
    const yAxisG = g.append("g");
    const plotG = g.append("g").attr("clip-path", `url(#${clipId})`);
    const linesG = plotG.append("g");
    const markersG = plotG.append("g").attr("pointer-events", "none");
    const labelsG = plotG.append("g").attr("pointer-events", "none");
    const brushG = g.append("g");

    g.append("text").attr("x", innerW / 2).attr("y", innerH + 38).attr("text-anchor", "middle").attr("fill", BU_CHART.text).attr("font-size", 12).text("m/z");
    g.append("text").attr("transform", `rotate(-90) translate(${-innerH / 2},${-52})`).attr("text-anchor", "middle").attr("fill", BU_CHART.text).attr("font-size", 12).text("Intensity");

    let xScale = d3.scaleLinear().domain(fullX).range([0, innerW]);
    let yScale = d3.scaleLinear().domain([0, 1]).range([innerH, 0]);
    let visible = peaks;
    const bisect = d3.bisector<ChartPeak, number>((p) => p.mz).left;

    const applyZoom = (nextZoom: Zoom) => {
      const [x0, x1] = nextZoom.x ?? fullX;
      xScale = d3.scaleLinear().domain([x0, x1]).range([0, innerW]);
      visible = peaks.filter((p) => p.mz >= x0 && p.mz <= x1);
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

      const y0 = yScale(0);
      linesG
        .selectAll<SVGLineElement, ChartPeak>("line")
        .data(visible)
        .join("line")
        .attr("x1", (d) => xScale(d.mz))
        .attr("x2", (d) => xScale(d.mz))
        .attr("y1", y0)
        .attr("y2", (d) => yScale(d.intensity))
        .attr("stroke", (d) => colorFor(d))
        .attr("stroke-width", (d) => (d.ion ? 1.8 : 0.7))
        .attr("opacity", (d) => (d.ion ? 1 : 0.85));

      const visibleMarkers = (spectrum.markers ?? []).filter((marker) => marker.mz >= x0 && marker.mz <= x1);
      markersG
        .selectAll<SVGLineElement, NonNullable<BuSpectrumV1["markers"]>[number]>("line")
        .data(visibleMarkers)
        .join("line")
        .attr("x1", (d) => xScale(d.mz))
        .attr("x2", (d) => xScale(d.mz))
        .attr("y1", 0)
        .attr("y2", innerH)
        .attr("stroke", BU_CHART.apex)
        .attr("stroke-width", 1.6)
        .attr("stroke-dasharray", "5,3");

      markersG
        .selectAll<SVGTextElement, NonNullable<BuSpectrumV1["markers"]>[number]>("text")
        .data(visibleMarkers)
        .join("text")
        .attr("x", (d) => xScale(d.mz) + 5)
        .attr("y", 14)
        .attr("font-size", 11)
        .attr("font-weight", 600)
        .attr("fill", BU_CHART.apex)
        .text((d) => `${d.label}${d.charge ? ` +${d.charge}` : ""}`);

      const LABEL_W = 26;
      const LABEL_H = 20;
      const LABEL_X_OFFSET = -4;
      const MAIN_FONT = 11;
      const SUB_FONT = 7.5;

      const matched = visible.filter((p) => p.ion).sort((a, b) => b.intensity - a.intensity);
      const placed: {
        peak: ChartPeak;
        px: number;
        py: number;
        x0: number;
        y0: number;
        x1: number;
        y1: number;
      }[] = [];

      for (const peak of matched) {
        const px = xScale(peak.mz);
        if (px < 0 || px > innerW) continue;
        const py = yScale(peak.intensity);
        if (py < 0 || py > innerH) continue;

        const x0 = px + LABEL_X_OFFSET;
        const x1 = x0 + LABEL_W;
        const y1 = py - 2;
        const y0 = y1 - LABEL_H;
        if (y0 < 0 || x0 < 0 || x1 > innerW) continue;

        let collides = false;
        for (const slot of placed) {
          if (!(x1 <= slot.x0 || x0 >= slot.x1 || y1 <= slot.y0 || y0 >= slot.y1)) {
            collides = true;
            break;
          }
        }
        if (collides) continue;

        placed.push({ peak, px, py, x0, y0, x1, y1 });
      }

      labelsG.selectAll("*").remove();
      for (const slot of placed) {
        const ion = slot.peak.ion!;
        const color = colorFor(slot.peak);
        const letter = ion.ion_type;

        labelsG
          .append("text")
          .attr("x", slot.px)
          .attr("y", slot.py - 5)
          .attr("text-anchor", "start")
          .attr("font-family", "Arial, Helvetica, sans-serif")
          .attr("font-size", MAIN_FONT)
          .attr("font-weight", 600)
          .attr("fill", color)
          .text(letter);

        if (ion.charge > 1) {
          labelsG
            .append("text")
            .attr("x", slot.px + MAIN_FONT * 0.7)
            .attr("y", slot.py - MAIN_FONT - 1)
            .attr("text-anchor", "start")
            .attr("font-family", "Arial, Helvetica, sans-serif")
            .attr("font-size", SUB_FONT)
            .attr("fill", color)
            .text(`${ion.charge}+`);
        }

        labelsG
          .append("text")
          .attr("x", slot.px + MAIN_FONT * 0.7)
          .attr("y", slot.py - 1)
          .attr("text-anchor", "start")
          .attr("font-family", "Arial, Helvetica, sans-serif")
          .attr("font-size", SUB_FONT)
          .attr("fill", color)
          .text(String(ion.position));
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
      if (!onMatchedIonClickRef.current || Date.now() < suppressClickUntil || event.detail > 1) return;
      const rect = svgEl.getBoundingClientRect();
      const cx = event.clientX - rect.left - margin.left;
      const cy = event.clientY - rect.top - margin.top;
      if (cx < 0 || cx > innerW || cy < 0 || cy > innerH) return;
      const matched = visible.filter((peak) => peak.ion);
      const selected = matched.sort(
        (a, b) => Math.abs(xScale(a.mz) - cx) - Math.abs(xScale(b.mz) - cx),
      )[0];
      if (!selected?.ion || Math.abs(xScale(selected.mz) - cx) > 8) return;
      const peakY = yScale(selected.intensity);
      if (cy < peakY - 8 || cy > yScale(0) + 8) return;
      clickTimer = setTimeout(() => {
        onMatchedIonClickRef.current?.(selected.ion!);
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
      const mz = xScale.invert(cx);
      const idx = bisect(visible, mz);
      const a = visible[Math.max(0, idx - 1)];
      const b = visible[Math.min(visible.length - 1, idx)];
      const peak = !a ? b : !b ? a : Math.abs(a.mz - mz) < Math.abs(b.mz - mz) ? a : b;
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
        const [y0, y1] = yScale.domain() as [number, number];
        const nextY0 = Math.max(0, vy - (vy - y0) * factor);
        const nextY1 = vy + (y1 - vy) * factor;
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
  }, [fullX, height, peaks, spectrum.markers, width]);

  useEffect(() => {
    applyZoomRef.current?.(zoom);
  }, [zoom]);

  return (
    <div ref={containerRef} className={cn("relative w-full", className)}>
      <div className="mb-2">
        <div className="text-center text-base font-medium">{title}</div>
        <div className="text-center text-sm text-muted-foreground">{subtitle}</div>
      </div>
      <svg ref={svgRef} aria-label={title} />
      <div className="absolute right-2 top-12 flex items-center gap-1">
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
          <div className="font-mono">m/z {tooltip.peak.mz.toFixed(4)}</div>
          <div className="font-mono text-muted-foreground">int {formatIntensity(tooltip.peak.intensity)}</div>
          {tooltip.peak.ion && (
            <div className="font-semibold" style={{ color: colorFor(tooltip.peak) }}>
              {ionLabel(tooltip.peak.ion)} · {tooltip.peak.ion.ppm.toFixed(2)} ppm
            </div>
          )}
        </div>
      )}
    </div>
  );
}
