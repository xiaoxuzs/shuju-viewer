/**
 * Local MS2 view for one matched deconv peak. Mirrors the original TopMSV
 * viewer: the X window equals the matched envelope's m/z span, every
 * isotope peak (`env_peaks`) gets a hollow ring, the tallest one carries
 * the ion annotation (e.g. `Z• 19`), and the Y axis is rendered in
 * percent of the local maximum.
 */
import { useMemo, useState } from "react";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { formatNumber } from "@/lib/utils";
import {
  findMatchedEnvelope,
  type MatchedIon,
  type MsPeakRow,
  type RawEnvelope,
  type RawSpectrum,
} from "@/features/prsm/parse";
import {
  DEFAULT_ZOOM,
  SpectrumChart,
  type ChartPeak,
  type EnvelopeOverlayPoint,
  type Zoom,
} from "@/features/prsm/SpectrumChart";

interface Props {
  selection: { peak: MsPeakRow; ion: MatchedIon } | null;
  ms2ChartPeaks: ChartPeak[];
  ms2RawSpectrum: RawSpectrum | null;
  ms2ScanLabel: string;
  onClose: () => void;
}

const N_ION_TYPES = new Set(["B", "C", "A"]);
const C_ION_TYPES = new Set(["Y", "Z", "Z_DOT", "X"]);

function ionColorFor(ionType: string): string {
  if (N_ION_TYPES.has(ionType)) return "hsl(var(--ion-n))";
  if (C_ION_TYPES.has(ionType)) return "hsl(var(--ion-c))";
  return "hsl(var(--ion-shift))";
}

function ionLetter(ionType: string): string {
  if (ionType === "Z_DOT") return "Z\u2022";
  return ionType;
}

/** Centroid-only fallback when no envelope is found. */
function fallbackWindow(center: number): [number, number] {
  const half = Math.max(3, center * 0.003);
  return [center - half, center + half];
}

