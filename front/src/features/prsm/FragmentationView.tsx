import { useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import { cn } from "@/lib/utils";
import type { AnnotatedProtein, MsPeakRow } from "./parse";

/*
 * Fragmentation / sequence-ladder view.
 *
 * Port of the `mono mass` MS2 graph from `topmsv/common/spectrum_view`
 * (`drawSequence`, `addErrorPlot`, `drawErrorPoints`). Three horizontally
 * stacked zones share the same mass x-axis:
 *
 *   1. Sequence ladder (top)
 *        Two rows — N-terminal ions (B / C / A) on top, C-terminal ions
 *        (Y / Z / Z· / X) below. A short vertical tick is drawn at every
 *        residue position of the proteoform (matched ticks are in their
 *        ion color, unmatched ticks are muted grey). Exactly one
 *        amino-acid letter is rendered between consecutive ticks — the
 *        residue that the ion series gains from `position → position + 1`.
 *
 *   2. Stick plot (middle)
 *        Every deconvoluted peak in `ms_peaks` is drawn as a thin stick
 *        at `monoisotopic_mass`; unmatched peaks are muted grey, matched
 *        ones are coloured (blue = N, red = C) with a small label such
 *        as `C₃₉` or `Z•₄₂`.
 *
 *   3. Error plot (bottom)
 *        Each matched ion contributes one dot at (mass, ppmError). A
 *        dashed zero line doubles as the x-axis baseline.
 *
 * Unlike MS1/MS2 the x-axis is *not* zoomed — the SVG is rendered at a
 * fixed density (px / Da, controllable via slider), wrapped in a native
 * horizontal-scroll container so the user can pan freely.
 *
 * Theoretical ion masses for *every* position are derived from a standard
 * monoisotopic amino-acid table plus the mass shifts reported in
 * `annotated_protein.annotation.mass_shift`, and calibrated to the
 * dominant matched-ion type so the ladder aligns with the observed
 * peaks regardless of ion chemistry (B/C/Y/Z/Z•).
 */

interface Props {
  protein: AnnotatedProtein;
  peaks: MsPeakRow[];
  className?: string;
}

const N_ION_TYPES = new Set(["B", "C", "A"]);
const C_ION_TYPES = new Set(["Y", "Z", "Z_DOT", "X"]);

// Monoisotopic residue masses (Da). Covers the 20 canonical amino acids
// plus selenocysteine (U) and pyrrolysine (O). X/B/Z/J default to 0 so we
// don't inject bogus offsets if the sequence contains ambiguity codes.
const AA_MASS: Record<string, number> = {
  G: 57.02146,
  A: 71.03711,
  S: 87.03203,
  P: 97.05276,
  V: 99.06841,
  T: 101.04768,
  C: 103.00919,
  L: 113.08406,
  I: 113.08406,
  N: 114.04293,
  D: 115.02694,
  Q: 128.05858,
  K: 128.09496,
  E: 129.04259,
  M: 131.04049,
  H: 137.05891,
  F: 147.06841,
  R: 156.10111,
  Y: 163.06333,
  W: 186.07931,
  U: 150.95364,
  O: 237.14773,
};

function aaMass(letter: string): number {
  return AA_MASS[letter.toUpperCase()] ?? 0;
}

interface LadderIon {
  position: number;
  theoreticalMass: number;
  monoMass: number;
  intensity: number;
  charge: number | null;
  ionType: string;
  ppmError: number | null;
}

interface DeconvPeak {
  mass: number;
  intensity: number;
  matched: boolean;
  ionType: string | null;
  position: number | null;
  charge: number | null;
  ppmError: number | null;
}

interface LadderTick {
  position: number; // 1..formLen-1
  mass: number; // calibrated theoretical mass
  matched: boolean;
  matchedIon: LadderIon | null;
}

function displayIonLetter(ion: string): string {
  if (ion === "Z_DOT") return "Z\u2022";
  return ion;
}

function colorForSide(side: "n" | "c"): string {
  return side === "n" ? "hsl(var(--ion-n))" : "hsl(var(--ion-c))";
}

function colorForPeak(p: DeconvPeak): string {
  if (!p.matched || !p.ionType) return "hsl(215 16% 60%)";
  if (N_ION_TYPES.has(p.ionType)) return "hsl(var(--ion-n))";
  if (C_ION_TYPES.has(p.ionType)) return "hsl(var(--ion-c))";
  return "hsl(var(--ion-shift))";
}

export function FragmentationView({ protein, peaks, className }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [viewportW, setViewportW] = useState(900);

  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        const w = e.contentRect.width;
        if (w > 100) setViewportW(Math.floor(w));
      }
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  // Flatten sequence to a string once; `firstResiduePosition` is the 0-based
  // index of the first residue actually belonging to the proteoform form.
  const seq = useMemo(
    () => protein.residues.map((r) => r.acid).join(""),
    [protein.residues],
  );

  const formFirst = protein.firstResiduePosition;
  const formLast = protein.lastResiduePosition;
  const formLen = Math.max(0, formLast - formFirst + 1);

  // Per-residue masses (AA table + variable / unexpected / fixed mass
  // shifts applied at their left position). Indices are protein-absolute,
  // so [formFirst..formLast] is the form's residue slice.
  const residueMasses = useMemo(() => {
    const out = protein.residues.map((r) => aaMass(r.acid));
    for (const ms of protein.massShifts) {
      if (ms.shift == null) continue;
      if (ms.leftPosition >= 0 && ms.leftPosition < out.length) {
        out[ms.leftPosition] += ms.shift;
      }
    }
    return out;
  }, [protein.residues, protein.massShifts]);

  // --- ladder ion series -------------------------------------------------
  const { nIons, cIons } = useMemo(() => {
    const n: LadderIon[] = [];
    const c: LadderIon[] = [];
    for (const p of peaks) {
      if (p.monoMass == null || p.intensity == null) continue;
      for (const ion of p.matchedIons) {
        if (ion.theoreticalMass == null) continue;
        const entry: LadderIon = {
          position: ion.ionDisplayPosition,
          theoreticalMass: ion.theoreticalMass,
          monoMass: p.monoMass,
          intensity: p.intensity,
          charge: p.charge,
          ionType: ion.ionType,
          ppmError: ion.ppm,
        };
        if (N_ION_TYPES.has(ion.ionType)) n.push(entry);
        else if (C_ION_TYPES.has(ion.ionType)) c.push(entry);
      }
    }
    const dedup = (arr: LadderIon[]) => {
      // Keep the highest-intensity match per position.
      const m = new Map<number, LadderIon>();
      for (const x of arr) {
        const prev = m.get(x.position);
        if (!prev || x.intensity > prev.intensity) m.set(x.position, x);
      }
      return Array.from(m.values()).sort((a, b) => a.position - b.position);
    };
    return { nIons: dedup(n), cIons: dedup(c) };
  }, [peaks]);

  // Cumulative prefix / suffix residue masses inside the form. The ladder
  // position `p` (1..formLen-1) corresponds to cumN[p] / cumC[p].
  //
  //   cumN[p] = Σ residueMasses[formFirst .. formFirst + p - 1]
  //   cumC[p] = Σ residueMasses[formLast .. formLast - p + 1]
  //
  // These are O(formLen) to build once and give O(1) lookup per tick.
  const { cumN, cumC } = useMemo(() => {
    const nArr = new Array<number>(formLen + 1).fill(0);
    const cArr = new Array<number>(formLen + 1).fill(0);
    for (let i = 0; i < formLen; i++) {
      nArr[i + 1] = nArr[i] + (residueMasses[formFirst + i] ?? 0);
      cArr[i + 1] = cArr[i] + (residueMasses[formLast - i] ?? 0);
    }
    return { cumN: nArr, cumC: cArr };
  }, [residueMasses, formFirst, formLast, formLen]);

  // Calibrate: for each side, find the dominant matched ion type and the
  // average offset between theoretical ion mass and cumulative residue
  // mass. This gives us the per-ion-type offset constant, which we use to
  // assign theoretical masses to every ladder position — matched or not.
  const nOffset = useMemo(
    () => calibrateOffset(nIons, cumN),
    [nIons, cumN],
  );
  const cOffset = useMemo(
    () => calibrateOffset(cIons, cumC),
    [cIons, cumC],
  );

  const nTicks = useMemo<LadderTick[]>(() => {
    if (nOffset == null || formLen <= 1) return [];
    const matchedMap = new Map<number, LadderIon>();
    for (const i of nIons) matchedMap.set(i.position, i);
    const out: LadderTick[] = [];
    for (let p = 1; p < formLen; p++) {
      const ion = matchedMap.get(p) ?? null;
      out.push({
        position: p,
        // Prefer the ion's actual theoretical mass (uses upstream code's
        // exact offset) when we have one; fall back to AA-table + offset.
        mass: ion?.theoreticalMass ?? cumN[p] + nOffset,
        matched: ion != null,
        matchedIon: ion,
      });
    }
    return out;
  }, [nIons, cumN, nOffset, formLen]);

  const cTicks = useMemo<LadderTick[]>(() => {
    if (cOffset == null || formLen <= 1) return [];
    const matchedMap = new Map<number, LadderIon>();
    for (const i of cIons) matchedMap.set(i.position, i);
    const out: LadderTick[] = [];
    for (let p = 1; p < formLen; p++) {
      const ion = matchedMap.get(p) ?? null;
      out.push({
        position: p,
        mass: ion?.theoreticalMass ?? cumC[p] + cOffset,
        matched: ion != null,
        matchedIon: ion,
      });
    }
    return out;
  }, [cIons, cumC, cOffset, formLen]);

  // --- deconv peaks (stick plot) ----------------------------------------
  const deconv: DeconvPeak[] = useMemo(() => {
    const out: DeconvPeak[] = [];
    for (const p of peaks) {
      if (p.monoMass == null || p.intensity == null || p.intensity <= 0) continue;
      const ion = p.matchedIons[0];
      out.push({
        mass: p.monoMass,
        intensity: p.intensity,
        matched: p.matchedIons.length > 0,
        ionType: ion?.ionType ?? null,
        position: ion?.ionDisplayPosition ?? null,
        charge: p.charge,
        ppmError: ion?.ppm ?? null,
      });
    }
    out.sort((a, b) => a.mass - b.mass);
    return out;
  }, [peaks]);

  // --- mass range --------------------------------------------------------
  // Covers both the observed peak range *and* the full calibrated ladder so
  // the user can scroll across the entire sequence coverage, not just the
  // subset that happened to match.
  const fullX = useMemo<[number, number]>(() => {
    let lo = Infinity;
    let hi = -Infinity;
    const push = (m: number) => {
      if (!Number.isFinite(m)) return;
      if (m < lo) lo = m;
      if (m > hi) hi = m;
    };
    for (const d of deconv) push(d.mass);
    for (const t of nTicks) push(t.mass);
    for (const t of cTicks) push(t.mass);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 1];
    const span = Math.max(1, hi - lo);
    const pad = Math.max(20, span * 0.02);
    return [lo - pad, hi + pad];
  }, [deconv, nTicks, cTicks]);

  const intensityMax = useMemo(() => {
    let m = 0;
    for (const d of deconv) if (d.intensity > m) m = d.intensity;
    return m > 0 ? m : 1;
  }, [deconv]);

  const ppmMax = useMemo(() => {
    let m = 0;
    for (const d of deconv) {
      if (d.ppmError != null && Math.abs(d.ppmError) > m) {
        m = Math.abs(d.ppmError);
      }
    }
    if (m <= 0) return 0.2;
    const mag = Math.pow(10, Math.floor(Math.log10(m)));
    const normalized = Math.ceil((m * 1.25) / mag) * mag;
    return normalized;
  }, [deconv]);

  // --- layout + density --------------------------------------------------
  // Default density is adaptive: aim for ~3× the current viewport width so
  // the chart is always "somewhat scrollable but not ridiculous", and the
  // user tweaks from there.
  const [density, setDensity] = useState<number | null>(null);
  const effectiveDensity = useMemo(() => {
    if (density != null) return density;
    const span = Math.max(1, fullX[1] - fullX[0]);
    const target = viewportW * 3;
    const d = target / span;
    return Math.max(0.3, Math.min(6, d));
  }, [density, fullX, viewportW]);

  const [showLines, setShowLines] = useState(true);

  const margin = { left: 64, right: 28, top: 6, bottom: 36 };
  const ladderH = 72;
  const mainH = 220;
  const gapH = 10;
  const errorH = 64;

  const innerW = Math.max(
    600,
    Math.ceil((fullX[1] - fullX[0]) * effectiveDensity),
  );
  const totalW = innerW + margin.left + margin.right;
  const totalH =
    ladderH + mainH + gapH + errorH + margin.top + margin.bottom + 12;

  // yOffsets are in the final SVG coordinate system.
  const ladderTop = margin.top;
  const mainTop = ladderTop + ladderH;
  const mainBottom = mainTop + mainH;
  const axisY = mainBottom;
  const errorTop = axisY + gapH + 18;
  const errorMid = errorTop + errorH / 2;
  const errorBottom = errorTop + errorH;

  const xScale = d3
    .scaleLinear()
    .domain(fullX)
    .range([margin.left, margin.left + innerW]);
  const yScale = d3
    .scaleLinear()
    .domain([0, intensityMax])
    .range([mainBottom, mainTop + 6]);
  const errYScale = d3
    .scaleLinear()
    .domain([-ppmMax, ppmMax])
    .range([errorBottom, errorTop]);

  const xTicks = useMemo(
    () => xScale.ticks(Math.max(6, Math.floor(innerW / 120))),
    [xScale, innerW],
  );
  const yTicks = useMemo(
    () => [0, 0.25, 0.5, 0.75, 1.0].map((f) => f * intensityMax),
    [intensityMax],
  );
  const errTicks = useMemo(
    () => [-ppmMax, -ppmMax / 2, 0, ppmMax / 2, ppmMax],
    [ppmMax],
  );

  // Two ladder rows: N-terminal ions on the upper row, C-terminal on the
  // lower row. Each row has its own tick line `yRow` and letter baseline
  // `yLetter` immediately below the ticks.
  const nIonRowY = ladderTop + 14;
  const nLetterY = nIonRowY + 18;
  const cIonRowY = ladderTop + 42;
  const cLetterY = cIonRowY + 18;

  // Decide whether there's enough horizontal room between adjacent ticks to
  // render the single-letter code without overlap. Below ~5 px we hide the
  // letters entirely rather than smear them; the ticks themselves still
  // convey coverage.
  const minLetterSpacing = 5;

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-4 text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-sm" style={{ background: "hsl(var(--ion-n))" }} />
            <span>N-term (B/C)</span>
            <span className="text-foreground">· {nIons.length}</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-sm" style={{ background: "hsl(var(--ion-c))" }} />
            <span>C-term (Y/Z)</span>
            <span className="text-foreground">· {cIons.length}</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-sm bg-muted-foreground/50" />
            unmatched · {deconv.filter((d) => !d.matched).length}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-muted-foreground">
            <span>density</span>
            <input
              type="range"
              min={0.3}
              max={6}
              step={0.1}
              value={effectiveDensity}
              onChange={(e) => setDensity(Number(e.target.value))}
              className="h-1 w-32 cursor-pointer accent-primary"
            />
            <span className="font-mono text-foreground">
              {effectiveDensity.toFixed(2)} px/Da
            </span>
            {density != null && (
              <button
                type="button"
                onClick={() => setDensity(null)}
                className="rounded border border-border px-1.5 py-0.5 text-[11px] hover:text-foreground"
              >
                auto
              </button>
            )}
          </label>
          <label className="flex items-center gap-1.5 text-muted-foreground">
            <input
              type="checkbox"
              checked={showLines}
              onChange={(e) => setShowLines(e.target.checked)}
              className="h-3.5 w-3.5 cursor-pointer accent-primary"
            />
            Show annotation lines
          </label>
        </div>
      </div>

      <div
        ref={containerRef}
        className="relative overflow-x-auto rounded-md border border-border bg-card"
      >
        {deconv.length === 0 ? (
          <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
            no deconvoluted peaks
          </div>
        ) : (
          <svg
            width={totalW}
            height={totalH}
            className="block"
            style={{ fontFamily: "Inter, sans-serif" }}
          >
            {/* -------------- Dashed annotation lines (ladder → peak) --- */}
            {showLines &&
              nTicks
                .filter((t) => t.matched && t.matchedIon)
                .map((t) => {
                  const ion = t.matchedIon!;
                  const x = xScale(t.mass);
                  const yTop = yScale(ion.intensity);
                  if (yTop - 4 <= mainTop) return null;
                  return (
                    <line
                      key={`lineN-${t.position}`}
                      x1={x}
                      x2={x}
                      y1={nIonRowY + 6}
                      y2={yTop - 3}
                      stroke="hsl(215 12% 55%)"
                      strokeWidth={1}
                      strokeDasharray="4,4"
                      opacity={0.6}
                    />
                  );
                })}
            {showLines &&
              cTicks
                .filter((t) => t.matched && t.matchedIon)
                .map((t) => {
                  const ion = t.matchedIon!;
                  const x = xScale(t.mass);
                  const yTop = yScale(ion.intensity);
                  if (yTop - 4 <= mainTop) return null;
                  return (
                    <line
                      key={`lineC-${t.position}`}
                      x1={x}
                      x2={x}
                      y1={cIonRowY + 6}
                      y2={yTop - 3}
                      stroke="hsl(215 12% 55%)"
                      strokeWidth={1}
                      strokeDasharray="4,4"
                      opacity={0.6}
                    />
                  );
                })}

            {/* -------------- Ladder rows (top) -------------- */}
            <LadderRow
              side="n"
              ticks={nTicks}
              seq={seq}
              formFirst={formFirst}
              formLast={formLast}
              xScale={xScale}
              yRow={nIonRowY}
              yLetter={nLetterY}
              minLetterSpacing={minLetterSpacing}
            />
            <LadderRow
              side="c"
              ticks={cTicks}
              seq={seq}
              formFirst={formFirst}
              formLast={formLast}
              xScale={xScale}
              yRow={cIonRowY}
              yLetter={cLetterY}
              minLetterSpacing={minLetterSpacing}
            />

            {/* -------------- Main stick plot -------------- */}
            {/* Y grid */}
            {yTicks.map((t, idx) => (
              <line
                key={`ygrid-${idx}`}
                x1={margin.left}
                x2={margin.left + innerW}
                y1={yScale(t)}
                y2={yScale(t)}
                stroke="hsl(var(--border))"
                strokeWidth={1}
                strokeDasharray="2,3"
                opacity={0.5}
              />
            ))}
            {/* Y axis */}
            <line
              x1={margin.left}
              x2={margin.left}
              y1={mainTop}
              y2={mainBottom}
              stroke="hsl(var(--border))"
            />
            {yTicks.map((t, idx) => {
              const y = yScale(t);
              const pct = intensityMax > 0 ? (t / intensityMax) * 100 : 0;
              return (
                <g key={`ylab-${idx}`}>
                  <line
                    x1={margin.left - 4}
                    x2={margin.left}
                    y1={y}
                    y2={y}
                    stroke="hsl(var(--border))"
                  />
                  <text
                    x={margin.left - 6}
                    y={y + 3}
                    textAnchor="end"
                    fontSize={10}
                    fill="hsl(var(--muted-foreground))"
                  >
                    {`${Math.round(pct)}%`}
                  </text>
                </g>
              );
            })}
            <text
              transform={`rotate(-90) translate(${-(mainTop + mainH / 2)},${margin.left - 44})`}
              textAnchor="middle"
              fontSize={11}
              fill="hsl(var(--muted-foreground))"
            >
              Intensity
            </text>

            {/* Deconv peaks: unmatched first so matched draws on top */}
            {deconv
              .filter((d) => !d.matched)
              .map((d, i) => {
                const x = xScale(d.mass);
                return (
                  <line
                    key={`u-${i}-${d.mass.toFixed(3)}`}
                    x1={x}
                    x2={x}
                    y1={yScale(0)}
                    y2={yScale(d.intensity)}
                    stroke={colorForPeak(d)}
                    strokeWidth={1}
                    opacity={0.65}
                  />
                );
              })}
            {deconv
              .filter((d) => d.matched)
              .map((d, i) => {
                const x = xScale(d.mass);
                const yTop = yScale(d.intensity);
                const color = colorForPeak(d);
                const letter = d.ionType ? displayIonLetter(d.ionType) : "";
                return (
                  <g key={`m-${i}-${d.mass.toFixed(3)}`}>
                    <line
                      x1={x}
                      x2={x}
                      y1={yScale(0)}
                      y2={yTop}
                      stroke={color}
                      strokeWidth={1.6}
                    />
                    {d.position != null && (
                      <text
                        x={x + 3}
                        y={Math.max(mainTop + 10, yTop - 4)}
                        fontSize={10}
                        fontWeight={600}
                        fontFamily="Arial, Helvetica, sans-serif"
                        fill={color}
                      >
                        {letter}
                        <tspan dy={2} fontSize={8}>
                          {d.position}
                        </tspan>
                      </text>
                    )}
                  </g>
                );
              })}

            {/* X axis for main chart */}
            <line
              x1={margin.left}
              x2={margin.left + innerW}
              y1={axisY}
              y2={axisY}
              stroke="hsl(var(--border))"
            />
            {xTicks.map((t, idx) => {
              const x = xScale(t);
              return (
                <g key={`xtick-${idx}`}>
                  <line
                    x1={x}
                    x2={x}
                    y1={axisY}
                    y2={axisY + 4}
                    stroke="hsl(var(--border))"
                  />
                  <text
                    x={x}
                    y={axisY + 16}
                    textAnchor="middle"
                    fontSize={10}
                    fill="hsl(var(--muted-foreground))"
                  >
                    {t}
                  </text>
                </g>
              );
            })}
            <text
              x={margin.left + innerW / 2}
              y={axisY + 30}
              textAnchor="middle"
              fontSize={11}
              fill="hsl(var(--muted-foreground))"
            >
              Mass (Da)
            </text>

            {/* -------------- Error plot -------------- */}
            {/* box */}
            <rect
              x={margin.left}
              y={errorTop}
              width={innerW}
              height={errorH}
              fill="none"
              stroke="hsl(var(--border))"
            />
            {/* zero dashed line */}
            <line
              x1={margin.left}
              x2={margin.left + innerW}
              y1={errorMid}
              y2={errorMid}
              stroke="hsl(215 12% 40%)"
              strokeWidth={1}
              strokeDasharray="5,4"
              opacity={0.7}
            />
            {/* y-ticks */}
            {errTicks.map((t, idx) => {
              const y = errYScale(t);
              return (
                <g key={`etick-${idx}`}>
                  <line
                    x1={margin.left - 4}
                    x2={margin.left}
                    y1={y}
                    y2={y}
                    stroke="hsl(var(--border))"
                  />
                  <text
                    x={margin.left - 6}
                    y={y + 3}
                    textAnchor="end"
                    fontSize={9}
                    fill="hsl(var(--muted-foreground))"
                  >
                    {t === 0 ? "0" : t.toFixed(ppmMax >= 1 ? 1 : 2)}
                  </text>
                </g>
              );
            })}
            <text
              transform={`rotate(-90) translate(${-(errorTop + errorH / 2)},${margin.left - 44})`}
              textAnchor="middle"
              fontSize={10}
              fill="hsl(var(--muted-foreground))"
            >
              Error (ppm)
            </text>
            {/* dots */}
            {deconv
              .filter((d) => d.matched && d.ppmError != null)
              .map((d, i) => {
                const x = xScale(d.mass);
                const y = errYScale(d.ppmError!);
                if (y < errorTop || y > errorBottom) return null;
                return (
                  <circle
                    key={`err-${i}-${d.mass.toFixed(3)}`}
                    cx={x}
                    cy={y}
                    r={2.5}
                    fill="hsl(222 47% 20%)"
                  >
                    <title>
                      mass {d.mass.toFixed(4)} · err {d.ppmError!.toFixed(2)} ppm
                      {d.ionType ? ` · ${displayIonLetter(d.ionType)}${d.position ?? ""}` : ""}
                    </title>
                  </circle>
                );
              })}
          </svg>
        )}
      </div>
    </div>
  );
}

