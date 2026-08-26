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

export type BuPlotReferenceYMax = number | "visible-max";

export interface BuPlotSeries {
  label: string;
  points: BuPlotPoint[];
  color: string;
  fill?: boolean;
  fillColor?: string;
  fillOpacity?: number;
}

export interface BuPlotPointClick {
  point: BuPlotPoint;
  seriesLabel: string;
}

export interface BuPlotAxisScale {
  divisor: number;
  label: string;
}

function sortedPoints(points: BuPlotPoint[]): BuPlotPoint[] {
  return [...points].filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y)).sort((a, b) => a.x - b.x);
}

function nearestPoint(points: BuPlotPoint[], value: number): BuPlotPoint | null {
  if (points.length === 0) return null;
  const bisect = d3.bisector<BuPlotPoint, number>((p) => p.x).left;
  const idx = bisect(points, value);
  const a = points[Math.max(0, idx - 1)];
  const b = points[Math.min(points.length - 1, idx)];
  return !a ? b : !b ? a : Math.abs(a.x - value) < Math.abs(b.x - value) ? a : b;
}

function formatYAxisTick(value: number, axisScale?: BuPlotAxisScale): string {
  if (!axisScale) return formatIntensity(value);
  const scaled = value / axisScale.divisor;
  if (!Number.isFinite(scaled)) return "-";
  if (Math.abs(scaled) < 1e-9) return "0";
  return scaled.toFixed(1);
}