/** Window covering an envelope's isotope cluster with a small margin. */
function envelopeWindow(env: RawEnvelope): [number, number] | null {
  if (env.envPeaks.length === 0) return null;
  let lo = Infinity;
  let hi = -Infinity;
  for (const p of env.envPeaks) {
    if (p.mz < lo) lo = p.mz;
    if (p.mz > hi) hi = p.mz;
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null;
  const span = Math.max(hi - lo, 0.5);
  const margin = Math.max(0.3, span * 0.3);
  return [lo - margin, hi + margin];
}

export function MatchedPeakSpectrumPanel({
  selection,
  ms2ChartPeaks,
  ms2RawSpectrum,
  ms2ScanLabel,
  onClose,
}: Props) {
  const [tab, setTab] = useState<"scan" | "masses">("scan");
  const [showGuides, setShowGuides] = useState(true);
  const [zoom, setZoom] = useState<Zoom>(DEFAULT_ZOOM);

  const envelope = useMemo(
    () => findMatchedEnvelope(ms2RawSpectrum, selection?.peak ?? null),
    [ms2RawSpectrum, selection?.peak],
  );

  const centerMz = selection?.peak.monoMz ?? null;

  const xDomain = useMemo<[number, number] | null>(() => {
    if (envelope) {
      const w = envelopeWindow(envelope);
      if (w) return w;
    }
    if (centerMz != null && Number.isFinite(centerMz)) return fallbackWindow(centerMz);
    return null;
  }, [envelope, centerMz]);

  const overlayPoints = useMemo<EnvelopeOverlayPoint[]>(() => {
    if (!envelope || !selection) return [];
    const color = ionColorFor(selection.ion.ionType);
    const labelText = `${ionLetter(selection.ion.ionType)} ${selection.ion.ionDisplayPosition}`;
    let maxIdx = 0;
    for (let i = 1; i < envelope.envPeaks.length; i++) {
      if (envelope.envPeaks[i].intensity > envelope.envPeaks[maxIdx].intensity) maxIdx = i;
    }
    return envelope.envPeaks.map((p, i) => ({
      mz: p.mz,
      intensity: p.intensity,
      color,
      label: i === maxIdx ? labelText : undefined,
    }));
  }, [envelope, selection]);

  const annotationGuidesMz = useMemo(() => {
    if (!showGuides) return [] as number[];
    if (envelope && envelope.envPeaks.length > 0) {
      return envelope.envPeaks.map((p) => p.mz);
    }
    if (!selection || !xDomain) return [] as number[];
    const [x0, x1] = xDomain;
    const seen = new Set<number>();
    const out: number[] = [];
    for (const p of ms2ChartPeaks) {
      if (!p.ion) continue;
      if (p.mz < x0 || p.mz > x1) continue;
      const k = Math.round(p.mz * 1e6) / 1e6;
      if (seen.has(k)) continue;
      seen.add(k);
      out.push(p.mz);
    }
    return out;
  }, [showGuides, envelope, selection, ms2ChartPeaks, xDomain]);

  const yPercentBase = useMemo(() => {
    if (!xDomain) return null;
    const [x0, x1] = xDomain;
    let max = 0;
    for (const p of ms2ChartPeaks) {
      if (p.mz < x0 || p.mz > x1) continue;
      if (p.intensity > max) max = p.intensity;
    }
    if (envelope) {
      for (const p of envelope.envPeaks) {
        if (p.intensity > max) max = p.intensity;
      }
    }
    return max > 0 ? max : null;
  }, [xDomain, ms2ChartPeaks, envelope]);

  type MassRow = { mz: number; intensity: number; isApex: boolean };
  const massesInView = useMemo<MassRow[]>(() => {
    if (envelope && envelope.envPeaks.length > 0) {
      const sorted = envelope.envPeaks.slice().sort((a, b) => a.mz - b.mz);
      let apex = 0;
      for (let i = 1; i < sorted.length; i++) {
        if (sorted[i].intensity > sorted[apex].intensity) apex = i;
      }
      return sorted.map((p, i) => ({ mz: p.mz, intensity: p.intensity, isApex: i === apex }));
    }
    if (!xDomain) return [];
    const [x0, x1] = xDomain;
    return ms2ChartPeaks
      .filter((p) => p.mz >= x0 && p.mz <= x1)
      .slice()
      .sort((a, b) => a.mz - b.mz)
      .map((p) => ({ mz: p.mz, intensity: p.intensity, isApex: false }));
  }, [envelope, ms2ChartPeaks, xDomain]);

  if (!selection || !xDomain) return null;

  const { peak, ion } = selection;
  const scanTitle = ms2ScanLabel.trim() || "MS2";

  return (
    <div className="mt-4 rounded-lg border border-border bg-muted/20 p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Peak detail · local m/z</h3>
          <p className="mt-1 font-mono text-xs text-muted-foreground">
            Peak {Number.isFinite(peak.peakId) ? peak.peakId + 1 : "—"} · m/z {formatNumber(peak.monoMz, 4)} ·{" "}
            mono mass {formatNumber(peak.monoMass, 4)} ·{" "}
            {ion.ionType.replace("_DOT", "·")} pos {ion.ionDisplayPosition}
          </p>
        </div>
        <Button type="button" variant="ghost" size="sm" className="h-8 shrink-0 gap-1 px-2" onClick={onClose}>
          <X className="h-4 w-4" />
          Close
        </Button>
      </div>

      <dl className="mb-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4 lg:grid-cols-6">
        <div>
          <dt className="text-muted-foreground">Charge</dt>
          <dd className="font-mono tabular-nums">{peak.charge ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Intensity</dt>
          <dd className="font-mono tabular-nums">{formatNumber(peak.intensity, 2)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Theo. mass</dt>
          <dd className="font-mono tabular-nums">{formatNumber(ion.theoreticalMass, 4)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Mass err</dt>
          <dd className="font-mono tabular-nums">{formatNumber(ion.massError, 4)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">ppm</dt>
          <dd className="font-mono tabular-nums">{formatNumber(ion.ppm, 2)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Isotopes</dt>
          <dd className="font-mono tabular-nums">{envelope ? envelope.envPeaks.length : 0}</dd>
        </div>
      </dl>

      <div className="mb-2 flex flex-wrap items-center gap-2 border-b border-border/60 pb-2">
        <button
          type="button"
          onClick={() => setTab("scan")}
          className={`rounded-md border px-2.5 py-1 text-xs ${
            tab === "scan"
              ? "border-primary/50 bg-primary/10 text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          {scanTitle}
        </button>
        <button
          type="button"
          onClick={() => setTab("masses")}
          className={`rounded-md border px-2.5 py-1 text-xs ${
            tab === "masses"
              ? "border-primary/50 bg-primary/10 text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          {scanTitle} masses
        </button>
        {tab === "scan" && (
          <label className="ml-auto flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              className="rounded border-border"
              checked={showGuides}
              onChange={(e) => setShowGuides(e.target.checked)}
            />
            Show annotation lines
          </label>
        )}
      </div>

      {tab === "scan" ? (
        ms2ChartPeaks.length === 0 ? (
          <p className="text-sm text-muted-foreground">No MS2 spectrum loaded.</p>
        ) : (
          <SpectrumChart
            peaks={ms2ChartPeaks}
            xLabel="M/Z"
            yLabel="Intensity"
            height={260}
            xDomain={xDomain}
            envelopeOverlay={overlayPoints}
            yPercentBase={yPercentBase}
            annotationGuidesMz={annotationGuidesMz}
            zoom={zoom}
            onZoomChange={setZoom}
            emptyHint="no peaks in window"
          />
        )
      ) : (
        <div className="max-h-[280px] overflow-auto rounded-md border border-border">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 z-10 border-b border-border bg-card">
              <tr className="text-muted-foreground">
                <th className="px-2 py-2 font-medium">m/z</th>
                <th className="px-2 py-2 font-medium text-right">Intensity</th>
                <th className="px-2 py-2 font-medium text-right">% base</th>
                <th className="px-2 py-2 font-medium">Note</th>
              </tr>
            </thead>
            <tbody>
              {massesInView.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-2 py-3 text-center text-muted-foreground">
                    no peaks in window
                  </td>
                </tr>
              ) : (
                massesInView.map((p, i) => {
                  const pct =
                    yPercentBase && yPercentBase > 0
                      ? `${((p.intensity / yPercentBase) * 100).toFixed(1)}%`
                      : "—";
                  return (
                    <tr
                      key={`${p.mz}-${i}`}
                      className={
                        p.isApex
                          ? "bg-primary/10 font-medium"
                          : "border-b border-border/40 hover:bg-muted/40"
                      }
                    >
                      <td className="px-2 py-1 font-mono tabular-nums">{formatNumber(p.mz, 4)}</td>
                      <td className="px-2 py-1 text-right font-mono tabular-nums">
                        {formatNumber(p.intensity, 2)}
                      </td>
                      <td className="px-2 py-1 text-right font-mono tabular-nums">{pct}</td>
                      <td className="px-2 py-1 font-mono text-[11px]">
                        {p.isApex ? `${ionLetter(ion.ionType)} ${ion.ionDisplayPosition}` : ""}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