// -------------------- helpers --------------------

/**
 * Return the average (theoreticalMass − cumulativeResidueMass) across the
 * most common ion-type group in `ions`. This is the offset constant that
 * converts a cumulative residue-mass into an actual theoretical ion mass
 * for that ion chemistry (e.g. C-ions = prefix + NH3, Z-ions = suffix + NH).
 *
 * Returns `null` if there are no matched ions to calibrate against — in
 * that case the ladder is hidden entirely, since we have no anchor.
 */
function calibrateOffset(
  ions: LadderIon[],
  cum: number[],
): number | null {
  if (ions.length === 0) return null;
  // Group by ion type, pick the largest group so a few stray
  // cross-chemistry matches don't poison the offset.
  const byType = new Map<string, LadderIon[]>();
  for (const ion of ions) {
    const lst = byType.get(ion.ionType) ?? [];
    lst.push(ion);
    byType.set(ion.ionType, lst);
  }
  let dominant: LadderIon[] = [];
  for (const lst of byType.values()) {
    if (lst.length > dominant.length) dominant = lst;
  }
  let sum = 0;
  let count = 0;
  for (const ion of dominant) {
    const base = cum[ion.position];
    if (base == null || !Number.isFinite(base)) continue;
    sum += ion.theoreticalMass - base;
    count++;
  }
  if (count === 0) return null;
  return sum / count;
}

