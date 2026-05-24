import { useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import { Maximize2, RotateCcw } from "lucide-react";

import { cn } from "@/lib/utils";
import { BU_CHART, DEFAULT_ZOOM, formatIntensity, isZoomed, type Zoom } from "@/features/bu/components/spectrum/chartTheme";

export interface BuPlotPoint {
  x: number;
  y: number;
}

export interface BuPlotBand {
  start: number;
  stop: number;
  color: string;
  opacity: number;
  label?: string;
}

export interface BuPlotGuide {
  x: number;
  color: string;
  label?: string;
  dashed?: boolean;
}

export function BuInteractivePlot({
  points,
  xLabel,
  yLabel,
  lineColor,
  fillColor = lineColor,
  fillOpacity = 0.25,
  height,
  bands = [],
  guides = [],
  legend = [],
  emptyHint = "No points",
  zoom: zoomProp,
  onZoomChange,
  onOpenFull,
  className,
}: {
  points: BuPlotPoint[];
  xLabel: string;
  yLabel: string;
  lineColor: string;
  fillColor?: string;
  fillOpacity?: number;
  height: number;
  bands?: BuPlotBand[];
  guides?: BuPlotGuide[];
  legend?: { label: string; color: string; kind: "line" | "band" }[];
  emptyHint?: string;
  zoom?: Zoom;
  onZoomChange?: (zoom: Zoom) => void;
  onOpenFull?: () => void;
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [width, setWidth] = useState(720);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; point: BuPlotPoint } | null>(null);
  const [internalZoom, setInternalZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const zoom = zoomProp ?? internalZoom;
  const controlled = zoomProp !== undefined;
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;

  const commitZoomRef = useRef<(zoom: Zoom) => void>(() => {});
  commitZoomRef.current = (next) => {
    onZoomChange?.(next);
    if (!controlled) setInternalZoom(next);
  };

  const sorted = useMemo(
    () => [...points].filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y)).sort((a, b) => a.x - b.x),
    [points],
  );
  const fullX = useMemo<[number, number]>(() => {
    if (sorted.length === 0) return [0, 1];
    const first = sorted[0].x;
    const last = sorted[sorted.length - 1].x;
    return first === last ? [first, first + 1] : [first, last];
  }, [sorted]);

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
  }, [sorted, controlled]);

  const applyZoomRef = useRef<((zoom: Zoom) => void) | null>(null);

  useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    const svg = d3.select(svgEl);
    svg.selectAll("*").remove();
    if (sorted.length === 0) {
      applyZoomRef.current = null;
      return;
    }

    const margin = BU_CHART.margin;
    const innerW = Math.max(80, width - margin.left - margin.right);
    const innerH = Math.max(80, height - margin.top - margin.bottom);
    svg.attr("viewBox", `0 0 ${width} ${height}`).attr("width", width).attr("height", height);

    const clipId = `bu-line-clip-${Math.random().toString(36).slice(2, 9)}`;
    svg.append("defs").append("clipPath").attr("id", clipId).append("rect").attr("width", innerW).attr("height", innerH);

    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);
    const gridG = g.append("g");
    const xAxisG = g.append("g").attr("transform", `translate(0,${innerH})`);
    const yAxisG = g.append("g");
    const plotG = g.append("g").attr("clip-path", `url(#${clipId})`);
    const bandG = plotG.append("g");
    const areaPath = plotG.append("path").attr("fill", fillColor).attr("opacity", fillOpacity);
    const linePath = plotG.append("path").attr("fill", "none").attr("stroke", lineColor).attr("stroke-width", 1.4);
    const guideG = plotG.append("g");
    const brushG = g.append("g");

    g.append("text")
      .attr("x", innerW / 2)
      .attr("y", innerH + 38)
      .attr("text-anchor", "middle")
      .attr("fill", BU_CHART.text)
      .attr("font-size", 12)
      .text(xLabel);
    g.append("text")
      .attr("transform", `rotate(-90) translate(${-innerH / 2},${-52})`)
      .attr("text-anchor", "middle")
      .attr("fill", BU_CHART.text)
      .attr("font-size", 12)
      .text(yLabel);

    let xScale = d3.scaleLinear().domain(fullX).range([0, innerW]);
    let yScale = d3.scaleLinear().domain([0, 1]).range([innerH, 0]);
    let visible = sorted;
    const bisect = d3.bisector<BuPlotPoint, number>((p) => p.x).left;

    const applyZoom = (nextZoom: Zoom) => {
      const [x0, x1] = nextZoom.x ?? fullX;
      xScale = d3.scaleLinear().domain([x0, x1]).range([0, innerW]);
      visible = sorted.filter((p) => p.x >= x0 && p.x <= x1);
      const autoMax = Math.max(...visible.map((p) => p.y), 1);
      yScale = d3.scaleLinear().domain(nextZoom.y ?? [0, autoMax]).range([innerH, 0]);

      xAxisG
        .call(d3.axisBottom(xScale).ticks(Math.max(5, Math.floor(innerW / 95))) as any)
        .call((sel) => {
          sel.selectAll("text").attr("fill", BU_CHART.text).attr("font-size", 11);
          sel.selectAll("line, path").attr("stroke", BU_CHART.axis);
        });
      yAxisG
        .call(d3.axisLeft(yScale).ticks(5).tickFormat((d) => formatIntensity(Number(d))) as any)
        .call((sel) => {
          sel.selectAll("text").attr("fill", BU_CHART.text).attr("font-size", 11);
          sel.selectAll("line, path").attr("stroke", BU_CHART.axis);
        });
      gridG
        .call(d3.axisLeft(yScale).tickSize(-innerW).tickFormat(() => "") as any)
        .call((sel) => {
          sel.selectAll("line").attr("stroke", BU_CHART.grid).attr("stroke-dasharray", "2,3").attr("opacity", 0.7);
          sel.selectAll(".domain").remove();
        });

      const line = d3.line<BuPlotPoint>().x((d) => xScale(d.x)).y((d) => yScale(d.y));
      const area = d3.area<BuPlotPoint>().x((d) => xScale(d.x)).y0(innerH).y1((d) => yScale(d.y));
      linePath.datum(sorted).attr("d", line as any);
      areaPath.datum(sorted).attr("d", area as any);

      bandG
        .selectAll<SVGRectElement, BuPlotBand>("rect")
        .data(bands)
        .join("rect")
        .attr("x", (d) => xScale(d.start))
        .attr("width", (d) => Math.max(0, xScale(d.stop) - xScale(d.start)))
        .attr("y", 0)
        .attr("height", innerH)
        .attr("fill", (d) => d.color)
        .attr("opacity", (d) => d.opacity);

      guideG
        .selectAll<SVGLineElement, BuPlotGuide>("line")
        .data(guides)
        .join("line")
        .attr("x1", (d) => xScale(d.x))
        .attr("x2", (d) => xScale(d.x))
        .attr("y1", 0)
        .attr("y2", innerH)
        .attr("stroke", (d) => d.color)
        .attr("stroke-width", 1.5)
        .attr("stroke-dasharray", (d) => (d.dashed ? "5,3" : null));
    };
    applyZoomRef.current = applyZoom;

    const brush = d3
      .brushX()
      .extent([[0, 0], [innerW, innerH]])
      .on("end", (event) => {
        if (!event.selection) return;
        const [a, b] = event.selection as [number, number];
        brushG.call(brush.move as any, null);
        if (Math.abs(b - a) < 4) return;
        commitZoomRef.current({ x: [xScale.invert(a), xScale.invert(b)], y: zoomRef.current.y });
      });
    brushG.call(brush as any);

    const onDblClick = (event: MouseEvent) => {
      const rect = svgEl.getBoundingClientRect();
      const cx = event.clientX - rect.left - margin.left;
      const cy = event.clientY - rect.top - margin.top;
      if (cx >= 0 && cx <= innerW && cy >= 0 && cy <= innerH) commitZoomRef.current(DEFAULT_ZOOM);
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
      const point = !a ? b : !b ? a : Math.abs(a.x - value) < Math.abs(b.x - value) ? a : b;
      if (point) setTooltip({ x: cx + margin.left, y: cy + margin.top, point });
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
        commitZoomRef.current({
          x: nextX0 === fullX[0] && nextX1 === fullX[1] ? null : [nextX0, nextX1],
          y: current.y,
        });
      }
    };
    svgEl.addEventListener("dblclick", onDblClick);
    svgEl.addEventListener("mousemove", onMove);
    svgEl.addEventListener("mouseleave", onLeave);
    svgEl.addEventListener("wheel", onWheel, { passive: false });

    applyZoom(zoomRef.current);

    return () => {
      svgEl.removeEventListener("dblclick", onDblClick);
      svgEl.removeEventListener("mousemove", onMove);
      svgEl.removeEventListener("mouseleave", onLeave);
      svgEl.removeEventListener("wheel", onWheel);
      applyZoomRef.current = null;
    };
  }, [bands, fillColor, fillOpacity, fullX, guides, height, lineColor, sorted, width, xLabel, yLabel]);

  useEffect(() => {
    applyZoomRef.current?.(zoom);
  }, [zoom]);

  return (
    <div ref={containerRef} className={cn("relative w-full", className)}>
      {sorted.length === 0 ? (
        <div className="flex items-center justify-center text-sm text-muted-foreground" style={{ height }}>
          {emptyHint}
        </div>
      ) : (
        <>
          <svg ref={svgRef} />
          <div className="absolute right-2 top-2 flex items-center gap-1">
            <button
              type="button"
              onClick={() => commitZoomRef.current(DEFAULT_ZOOM)}
              disabled={!isZoomed(zoom)}
              className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-0.5 text-[11px] text-muted-foreground shadow-sm transition-colors enabled:hover:text-foreground disabled:opacity-40"
              title="reset zoom (dbl-click plot)"
            >
              <RotateCcw className="h-3 w-3" />
              reset
            </button>
            {onOpenFull && (
              <button
                type="button"
                onClick={onOpenFull}
                className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-0.5 text-[11px] text-muted-foreground shadow-sm hover:text-foreground"
                title="view large"
              >
                <Maximize2 className="h-3 w-3" />
                enlarge
              </button>
            )}
          </div>
          {legend.length > 0 && (
            <div className="absolute right-3 top-10 rounded-md border border-border bg-card/90 px-2 py-1 text-[11px] text-muted-foreground shadow-sm">
              {legend.map((item) => (
                <div key={item.label} className="flex items-center gap-1.5">
                  <span
                    className={cn("inline-block h-2 w-4", item.kind === "line" ? "border-t-2 border-dashed" : "")}
                    style={{ background: item.kind === "band" ? item.color : "transparent", borderColor: item.color }}
                  />
                  {item.label}
                </div>
              ))}
            </div>
          )}
          {tooltip && (
            <div
              className="pointer-events-none absolute z-10 rounded-md border border-border bg-popover px-2 py-1 text-[11px] text-popover-foreground shadow-md"
              style={{ left: tooltip.x + 8, top: Math.max(0, tooltip.y - 8) }}
            >
              <div className="font-mono">{xLabel}: {tooltip.point.x.toFixed(4)}</div>
              <div className="font-mono text-muted-foreground">{yLabel}: {formatIntensity(tooltip.point.y)}</div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