export function BuInteractivePlot({
  points,
  series,
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
  yDomain,
  yTicks,
  yAxisScale,
  referenceYMax,
  zoom: zoomProp,
  onZoomChange,
  onPointClick,
  onOpenFull,
  onFirstRender,
  className,
}: {
  points: BuPlotPoint[];
  series?: BuPlotSeries[];
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
  yDomain?: [number, number] | ((visibleMax: number) => [number, number]);
  yTicks?: number[];
  yAxisScale?: BuPlotAxisScale;
  referenceYMax?: BuPlotReferenceYMax;
  zoom?: Zoom;
  onZoomChange?: (zoom: Zoom) => void;
  onPointClick?: (selection: BuPlotPointClick) => void;
  onOpenFull?: () => void;
  onFirstRender?: () => void;
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [width, setWidth] = useState(720);
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    point: BuPlotPoint;
    values: { label: string; color: string; y: number }[];
  } | null>(null);
  const [internalZoom, setInternalZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const zoom = zoomProp ?? internalZoom;
  const controlled = zoomProp !== undefined;
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;
  const onPointClickRef = useRef(onPointClick);
  onPointClickRef.current = onPointClick;
  const onFirstRenderRef = useRef(onFirstRender);
  onFirstRenderRef.current = onFirstRender;

  const commitZoomRef = useRef<(zoom: Zoom) => void>(() => {});
  commitZoomRef.current = (next) => {
    onZoomChange?.(next);
    if (!controlled) setInternalZoom(next);
  };

  const normalizedSeries = useMemo(() => {
    if (series?.length) {
      return series
        .map((item) => ({
          ...item,
          fill: item.fill ?? false,
          fillColor: item.fillColor ?? item.color,
          fillOpacity: item.fillOpacity ?? 0.25,
          points: sortedPoints(item.points),
        }))
        .filter((item) => item.points.length > 0);
    }
    const single = sortedPoints(points);
    return single.length > 0
      ? [{ label: "", points: single, color: lineColor, fill: true, fillColor, fillOpacity }]
      : [];
  }, [fillColor, fillOpacity, lineColor, points, series]);
  const allPoints = useMemo(
    () => normalizedSeries.flatMap((item) => item.points).sort((a, b) => a.x - b.x),
    [normalizedSeries],
  );
  const fullX = useMemo<[number, number]>(() => {
    if (allPoints.length === 0) return [0, 1];
    const first = allPoints[0].x;
    const last = allPoints[allPoints.length - 1].x;
    return first === last ? [first, first + 1] : [first, last];
  }, [allPoints]);

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
  }, [normalizedSeries, controlled]);

  const applyZoomRef = useRef<((zoom: Zoom) => void) | null>(null);

  useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    const svg = d3.select(svgEl);
    svg.selectAll("*").remove();
    if (normalizedSeries.length === 0) {
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
    const areaG = plotG.append("g");
    const lineG = plotG.append("g");
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
    if (yAxisScale) {
      g.append("text")
        .attr("data-testid", "y-axis-scale-label")
        .attr("x", -12)
        .attr("y", -8)
        .attr("text-anchor", "end")
        .attr("fill", BU_CHART.text)
        .attr("font-size", 11)
        .text(yAxisScale.label);
    }

    let xScale = d3.scaleLinear().domain(fullX).range([0, innerW]);
    let yScale = d3.scaleLinear().domain([0, 1]).range([innerH, 0]);
    let visible = normalizedSeries[0]?.points ?? [];

    const applyZoom = (nextZoom: Zoom) => {
      const [x0, x1] = nextZoom.x ?? fullX;
      xScale = d3.scaleLinear().domain([x0, x1]).range([0, innerW]);
      visible = (normalizedSeries[0]?.points ?? []).filter((p) => p.x >= x0 && p.x <= x1);
      const visibleValues = normalizedSeries.flatMap((item) => item.points.filter((p) => p.x >= x0 && p.x <= x1));
      const autoMax = Math.max(...visibleValues.map((p) => p.y), 1);
      const resolvedYDomain =
        typeof yDomain === "function"
          ? yDomain(autoMax)
          : yDomain;
      yScale = d3.scaleLinear().domain(nextZoom.y ?? resolvedYDomain ?? [0, autoMax]).range([innerH, 0]);
      const resolvedReferenceYMax =
        referenceYMax === "visible-max"
          ? autoMax
          : referenceYMax;
      const referenceTop =
        resolvedReferenceYMax === undefined
          ? 0
          : Math.max(0, Math.min(innerH, yScale(resolvedReferenceYMax)));

      xAxisG
        .call(d3.axisBottom(xScale).ticks(Math.max(5, Math.floor(innerW / 95))) as any)
        .call((sel) => {
          sel.selectAll("text").attr("fill", BU_CHART.text).attr("font-size", 11);
          sel.selectAll("line, path").attr("stroke", BU_CHART.axis);
        });
      const [y0, y1] = yScale.domain() as [number, number];
      const visibleYTicks = yTicks?.filter((tick) => tick >= y0 && tick <= y1);
      const yAxis = d3.axisLeft(yScale).tickFormat((d) => formatYAxisTick(Number(d), yAxisScale));
      if (visibleYTicks) yAxis.tickValues(visibleYTicks);
      else yAxis.ticks(5);
      yAxisG
        .call(yAxis as any)
        .call((sel) => {
          sel.selectAll("text").attr("fill", BU_CHART.text).attr("font-size", 11);
          sel.selectAll("line, path").attr("stroke", BU_CHART.axis);
        });
      const yGrid = d3.axisLeft(yScale).tickSize(-innerW).tickFormat(() => "");
      if (visibleYTicks) yGrid.tickValues(visibleYTicks);
      gridG
        .call(yGrid as any)
        .call((sel) => {
          sel.selectAll("line").attr("stroke", BU_CHART.grid).attr("stroke-dasharray", "2,3").attr("opacity", 0.7);
          sel.selectAll(".domain").remove();
        });

      const line = d3.line<BuPlotPoint>().x((d) => xScale(d.x)).y((d) => yScale(d.y));
      const area = d3.area<BuPlotPoint>().x((d) => xScale(d.x)).y0(innerH).y1((d) => yScale(d.y));
      areaG
        .selectAll<SVGPathElement, (typeof normalizedSeries)[number]>("path")
        .data(normalizedSeries.filter((item) => item.fill))
        .join("path")
        .attr("fill", (d) => d.fillColor)
        .attr("opacity", (d) => d.fillOpacity)
        .attr("d", (d) => area(d.points));
      lineG
        .selectAll<SVGPathElement, (typeof normalizedSeries)[number]>("path")
        .data(normalizedSeries)
        .join("path")
        .attr("data-testid", "plot-series")
        .attr("data-series-label", (d) => d.label)
        .attr("fill", "none")
        .attr("stroke", (d) => d.color)
        .attr("stroke-width", (d) => (d.fill ? 1.5 : 1.35))
        .attr("d", (d) => line(d.points));

      bandG
        .selectAll<SVGRectElement, BuPlotBand>("rect")
        .data(bands)
        .join("rect")
        .attr("x", (d) => xScale(d.start))
        .attr("width", (d) => Math.max(0, xScale(d.stop) - xScale(d.start)))
        .attr("y", referenceTop)
        .attr("height", innerH - referenceTop)
        .attr("fill", (d) => d.color)
        .attr("opacity", (d) => d.opacity);

      guideG
        .selectAll<SVGLineElement, BuPlotGuide>("line")
        .data(guides)
        .join("line")
        .attr("x1", (d) => xScale(d.x))
        .attr("x2", (d) => xScale(d.x))
        .attr("y1", referenceTop)
        .attr("y2", innerH)
        .attr("stroke", (d) => d.color)
        .attr("stroke-width", 1.5)
        .attr("stroke-dasharray", (d) => (d.dashed ? "5,3" : null));
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
      if (!onPointClickRef.current || Date.now() < suppressClickUntil || event.detail > 1) return;
      const rect = svgEl.getBoundingClientRect();
      const cx = event.clientX - rect.left - margin.left;
      const cy = event.clientY - rect.top - margin.top;
      if (cx < 0 || cx > innerW || cy < 0 || cy > innerH || visible.length === 0) return;
      const anchor = nearestPoint(visible, xScale.invert(cx));
      if (!anchor) return;
      const candidates = normalizedSeries
        .map((item) => ({ item, point: nearestPoint(item.points, anchor.x) }))
        .filter((candidate): candidate is { item: (typeof normalizedSeries)[number]; point: BuPlotPoint } => {
          return candidate.point !== null && candidate.point.x >= xScale.domain()[0] && candidate.point.x <= xScale.domain()[1];
        });
      const selected = candidates.sort(
        (a, b) => Math.abs(yScale(a.point.y) - cy) - Math.abs(yScale(b.point.y) - cy),
      )[0];
      if (!selected) return;
      clickTimer = setTimeout(() => {
        onPointClickRef.current?.({ point: selected.point, seriesLabel: selected.item.label });
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
      const point = nearestPoint(visible, value);
      if (point) {
        setTooltip({
          x: cx + margin.left,
          y: cy + margin.top,
          point,
          values: normalizedSeries.map((item) => {
            const seriesPoint = nearestPoint(item.points, point.x);
            return { label: item.label, color: item.color, y: seriesPoint?.y ?? 0 };
          }),
        });
      }
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
    svgEl.addEventListener("click", onClick);
    svgEl.addEventListener("mousemove", onMove);
    svgEl.addEventListener("mouseleave", onLeave);
    svgEl.addEventListener("wheel", onWheel, { passive: false });

    applyZoom(zoomRef.current);
    onFirstRenderRef.current?.();

    return () => {
      svgEl.removeEventListener("dblclick", onDblClick);
      svgEl.removeEventListener("click", onClick);
      svgEl.removeEventListener("mousemove", onMove);
      svgEl.removeEventListener("mouseleave", onLeave);
      svgEl.removeEventListener("wheel", onWheel);
      if (clickTimer) clearTimeout(clickTimer);
      applyZoomRef.current = null;
    };
  }, [bands, fullX, guides, height, normalizedSeries, referenceYMax, width, xLabel, yAxisScale, yDomain, yLabel, yTicks]);

  useEffect(() => {
    applyZoomRef.current?.(zoom);
  }, [zoom]);

  return (
    <div ref={containerRef} className={cn("relative w-full", className)}>
      {normalizedSeries.length === 0 ? (
        <div className="flex items-center justify-center text-sm text-muted-foreground" style={{ height }}>
          {emptyHint}
        </div>
      ) : (
        <>
          <svg ref={svgRef} aria-label={`${xLabel} versus ${yLabel}`} />
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
              {tooltip.values.length > 1 ? (
                tooltip.values.map((item) => (
                  <div key={item.label} className="font-mono" style={{ color: item.color }}>
                    {item.label}: {formatIntensity(item.y)}
                  </div>
                ))
              ) : (
                <div className="font-mono text-muted-foreground">{yLabel}: {formatIntensity(tooltip.point.y)}</div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
