import { useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import { Maximize2, RotateCcw } from "lucide-react";
import { cn } from "@/lib/utils";
import { CHART_COLORS } from "@/features/theme/chartColors";

export interface ChartPeak {
  mz: number;
  intensity: number;
  /**
   * Optional ion-type label. If present, the peak is colored and the
   * tooltip shows the label. Used for matched fragment ions.
   */
  ion?: string | null;
  /** Ion display position (N-terminus 1..L for B/C, C-terminus 1..L for Y/Z).
   * Rendered as a subscript on the peak annotation. */
  ionPos?: number | null;
  /** free-form tooltip line added under the numbers (e.g. "C·95 · z+3"). */
  tooltip?: string | null;
  charge?: number | null;
  /** Optional stable key for raw peak interactions. */
  peakKey?: string | null;
  /** Optional relative intensity percentage for raw spectra tooltips. */
  relativeIntensity?: number | null;
}

/**
 * Zoom state for a spectrum. Either axis may be null, in which case that axis
 * falls back to its auto-computed domain (full X range, or max intensity of
 * the currently visible X range for Y).
 */
export interface Zoom {
  x: [number, number] | null;
  y: [number, number] | null;
}

export const DEFAULT_ZOOM: Zoom = { x: null, y: null };

export function isZoomed(z: Zoom): boolean {
  return z.x !== null || z.y !== null;
}

interface Props {
  peaks: ChartPeak[];
  xLabel?: string;
  yLabel?: string;
  height?: number;
  /** Optional marker line (e.g. precursor m/z on MS1). */
  marker?: { x: number; label: string } | null;
  /** Optional domain override (e.g. trim to signal range). */
  xDomain?: [number, number] | null;
  emptyHint?: string;
  /**
   * Controlled zoom state. If omitted the chart keeps its own internal state
   * and resets whenever `peaks` changes. For the "fullscreen modal" use case
   * the parent keeps the state so it survives unmount/remount.
   */
  zoom?: Zoom;
  onZoomChange?: (next: Zoom) => void;
  /** If provided, a "view large" button is rendered in the top-right corner. */
  onOpenFull?: () => void;
  /**
   * Optional vertical dashed guides at these m/z (e.g. matched deconv positions).
   * Drawn behind peak sticks; filtered to current X domain on each zoom.
   */
  annotationGuidesMz?: number[];
  /**
   * Optional hollow-circle overlay drawn on top of the peak sticks. Used by
   * the matched-peak detail panel to mark every isotope peak inside a single
   * deconvoluted envelope (TopFD's `env_peaks`). When `label` is provided
   * the chart draws an annotation (e.g. `Z· 19`) right above that circle.
   */
  envelopeOverlay?: EnvelopeOverlayPoint[];
  /** Optional single peak highlight drawn with the same non-invasive overlay. */
  highlightPeak?: EnvelopeOverlayPoint | null;
  /** Optional raw peak labels, used by spectra-only MS2 peak annotation. */
  peakLabels?: EnvelopeOverlayPoint[];
  /** Optional selected raw peak highlight, kept separate from precursor highlight. */
  selectedPeak?: EnvelopeOverlayPoint | null;
  /** Optional raw peak click callback. */
  onPeakClick?: (peak: ChartPeak) => void;
  /**
   * If provided, the Y axis renders ticks as percentages of this value
   * instead of the default SI-formatted intensity. Mirrors the original
   * TopMSV viewer where matched-peak windows show 0 / 25 / 50 / 75 / 100 %.
   * Takes precedence over {@link yIntensityScale} when set (matched-peak panel).
   */
  yPercentBase?: number | null;
  /**
   * `percent`: global base-peak normalization — max intensity over the full
   * `peaks` array is 100% relative abundance; X zoom does not change that scale.
   * Ignored when `yPercentBase` is set.
   */
  yIntensityScale?: "absolute" | "percent";
  /** Optional automatic Y-axis headroom ratio, e.g. 0.12 keeps 12% space above the tallest visible peak. */
  yHeadroomRatio?: number;
  className?: string;
}

export interface EnvelopeOverlayPoint {
  mz: number;
  intensity: number;
  key?: string;
  color?: string;
  label?: string;
}

const N_ION_TYPES = new Set(["B", "C", "A"]);
const C_ION_TYPES = new Set(["Y", "Z", "Z_DOT", "X"]);

function colorFor(peak: ChartPeak): string {
  if (!peak.ion) return CHART_COLORS.unmatched;
  if (N_ION_TYPES.has(peak.ion)) return "hsl(var(--ion-n))";
  if (C_ION_TYPES.has(peak.ion)) return "hsl(var(--ion-c))";
  return "hsl(var(--ion-shift))";
}

/**
 * Format an ion-type token for on-chart display.
 * `Z_DOT` is conventionally rendered as `Z•` (Z-radical); everything else
 * passes through as the single capital letter TopPIC already gives us.
 */
function displayIonLetter(ion: string): string {
  if (ion === "Z_DOT") return "Z\u2022";
  return ion;
}

/**
 * Find the first index `i` in a mz-sorted array for which `peaks[i].mz >= target`.
 * Returns `peaks.length` if every peak is below the target.
 */
function lowerBound(peaks: ChartPeak[], target: number): number {
  let lo = 0;
  let hi = peaks.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (peaks[mid].mz < target) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/**
 * Downsample unmatched peaks to at most ~2 per pixel column by max-pooling
 * intensity within fixed-width m/z buckets. Matched (ion-colored) peaks are
 * always preserved so the user never loses a coloured hit. Peaks must be
 * sorted by m/z.
 */
function downsampleForRender(
  peaks: ChartPeak[],
  xDomain: [number, number],
  innerW: number,
): ChartPeak[] {
  const [x0, x1] = xDomain;
  const range = x1 - x0;
  if (range <= 0 || innerW <= 0 || peaks.length === 0) return peaks;

  const start = lowerBound(peaks, x0);
  const endIdx = lowerBound(peaks, x1);
  const visibleCount = endIdx - start;

  // Target: at most 2 rendered peaks per pixel column.
  const targetBuckets = Math.max(200, innerW * 2);
  // If visible count is already modest, skip downsampling entirely – it's both
  // cheaper and preserves every peak for hover/tooltip accuracy.
  if (visibleCount <= targetBuckets) {
    return peaks.slice(start, endIdx);
  }

  const bucketWidth = range / targetBuckets;
  const out: ChartPeak[] = [];
  let currentBucket = -1;
  let tallest: ChartPeak | null = null;
  for (let i = start; i < endIdx; i++) {
    const p = peaks[i];
    if (p.ion) {
      // Keep all matched peaks. Flush any pending bucket first so ordering stays
      // monotonic in m/z, which matters for the hover bisector.
      if (tallest) {
        out.push(tallest);
        tallest = null;
      }
      out.push(p);
      currentBucket = -1;
      continue;
    }
    const bi = Math.floor((p.mz - x0) / bucketWidth);
    if (bi !== currentBucket) {
      if (tallest) out.push(tallest);
      tallest = p;
      currentBucket = bi;
    } else if (tallest == null || p.intensity > tallest.intensity) {
      tallest = p;
    }
  }
  if (tallest) out.push(tallest);
  return out;
}

export function SpectrumChart({
  peaks,
  xLabel = "m/z",
  yLabel = "Intensity",
  height = 260,
  marker = null,
  xDomain = null,
  emptyHint = "No peaks",
  zoom: zoomProp,
  onZoomChange,
  onOpenFull,
  annotationGuidesMz,
  envelopeOverlay,
  highlightPeak,
  peakLabels,
  selectedPeak,
  onPeakClick,
  yPercentBase,
  yIntensityScale = "absolute",
  yHeadroomRatio = 0,
  className,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [width, setWidth] = useState(640);
  const [tooltip, setTooltip] = useState<
    | { x: number; y: number; peak: ChartPeak }
    | null
  >(null);
  const [internalZoom, setInternalZoom] = useState<Zoom>(DEFAULT_ZOOM);

  const zoom = zoomProp ?? internalZoom;
  const isControlled = zoomProp !== undefined;

  // Refs that wheel / brush closures read synchronously. Keeping them fresh
  // lets us attach the wheel listener once and read the latest zoom + commit
  // function without re-attaching between frames.
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;
  const commitZoomRef = useRef<(z: Zoom) => void>(() => {});
  commitZoomRef.current = (next: Zoom) => {
    if (onZoomChange) onZoomChange(next);
    if (!isControlled) setInternalZoom(next);
  };

  // Sort peaks once by m/z so bisector lookup + binary-search downsampling are
  // correct. Short-circuit if the input is already sorted (the common case).
  const sortedPeaks = useMemo(() => {
    let sorted = true;
    for (let i = 1; i < peaks.length; i++) {
      if (peaks[i].mz < peaks[i - 1].mz) {
        sorted = false;
        break;
      }
    }
    return sorted ? peaks : [...peaks].sort((a, b) => a.mz - b.mz);
  }, [peaks]);

  const fullX = useMemo<[number, number]>(() => {
    if (xDomain) return xDomain;
    if (sortedPeaks.length === 0) return [0, 1];
    return [sortedPeaks[0].mz, sortedPeaks[sortedPeaks.length - 1].mz];
  }, [sortedPeaks, xDomain]);

  /** Max intensity over the entire spectrum (not X-window / not downsampled). */
  const globalBPI = useMemo(() => {
    let m = 0;
    for (const p of sortedPeaks) {
      if (p.intensity > m) m = p.intensity;
    }
    return m > 0 ? m : 1;
  }, [sortedPeaks]);

  const useLocalPercentPanel =
    yPercentBase != null && yPercentBase > 0;
  const useGlobalRA =
    yIntensityScale === "percent" && !useLocalPercentPanel;
  const safeYHeadroomRatio =
    Number.isFinite(yHeadroomRatio) && yHeadroomRatio > 0 ? yHeadroomRatio : 0;

  const axisYLabel = useMemo(() => {
    if (useGlobalRA) return "Relative abundance (%)";
    return yLabel;
  }, [useGlobalRA, yLabel]);

  // Keep primitive marker values so the skeleton effect doesn't rebuild on
  // every parent re-render (the caller often creates `marker` inline).
  const markerX = marker?.x ?? null;
  const markerLabel = marker?.label ?? null;

  // Observe container width for responsive sizing.
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        const w = e.contentRect.width;
        if (w > 100) setWidth(Math.floor(w));
      }
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  // Reset internal zoom when the dataset changes. When controlled, the parent
  // owns this decision.
  useEffect(() => {
    if (!isControlled) setInternalZoom(DEFAULT_ZOOM);
  }, [sortedPeaks, isControlled]);

  // --- Skeleton build ---------------------------------------------------------
  // Builds the static SVG structure exactly once per data/layout change and
  // exposes an imperative `applyZoom(zoom)` via a ref. All hot-path updates
  // (wheel zoom, brush-end, external zoom prop changes) funnel through that
  // closure so we avoid React re-render + `d3.selectAll.remove()` on every tick.
  const applyZoomRef = useRef<((z: Zoom) => void) | null>(null);

  useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    const svg = d3.select(svgEl);
    svg.selectAll("*").remove();
    if (sortedPeaks.length === 0) {
      applyZoomRef.current = null;
      return;
    }

    const margin = { top: 12, right: 18, bottom: 40, left: 60 };
    const innerW = Math.max(50, width - margin.left - margin.right);
    const innerH = Math.max(50, height - margin.top - margin.bottom);

    svg
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("width", width)
      .attr("height", height);

    // Unique clipPath id so multiple charts on the same page don't collide.
    const clipId = `spec-clip-${Math.random().toString(36).slice(2, 9)}`;
    svg
      .append("defs")
      .append("clipPath")
      .attr("id", clipId)
      .append("rect")
      .attr("width", innerW)
      .attr("height", innerH);

    const g = svg
      .append("g")
      .attr("transform", `translate(${margin.left},${margin.top})`);

    // Axis labels (static, don't change with zoom).
    g.append("text")
      .attr("x", innerW / 2)
      .attr("y", innerH + 32)
      .attr("text-anchor", "middle")
      .attr("fill", CHART_COLORS.text)
      .attr("font-size", 11)
      .text(xLabel);
    g.append("text")
      .attr("transform", `rotate(-90) translate(${-innerH / 2},${-44})`)
      .attr("text-anchor", "middle")
      .attr("fill", CHART_COLORS.text)
      .attr("font-size", 11)
      .text(axisYLabel);

    // Reusable groups: axes + grid (updated via `axis.call` on every zoom,
    // which only patches tick text/lines) and peak layer (clipped so off-range
    // peaks never spill when zoomed in).
    const gridG = g.append("g").attr("class", "grid");
    const xAxisG = g.append("g").attr("transform", `translate(0,${innerH})`);
    const yAxisG = g.append("g");
    const peakG = g
      .append("g")
      .attr("class", "peaks")
      .attr("clip-path", `url(#${clipId})`);
    const guidesG = peakG.append("g").attr("class", "annotation-guides");
    const linesG = peakG.append("g").attr("class", "lines");
    const dotsG = peakG.append("g").attr("class", "dots");
    // Hollow-circle overlay for envelope isotope peaks. Rendered above the
    // sticks but under the marker so peak labels still sit on top.
    const envOverlayG = peakG.append("g").attr("class", "env-overlay");
    const envLabelsG = peakG
      .append("g")
      .attr("class", "env-labels")
      .attr("pointer-events", "none");
    const markerG = g
      .append("g")
      .attr("class", "marker")
      .attr("clip-path", `url(#${clipId})`);
    // Annotation labels (e.g. "C 3+ / 39") for the most prominent matched
    // peaks. Rendered last so they sit above every peak line, and flagged
    // pointer-events="none" so they never eat mouse events from the overlay.
    const labelsG = g
      .append("g")
      .attr("class", "labels")
      .attr("clip-path", `url(#${clipId})`)
      .attr("pointer-events", "none");

    // Brush for X zoom. Its internal overlay captures mousedown/dblclick so we
    // attach the tooltip / dblclick-to-reset listeners on the outer SVG
    // element where they reliably bubble.
    const brushG = g.append("g").attr("class", "brush");

    // Live scales (re-assigned on every applyZoom call).
    let xScale: d3.ScaleLinear<number, number> = d3
      .scaleLinear()
      .domain(fullX)
      .range([0, innerW]);
    let yScale: d3.ScaleLinear<number, number> = d3
      .scaleLinear()
      .domain([0, 1])
      .range([innerH, 0]);
    let hoverCandidates: ChartPeak[] = sortedPeaks;

    const siFormat = d3.format(".2s");
    const bisectMz = d3.bisector<ChartPeak, number>((p) => p.mz).left;

    const applyZoom = (z: Zoom) => {
      // IMPORTANT: don't `.nice()` the X scale. `.nice()` expands the domain
      // to round numbers, so a committed `[408.35, 491.65]` becomes
      // `[400, 500]` in the live scale. Reading `xScale.domain()` for the
      // next wheel tick's pivot then snaps back to 400/500, which makes the
      // zoom feel like it "hits a wall" every few ticks. Leaving the domain
      // exact is what lets the zoom stay truly stepless; tick *positions*
      // are still chosen by d3 inside the domain, so axis labels still look
      // nice either way.
      const [xd0, xd1] = z.x ?? fullX;
      xScale = d3.scaleLinear().domain([xd0, xd1]).range([0, innerW]);

      const displayed = downsampleForRender(
        sortedPeaks,
        [xd0, xd1],
        innerW,
      );
      hoverCandidates = displayed;

      let autoYMax = 0;
      for (const p of displayed) if (p.intensity > autoYMax) autoYMax = p.intensity;
      if (autoYMax === 0) autoYMax = 1;

      let yDomain: [number, number];
      if (useGlobalRA) {
        if (z.y == null) {
          yDomain = [0, globalBPI];
        } else {
          let y0 = z.y[0];
          let y1 = z.y[1];
          if (y0 < 0) y0 = 0;
          if (y1 > globalBPI) y1 = globalBPI;
          if (y1 - y0 < 1e-6 || y0 >= y1) yDomain = [0, globalBPI];
          else yDomain = [y0, y1];
        }
      } else {
        yDomain = z.y ?? [0, autoYMax * (1 + safeYHeadroomRatio)];
      }
      // Same reason as X: keep domain exact so Y zoom is also truly stepless.
      yScale = d3.scaleLinear().domain(yDomain).range([innerH, 0]);

      xAxisG
        .call(
          d3
            .axisBottom(xScale)
            .ticks(Math.max(5, Math.floor(innerW / 90))) as any,
        )
        .call((sel) => {
          sel
            .selectAll("text")
            .attr("fill", CHART_COLORS.text)
            .attr("font-size", 11);
          sel.selectAll("line, path").attr("stroke", CHART_COLORS.axis);
        });
      const yTickFormat: (v: d3.NumberValue) => string = useLocalPercentPanel
        ? (v) =>
            `${Math.round((Number(v) / (yPercentBase as number)) * 100)}%`
        : useGlobalRA
          ? (v) => `${Math.round((Number(v) / globalBPI) * 100)}%`
          : (v) => siFormat(Number(v));
      yAxisG
        .call(
          d3
            .axisLeft(yScale)
            .ticks(5)
            .tickFormat(yTickFormat) as any,
        )
        .call((sel) => {
          sel
            .selectAll("text")
            .attr("fill", CHART_COLORS.text)
            .attr("font-size", 11);
          sel.selectAll("line, path").attr("stroke", CHART_COLORS.axis);
        });

      gridG
        .call(
          d3
            .axisLeft(yScale)
            .tickSize(-innerW)
            .tickFormat(() => "") as any,
        )
        .selectAll("line")
        .attr("stroke", CHART_COLORS.grid)
        .attr("stroke-dasharray", "2,3");
      gridG.selectAll(".domain").remove();

      const yBase = yScale(0);

      const guideMzList = annotationGuidesMz ?? [];
      const inViewGuides = guideMzList.filter((mz) => mz >= xd0 && mz <= xd1);
      guidesG
        .selectAll<SVGLineElement, number>("line.guide")
        .data(inViewGuides, (d) => String(d))
        .join(
          (enter) =>
            enter
              .append("line")
              .attr("class", "guide")
              .attr("x1", (d) => xScale(d))
              .attr("x2", (d) => xScale(d))
              .attr("y1", innerH)
              .attr("y2", 0)
              .attr("stroke", "hsl(var(--muted-foreground) / 0.5)")
              .attr("stroke-dasharray", "3,2")
              .attr("stroke-width", 1)
              .attr("pointer-events", "none"),
          (update) =>
            update.attr("x1", (d) => xScale(d)).attr("x2", (d) => xScale(d)),
          (exit) => exit.remove(),
        );

      // Data-join the peak lines. Since `displayed.length` is bounded by ~2×
      // innerW, this join touches at most a few thousand attrs even for very
      // dense spectra – an order of magnitude cheaper than rebuilding.
      linesG
        .selectAll<SVGLineElement, ChartPeak>("line")
        .data(displayed)
        .join(
          (enter) =>
            enter
              .append("line")
              .attr("x1", (d) => xScale(d.mz))
              .attr("x2", (d) => xScale(d.mz))
              .attr("y1", yBase)
              .attr("y2", (d) => yScale(d.intensity))
              .attr("stroke", (d) => colorFor(d))
              .attr("stroke-width", (d) => (d.ion ? 1.6 : 1)),
          (update) =>
            update
              .attr("x1", (d) => xScale(d.mz))
              .attr("x2", (d) => xScale(d.mz))
              .attr("y1", yBase)
              .attr("y2", (d) => yScale(d.intensity))
              .attr("stroke", (d) => colorFor(d))
              .attr("stroke-width", (d) => (d.ion ? 1.6 : 1)),
          (exit) => exit.remove(),
        );

      const matched: ChartPeak[] = [];
      for (const p of displayed) if (p.ion) matched.push(p);
      dotsG
        .selectAll<SVGCircleElement, ChartPeak>("circle")
        .data(matched)
        .join(
          (enter) =>
            enter
              .append("circle")
              .attr("cx", (d) => xScale(d.mz))
              .attr("cy", (d) => yScale(d.intensity))
              .attr("r", 2.5)
              .attr("fill", (d) => colorFor(d)),
          (update) =>
            update
              .attr("cx", (d) => xScale(d.mz))
              .attr("cy", (d) => yScale(d.intensity))
              .attr("fill", (d) => colorFor(d)),
          (exit) => exit.remove(),
        );

      // Envelope-isotope hollow circles + ion annotation. Filtered to the
      // current X domain so panning/zoom keeps them responsive without a
      // full rebuild.
      const overlay = [
        ...(envelopeOverlay ?? []),
        ...(peakLabels ?? []),
        ...(highlightPeak ? [highlightPeak] : []),
        ...(selectedPeak ? [selectedPeak] : []),
      ].filter(
        (d) => d.mz >= xd0 && d.mz <= xd1,
      );
      envOverlayG
        .selectAll<SVGCircleElement, EnvelopeOverlayPoint>("circle")
        .data(overlay, (d) => d.key ?? `${d.mz}|${d.intensity}|${d.label ?? ""}`)
        .join(
          (enter) =>
            enter
              .append("circle")
              .attr("cx", (d) => xScale(d.mz))
              .attr("cy", (d) => yScale(d.intensity))
              .attr("r", 4.5)
              .attr("fill", "none")
              .attr("stroke", (d) => d.color ?? "hsl(var(--ion-c))")
              .attr("stroke-width", 1.5),
          (update) =>
            update
              .attr("cx", (d) => xScale(d.mz))
              .attr("cy", (d) => yScale(d.intensity))
              .attr("stroke", (d) => d.color ?? "hsl(var(--ion-c))"),
          (exit) => exit.remove(),
        );

      envLabelsG.selectAll("*").remove();
      for (const o of overlay) {
        if (!o.label) continue;
        const ox = xScale(o.mz);
        const oy = yScale(o.intensity);
        if (ox < 0 || ox > innerW || oy < 0 || oy > innerH) continue;
        envLabelsG
          .append("text")
          .attr("x", ox + 6)
          .attr("y", Math.max(12, oy - 8))
          .attr("text-anchor", "start")
          .attr("font-family", "Arial, Helvetica, sans-serif")
          .attr("font-size", 12)
          .attr("font-weight", 600)
          .attr("fill", o.color ?? "hsl(var(--ion-c))")
          .text(o.label);
      }

      markerG.selectAll("*").remove();
      if (markerX != null && Number.isFinite(markerX)) {
        const mx = xScale(markerX);
        if (mx >= 0 && mx <= innerW) {
          markerG
            .append("line")
            .attr("x1", mx)
            .attr("x2", mx)
            .attr("y1", 0)
            .attr("y2", innerH)
            .attr("stroke", "hsl(var(--primary))")
            .attr("stroke-dasharray", "4,3")
            .attr("stroke-width", 1.2);
          if (markerLabel) {
            markerG
              .append("text")
              .attr("x", mx + 4)
              .attr("y", 12)
              .attr("fill", "hsl(var(--primary))")
              .attr("font-size", 10)
              .text(markerLabel);
          }
        }
      }

      // --- Annotation labels (greedy, non-overlapping) ----------------------
      // Show "letter + charge superscript + position subscript" (e.g. C^{3+}_{39})
      // above the tallest matched peaks that can fit without colliding. When
      // the view is crowded, only the most prominent peaks get a label;
      // zooming in frees room and reveals more labels automatically.
      const LABEL_W = 26;
      const LABEL_H = 20;
      const LABEL_X_OFFSET = -4; // peak sits a bit left of the bbox center
      const MAIN_FONT = 11;
      const SUB_FONT = 7.5;

      // Rank candidates by intensity so the tallest peak in any cluster wins
      // its label slot first – that's the "most important" peak intuitively.
      const rankedMatches = matched.slice().sort((a, b) => b.intensity - a.intensity);

      const placed: Array<{
        peak: ChartPeak;
        px: number;
        py: number;
        x0: number;
        y0: number;
        x1: number;
        y1: number;
      }> = [];

      for (const p of rankedMatches) {
        const px = xScale(p.mz);
        if (px < 0 || px > innerW) continue;
        const py = yScale(p.intensity);
        if (py < 0 || py > innerH) continue;

        // Bbox reserved for this label. The peak x sits near the left edge of
        // the bbox so the subscript/superscript (which hang to the right of
        // the main letter) stay inside.
        const x0 = px + LABEL_X_OFFSET;
        const x1 = x0 + LABEL_W;
        const y1 = py - 2; // bottom of label = just above peak top
        const y0 = y1 - LABEL_H;

        // Require the bbox to be fully inside the plot so labels never look
        // like they're clipped.
        if (y0 < 0 || x0 < 0 || x1 > innerW) continue;

        let collides = false;
        for (const s of placed) {
          if (!(x1 <= s.x0 || x0 >= s.x1 || y1 <= s.y0 || y0 >= s.y1)) {
            collides = true;
            break;
          }
        }
        if (collides) continue;

        placed.push({ peak: p, px, py, x0, y0, x1, y1 });
      }

      // Full rebuild is fine here – `placed.length` is bounded by how many
      // labels fit, so at most a few dozen text nodes even on a crowded MS2.
      labelsG.selectAll("*").remove();
      for (const s of placed) {
        const color = colorFor(s.peak);
        const letter = displayIonLetter(s.peak.ion!);

        // Main letter: anchored so its left edge is at `px`, baseline at
        // `py - 5` (just above the peak top).
        labelsG
          .append("text")
          .attr("x", s.px)
          .attr("y", s.py - 5)
          .attr("text-anchor", "start")
          .attr("font-family", "Arial, Helvetica, sans-serif")
          .attr("font-size", MAIN_FONT)
          .attr("font-weight", 600)
          .attr("fill", color)
          .text(letter);

        // Charge superscript: a bit above the top of the main letter,
        // slightly indented so it sits to the upper-right of the letter.
        if (s.peak.charge != null) {
          labelsG
            .append("text")
            .attr("x", s.px + MAIN_FONT * 0.7)
            .attr("y", s.py - MAIN_FONT - 1)
            .attr("text-anchor", "start")
            .attr("font-family", "Arial, Helvetica, sans-serif")
            .attr("font-size", SUB_FONT)
            .attr("fill", color)
            .text(`${s.peak.charge}+`);
        }

        // Ion position subscript: just below the baseline of the main letter.
        if (s.peak.ionPos != null) {
          labelsG
            .append("text")
            .attr("x", s.px + MAIN_FONT * 0.7)
            .attr("y", s.py - 1)
            .attr("text-anchor", "start")
            .attr("font-family", "Arial, Helvetica, sans-serif")
            .attr("font-size", SUB_FONT)
            .attr("fill", color)
            .text(String(s.peak.ionPos));
        }
      }
    };

    applyZoomRef.current = applyZoom;

    // Brush: committed once, picks up the current xScale via closure over the
    // ref. Empty / tiny drags are no-ops.
    const brush = d3
      .brushX()
      .extent([
        [0, 0],
        [innerW, innerH],
      ])
      .on("end", (event) => {
        if (!event.selection) return;
        const [a, b] = event.selection as [number, number];
        brushG.call(brush.move as any, null);
        if (Math.abs(b - a) < 4) return;
        commitZoomRef.current({
          x: [xScale.invert(a), xScale.invert(b)],
          y: zoomRef.current.y,
        });
      });
    brushG.call(brush as any);

    // Hover tooltip + dblclick reset, attached to the svg element so they work
    // regardless of whether the brush overlay is currently on top.
    let tooltipRaf = 0;
    let lastMoveEvent: MouseEvent | null = null;
    const findNearestPeakAt = (px: number): ChartPeak | null => {
      const mzVal = xScale.invert(px);
      const idx = bisectMz(hoverCandidates, mzVal);
      const a = hoverCandidates[Math.max(0, idx - 1)];
      const b = hoverCandidates[Math.min(hoverCandidates.length - 1, idx)];
      return !a
        ? b ?? null
        : !b
          ? a
          : Math.abs(a.mz - mzVal) < Math.abs(b.mz - mzVal)
            ? a
            : b;
    };
    const onMove = (event: MouseEvent) => {
      lastMoveEvent = event;
      if (tooltipRaf) return;
      tooltipRaf = requestAnimationFrame(() => {
        tooltipRaf = 0;
        const ev = lastMoveEvent;
        if (!ev) return;
        const rect = svgEl.getBoundingClientRect();
        const px = ev.clientX - rect.left - margin.left;
        const py = ev.clientY - rect.top - margin.top;
        if (px < 0 || py < 0 || px > innerW || py > innerH) {
          setTooltip((prev) => (prev == null ? prev : null));
          return;
        }
        const nearest = findNearestPeakAt(px);
        if (nearest) {
          setTooltip({ x: px + margin.left, y: py + margin.top, peak: nearest });
        }
      });
    };
    const onLeave = () => setTooltip(null);
    const onDblClick = (event: MouseEvent) => {
      const rect = svgEl.getBoundingClientRect();
      const px = event.clientX - rect.left - margin.left;
      const py = event.clientY - rect.top - margin.top;
      if (px >= 0 && py >= 0 && px <= innerW && py <= innerH) {
        commitZoomRef.current(DEFAULT_ZOOM);
      }
    };
    const onClick = (event: MouseEvent) => {
      if (!onPeakClick) return;
      const rect = svgEl.getBoundingClientRect();
      const px = event.clientX - rect.left - margin.left;
      const py = event.clientY - rect.top - margin.top;
      if (px < 0 || py < 0 || px > innerW || py > innerH) return;
      const nearest = findNearestPeakAt(px);
      if (nearest) onPeakClick(nearest);
    };
    svgEl.addEventListener("mousemove", onMove);
    svgEl.addEventListener("mouseleave", onLeave);
    svgEl.addEventListener("dblclick", onDblClick);
    svgEl.addEventListener("click", onClick);

    // Wheel zoom. Cursor region picks the axis:
    //   * over the Y-axis gutter  -> zoom Y around cursor Y.
    //   * over the X-axis gutter  -> zoom X around cursor X.
    //   * over the plot area      -> zoom X (the primary axis for spectra).
    //   * hold Shift + wheel      -> force Y zoom regardless of region.
    //
    // Events are coalesced to at most one per animation frame so fast trackpad
    // scrolling commits one React state update per ~16ms instead of per
    // physical wheel tick.
    const accum = {
      deltaY: 0,
      cx: 0,
      cy: 0,
      mode: "" as "x" | "y" | "",
      scheduled: false,
    };

    const wheelHandler = (e: WheelEvent) => {
      const rect = svgEl.getBoundingClientRect();
      const cx = e.clientX - rect.left - margin.left;
      const cy = e.clientY - rect.top - margin.top;

      const onYAxis =
        cx < 0 && cx > -margin.left && cy >= 0 && cy <= innerH;
      const onXAxis =
        cy > innerH && cy < innerH + margin.bottom && cx >= 0 && cx <= innerW;
      const inPlot = cx >= 0 && cx <= innerW && cy >= 0 && cy <= innerH;
      if (!onYAxis && !onXAxis && !inPlot) return;
      e.preventDefault();

      const mode: "x" | "y" = onYAxis || (inPlot && e.shiftKey) ? "y" : "x";
      // If the zoom axis changed mid-gesture, flush whatever was pending so
      // we never mix X and Y accumulations.
      if (accum.mode && accum.mode !== mode) accum.deltaY = 0;
      accum.deltaY += e.deltaY;
      accum.cx = cx;
      accum.cy = cy;
      accum.mode = mode;

      if (accum.scheduled) return;
      accum.scheduled = true;
      requestAnimationFrame(() => {
        accum.scheduled = false;
        const dy = accum.deltaY;
        accum.deltaY = 0;
        if (dy === 0 || !accum.mode) return;
        // Continuous-feeling zoom: 100px of wheel travel = 1.35× scale change.
        // Slightly punchier than the classic 1.2 so a single mouse-wheel tick
        // feels like a real step, while trackpad gestures (many small dy
        // events per frame) still integrate to a smooth curve.
        const factor = Math.pow(1.35, dy / 100);
        const currentZoom = zoomRef.current;

        if (accum.mode === "y") {
          const py = Math.max(0, Math.min(innerH, accum.cy));
          const vy = yScale.invert(py);
          const [y0, y1] = yScale.domain() as [number, number];
          let newY0 = vy - (vy - y0) * factor;
          let newY1 = vy + (y1 - vy) * factor;
          if (newY0 < 0) newY0 = 0;
          if (useGlobalRA) {
            if (newY1 > globalBPI) newY1 = globalBPI;
            if (newY0 > newY1 - 1e-6) newY0 = Math.max(0, newY1 - 1e-6);
          }
          if (newY1 - newY0 < 1e-6) return;
          commitZoomRef.current({ x: currentZoom.x, y: [newY0, newY1] });
        } else {
          const px = Math.max(0, Math.min(innerW, accum.cx));
          const vx = xScale.invert(px);
          const [curX0, curX1] = xScale.domain() as [number, number];
          let newX0 = vx - (vx - curX0) * factor;
          let newX1 = vx + (curX1 - vx) * factor;
          if (newX0 < fullX[0]) newX0 = fullX[0];
          if (newX1 > fullX[1]) newX1 = fullX[1];
          if (newX1 - newX0 < 1e-6) return;
          const next: Zoom["x"] =
            newX0 === fullX[0] && newX1 === fullX[1]
              ? null
              : [newX0, newX1];
          commitZoomRef.current({ x: next, y: currentZoom.y });
        }
      });
    };
    svgEl.addEventListener("wheel", wheelHandler, { passive: false });

    // Initial paint using whatever zoom is currently set by the parent.
    applyZoom(zoomRef.current);

    return () => {
      svgEl.removeEventListener("wheel", wheelHandler);
      svgEl.removeEventListener("mousemove", onMove);
      svgEl.removeEventListener("mouseleave", onLeave);
      svgEl.removeEventListener("dblclick", onDblClick);
      svgEl.removeEventListener("click", onClick);
      if (tooltipRaf) cancelAnimationFrame(tooltipRaf);
      applyZoomRef.current = null;
    };
  }, [
    sortedPeaks,
    width,
    height,
    xLabel,
    axisYLabel,
    markerX,
    markerLabel,
    fullX,
    annotationGuidesMz,
    envelopeOverlay,
    highlightPeak,
    peakLabels,
    selectedPeak,
    onPeakClick,
    yPercentBase,
    yIntensityScale,
    safeYHeadroomRatio,
    globalBPI,
    useGlobalRA,
    useLocalPercentPanel,
  ]);

  // --- Zoom update (hot path) -------------------------------------------------
  // Just delegates to the skeleton's imperative applyZoom. No DOM teardown, no
  // event listener reattachment – the whole redraw is axis ticks + ~innerW×2
  // peak attrs, which stays well under 1ms even for dense MS1 spectra.
  useEffect(() => {
    applyZoomRef.current?.(zoom);
  }, [zoom]);

  const zoomed = isZoomed(zoom);

  return (
    <div ref={containerRef} className={cn("relative w-full", className)}>
      {peaks.length === 0 ? (
        <div
          className="flex items-center justify-center text-sm text-muted-foreground"
          style={{ height }}
        >
          {emptyHint}
        </div>
      ) : (
        <>
          <svg ref={svgRef} />
          <div className="absolute right-2 top-2 flex items-center gap-1">
            <button
              type="button"
              onClick={() => commitZoomRef.current(DEFAULT_ZOOM)}
              disabled={!zoomed}
              title="reset zoom (dbl-click plot)"
              className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-0.5 text-[11px] text-muted-foreground shadow-sm transition-colors enabled:hover:text-foreground disabled:opacity-40"
            >
              <RotateCcw className="h-3 w-3" />
              reset
            </button>
            {onOpenFull && (
              <button
                type="button"
                onClick={onOpenFull}
                title="view large"
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
              style={{
                left: Math.min(tooltip.x + 8, width - 160),
                top: Math.max(tooltip.y - 8, 0),
              }}
            >
              <div className="font-mono">m/z {tooltip.peak.mz.toFixed(4)}</div>
              <div className="font-mono text-muted-foreground">
                int {d3.format(".3~s")(tooltip.peak.intensity)}
                {tooltip.peak.charge != null ? ` · z=${tooltip.peak.charge}` : ""}
              </div>
              {useGlobalRA && (
                <div className="font-mono text-muted-foreground">
                  RA {((tooltip.peak.intensity / globalBPI) * 100).toFixed(2)}%
                </div>
              )}
              {typeof tooltip.peak.relativeIntensity === "number" && Number.isFinite(tooltip.peak.relativeIntensity) && (
                <div className="font-mono text-muted-foreground">
                  relative {tooltip.peak.relativeIntensity.toFixed(1)}%
                </div>
              )}
              {tooltip.peak.ion && (
                <div className="font-semibold" style={{ color: colorFor(tooltip.peak) }}>
                  {tooltip.peak.ion}
                  {tooltip.peak.tooltip ? ` · ${tooltip.peak.tooltip}` : ""}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
