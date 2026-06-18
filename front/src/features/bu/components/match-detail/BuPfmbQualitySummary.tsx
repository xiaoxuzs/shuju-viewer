import { useMemo } from "react";
import { AlertTriangle } from "lucide-react";

import { cn } from "@/lib/utils";
import type { BuMs2AnnotationMatrixOut, BuMs2AnnotationOut } from "@/features/bu/types";
import { formatCount, formatDecimal } from "@/features/bu/utils";
import { calculatePfmbCoverage } from "@/features/bu/components/match-detail/evidenceSummaryModel";
import {
  PFMB_SERIES_COLOR,
  seriesLabel,
  type PfmbIonType,
} from "@/features/bu/components/match-detail/pfmbSeries";

const SERIES_ORDER: PfmbIonType[] = ["b", "y", "c", "z_dot"];
const PPM_BINS = 12;

function quantile(sorted: number[], q: number): number {
  if (sorted.length === 0) return NaN;
  if (sorted.length === 1) return sorted[0];
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  const next = sorted[base + 1];
  return next === undefined ? sorted[base] : sorted[base] + rest * (next - sorted[base]);
}

export function BuPfmbQualitySummary({
  annotation,
  matrix,
  selectedRt,
  onSelectRt,
  compact = false,
}: {
  annotation: BuMs2AnnotationOut;
  matrix?: BuMs2AnnotationMatrixOut;
  selectedRt: number | null;
  onSelectRt: (rt: number) => void;
  compact?: boolean;
}) {
  const ions = annotation.matched_ions;
  const coverage = useMemo(
    () => calculatePfmbCoverage(annotation.peptide, annotation),
    [annotation],
  );

  const ppm = useMemo(() => {
    const values = ions.map((i) => i.mass_error_ppm).filter((v) => Number.isFinite(v));
    if (values.length === 0) return null;
    const sorted = [...values].sort((a, b) => a - b);
    const min = sorted[0];
    const max = sorted[sorted.length - 1];
    const span = max - min || 1;
    const bins = new Array(PPM_BINS).fill(0);
    for (const v of sorted) {
      const idx = Math.min(PPM_BINS - 1, Math.floor(((v - min) / span) * PPM_BINS));
      bins[idx] += 1;
    }
    return {
      median: quantile(sorted, 0.5),
      q1: quantile(sorted, 0.25),
      q3: quantile(sorted, 0.75),
      min,
      max,
      bins,
      n: sorted.length,
    };
  }, [ions]);

  const series = useMemo(() => {
    const count: Record<PfmbIonType, number> = { b: 0, y: 0, c: 0, z_dot: 0 };
    for (const ion of ions) {
      count[ion.ion_type] += 1;
    }
    const maxCount = Math.max(1, ...SERIES_ORDER.map((t) => count[t]));
    return { count, maxCount };
  }, [ions]);

  const uniquePeakIntensity = useMemo(() => {
    const byPeak = new Map<number, number>();
    for (const ion of ions) {
      byPeak.set(ion.peak_id, Math.max(byPeak.get(ion.peak_id) ?? 0, ion.intensity));
    }
    return {
      peakCount: byPeak.size,
      total: [...byPeak.values()].reduce((sum, intensity) => sum + intensity, 0),
    };
  }, [ions]);

  const trend = matrix?.slot_summary ?? [];

  return (
    <div className="mb-4 space-y-3" data-testid="pfmb-quality-summary">
      <div
        className="flex items-start gap-2 rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-500/40 dark:bg-amber-950/40 dark:text-amber-200"
        data-testid="pfmb-quality-disclaimer"
      >
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        <span>
          Peak match rate is not identification accuracy. These counts describe fragment evidence
          only; intensity sums cover matched peaks (not a true TIC) and about a third of matched ions
          can have zero intensity.
        </span>
      </div>

      <div className={cn("grid grid-cols-1 gap-3", !compact && "sm:grid-cols-3")}>
        {/* Fragment coverage (theoretical cleavage-site coverage, not a peak match rate) */}
        <div className="rounded-md border border-border p-2" data-testid="pfmb-quality-coverage">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Fragment coverage</div>
          {coverage ? (
            <>
              <div className="text-lg font-semibold tabular-nums" data-testid="pfmb-coverage-pct">
                {(coverage.ratio * 100).toFixed(0)}%
              </div>
              <div className="text-[11px] text-muted-foreground">
                {coverage.covered}/{coverage.total} cleavage sites covered
              </div>
            </>
          ) : (
            <div className="text-xs text-muted-foreground">n/a</div>
          )}
        </div>

        {/* ppm distribution */}
        <div className="rounded-md border border-border p-2" data-testid="pfmb-quality-ppm">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">ppm distribution</div>
          {ppm ? (
            <>
              <div className="text-lg font-semibold tabular-nums" data-testid="pfmb-ppm-median">
                {formatDecimal(ppm.median, 2)}
              </div>
              <div className="text-[11px] text-muted-foreground">
                median; IQR {formatDecimal(ppm.q1, 2)}..{formatDecimal(ppm.q3, 2)}; range{" "}
                {formatDecimal(ppm.min, 2)}..{formatDecimal(ppm.max, 2)}
              </div>
              <Histogram bins={ppm.bins} />
            </>
          ) : (
            <div className="text-xs text-muted-foreground">n/a</div>
          )}
        </div>

        {/* series counts */}
        <div className="rounded-md border border-border p-2" data-testid="pfmb-quality-series">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Series counts (b/y/c/z.)</div>
          <div className="mt-1 space-y-1">
            {SERIES_ORDER.map((t) => (
              <div key={t} className="flex items-center gap-2" data-testid="pfmb-series-row" data-series={t}>
                <span className="w-6 font-mono text-xs" style={{ color: PFMB_SERIES_COLOR[t] }}>
                  {seriesLabel(t)}
                </span>
                <span className="h-2 flex-1 overflow-hidden rounded-sm bg-muted">
                  <span
                    className="block h-full"
                    style={{ width: `${(series.count[t] / series.maxCount) * 100}%`, backgroundColor: PFMB_SERIES_COLOR[t] }}
                  />
                </span>
                <span className="w-6 text-right font-mono text-xs tabular-nums">{series.count[t]}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Unique physical peaks only; multiple fragment annotations may share a peak_id. */}
      <div data-testid="pfmb-quality-intensity">
        <div className="mb-1 text-[11px] uppercase tracking-wider text-muted-foreground">
          Unique matched-peak intensity sum <span className="normal-case">(not a true TIC)</span>
        </div>
        <div className="text-lg font-semibold tabular-nums" data-testid="pfmb-unique-peak-intensity">
          {formatCount(uniquePeakIntensity.total)}
        </div>
        <div className="text-[11px] text-muted-foreground">
          {formatCount(uniquePeakIntensity.peakCount)} unique peak IDs; duplicate fragment annotations are counted once.
        </div>
      </div>

      {/* per-slot trend */}
      {trend.length > 0 && (
        <SlotTrend
          trend={trend}
          apexSlot={matrix?.apex_slot ?? null}
          selectedRt={selectedRt}
          onSelectRt={onSelectRt}
        />
      )}
    </div>
  );
}

function Histogram({ bins }: { bins: number[] }) {
  const max = Math.max(1, ...bins);
  return (
    <div className="mt-1 flex h-8 items-end gap-px" aria-hidden data-testid="pfmb-ppm-histogram">
      {bins.map((count, i) => (
        <span
          key={i}
          className="flex-1 rounded-sm bg-primary/60"
          style={{ height: `${(count / max) * 100}%`, minHeight: count > 0 ? 2 : 0 }}
        />
      ))}
    </div>
  );
}

function SlotTrend({
  trend,
  apexSlot,
  selectedRt,
  onSelectRt,
}: {
  trend: BuMs2AnnotationMatrixOut["slot_summary"];
  apexSlot: number | null;
  selectedRt: number | null;
  onSelectRt: (rt: number) => void;
}) {
  const W = Math.max(160, trend.length * 16);
  const H = 56;
  const padX = 6;
  const padY = 8;
  const maxVal = Math.max(1, ...trend.map((s) => s.matched_peak_count));
  const stepX = trend.length > 1 ? (W - 2 * padX) / (trend.length - 1) : 0;
  const x = (i: number) => padX + i * stepX;
  const y = (v: number) => H - padY - (v / maxVal) * (H - 2 * padY);

  const currentIndex = useMemo(() => {
    if (selectedRt == null) return trend.findIndex((s) => s.slot_index === apexSlot);
    let best = -1;
    let bestD = Infinity;
    trend.forEach((s, i) => {
      const d = Math.abs(s.rt_minutes - selectedRt);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    return best;
  }, [trend, selectedRt, apexSlot]);

  const path = trend.map((s, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(s.matched_peak_count)}`).join(" ");

  return (
    <div data-testid="pfmb-quality-trend">
      <div className="mb-1 text-[11px] uppercase tracking-wider text-muted-foreground">
        PFMB matched peaks per RT slot
      </div>
      <svg width={W} height={H} role="img" aria-label="PFMB matched peaks per RT slot">
        <path d={path} fill="none" stroke="hsl(var(--primary))" strokeWidth={1.5} opacity={0.7} />
        {trend.map((s, i) => {
          const isApex = s.slot_index === apexSlot;
          const isCurrent = i === currentIndex;
          return (
            <circle
              key={s.prsm_index}
              data-testid="pfmb-trend-point"
              data-slot={s.slot_index}
              data-apex={isApex ? "true" : "false"}
              data-current={isCurrent ? "true" : "false"}
              cx={x(i)}
              cy={y(s.matched_peak_count)}
              r={isCurrent ? 4 : isApex ? 3.2 : 2.4}
              fill={isCurrent ? "hsl(var(--primary))" : isApex ? "hsl(var(--background))" : "hsl(var(--muted-foreground))"}
              stroke={isApex || isCurrent ? "hsl(var(--primary))" : "none"}
              strokeWidth={isApex || isCurrent ? 1.4 : 0}
              className={cn("cursor-pointer")}
              onClick={() => onSelectRt(s.rt_minutes)}
            >
              <title>{`Slot ${s.slot_index} (PFMB slot RT ${s.rt_minutes.toFixed(2)} min): ${formatCount(s.matched_peak_count)} PFMB matched peaks${isApex ? " [PFMB apex]" : ""}`}</title>
            </circle>
          );
        })}
      </svg>
    </div>
  );
}