interface LadderRowProps {
  side: "n" | "c";
  ticks: LadderTick[];
  seq: string;
  formFirst: number;
  formLast: number;
  xScale: d3.ScaleLinear<number, number>;
  yRow: number;
  yLetter: number;
  minLetterSpacing: number;
}

/**
 * Renders one of the two ladder rows: tick at every position plus the
 * gained amino-acid letter between adjacent ticks. Matched ticks use the
 * ion-side colour; unmatched ones are muted so coverage is obvious at a
 * glance.
 */
function LadderRow({
  side,
  ticks,
  seq,
  formFirst,
  formLast,
  xScale,
  yRow,
  yLetter,
  minLetterSpacing,
}: LadderRowProps) {
  if (ticks.length === 0) return null;
  const matchedColor = colorForSide(side);
  const mutedColor = "hsl(215 14% 72%)";
  return (
    <g className={`ladder-row ladder-${side}`}>
      {ticks.map((t) => {
        const x = xScale(t.mass);
        const color = t.matched ? matchedColor : mutedColor;
        return (
          <line
            key={`tick-${side}-${t.position}`}
            x1={x}
            x2={x}
            y1={yRow - 6}
            y2={yRow + 4}
            stroke={color}
            strokeWidth={t.matched ? 1.4 : 1}
          />
        );
      })}
      {ticks.slice(0, -1).map((t, idx) => {
        const nextT = ticks[idx + 1];
        const xLeft = xScale(t.mass);
        const xRight = xScale(nextT.mass);
        const gap = xRight - xLeft;
        if (gap < minLetterSpacing) return null;
        // The letter added going from position p → p+1:
        //   N-ion: residue immediately after the prefix = seq[formFirst + p]
        //   C-ion: residue immediately before the suffix = seq[formLast - p]
        const letter =
          side === "n"
            ? (seq[formFirst + t.position] ?? "")
            : (seq[formLast - t.position] ?? "");
        if (!letter) return null;
        return (
          <text
            key={`aa-${side}-${t.position}`}
            x={(xLeft + xRight) / 2}
            y={yLetter}
            textAnchor="middle"
            fontSize={11}
            fontFamily="FreeMono, Consolas, monospace"
            fill="hsl(222 47% 14%)"
          >
            {letter}
          </text>
        );
      })}
    </g>
  );
}
