/**
 * PrSM 详情：聚合 PrSM JSON、MS1/MS2 原始谱与解析结果，渲染序列、谱图、
 * 碎片化视图、匹配峰表及全屏谱图模态框；内联注释说明 zoom 与数据流。
 */
import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";

import { fetchDataset, fetchMs1Spectrum, fetchMs2Spectrum, fetchMzmlSpectrum, fetchPrsm } from "@/api/client";
import { DataEmptyState, DataLoadError } from "@/components/common/data-state";
import { PageLoading } from "@/components/common/page-loading";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/common/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { Stat } from "@/components/common/stat";
import { Badge } from "@/components/ui/badge";
import { formatEValue, formatNumber } from "@/lib/utils";

import {
  matchedPeakDetailKey,
  parseAnnotatedProtein,
  parseMsPeaks,
  parseRawSpectrum,
  type MatchedIon,
  type MsPeakRow,
  type RawSpectrum,
} from "@/features/prsm/parse";
import { SequenceView } from "@/features/prsm/SequenceView";
import {
  DEFAULT_ZOOM,
  SpectrumChart,
  isZoomed,
  type ChartPeak,
  type Zoom,
} from "@/features/prsm/SpectrumChart";
import { SpectrumModal } from "@/features/prsm/SpectrumModal";
import { MatchedPeakSpectrumPanel } from "@/features/prsm/MatchedPeakSpectrumPanel";
import { MatchedPeaksTable } from "@/features/prsm/MatchedPeaksTable";
import { FragmentationView } from "@/features/prsm/FragmentationView";
import { Lcms3DPanel } from "@/features/lcms3d/Lcms3DPanel";

type Marker = { x: number; label: string } | null;

/** MS1/MS2 charts: global base-peak normalization vs raw intensity axis. */
type SpectrumIntensityMode = "absolute" | "percent";

function useModalHeight() {
  const compute = () =>
    typeof window === "undefined" ? 600 : Math.max(360, Math.floor(window.innerHeight * 0.72));
  const [h, setH] = useState(compute);
  useEffect(() => {
    const onResize = () => setH(compute());
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return h;
}

export function PrsmDetailPage() {
  const { slug = "", cutoff = "", prsmId = "" } = useParams();
  const prsmIdNum = Number(prsmId);

  useLayoutEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [slug, cutoff, prsmId]);

  const prsmQuery = useQuery({
    queryKey: ["prsm", slug, cutoff, prsmIdNum],
    queryFn: () => fetchPrsm(slug, cutoff, prsmIdNum),
    enabled: Number.isFinite(prsmIdNum),
  });

  const prsm = prsmQuery.data;
  const datasetQuery = useQuery({
    queryKey: ["dataset", slug],
    queryFn: () => fetchDataset(slug),
    enabled: Boolean(slug),
    // Keep the resolved source stable while the detail page mounts; the LC-MS
    // panel is disabled until this is known, so it never fires a wrong default request.
    staleTime: 5 * 60_000,
  });
  const spectraSource = useMemo(() => {
    if (!datasetQuery.data) return null;
    return (datasetQuery.data.capabilities?.["spectra_source"] as string | undefined) ?? "topfd_js";
  }, [datasetQuery.data]);
  const spectraSourceReady = spectraSource != null;

  const parsed = useMemo(() => {
    if (!prsm) return null;
    return {
      protein: parseAnnotatedProtein(prsm.annotated_protein),
      peaks: parseMsPeaks(prsm.ms_peaks),
    };
  }, [prsm]);

  const ms1Id = prsm?.ms1_ids ? Number(prsm.ms1_ids.split(/[;, ]+/)[0]) : null;
  const ms2Id = prsm?.ms2_ids ? Number(prsm.ms2_ids.split(/[;, ]+/)[0]) : null;
  const ms1Scan = prsm?.ms1_scans ? Number(prsm.ms1_scans.split(/[;, ]+/)[0]) : null;
  const ms2Scan = prsm?.ms2_scans ? Number(prsm.ms2_scans.split(/[;, ]+/)[0]) : null;

  const ms1Query = useQuery({
    queryKey: ["ms1", spectraSource, slug, prsm?.run_id, ms1Id, ms1Scan],
    queryFn: () => {
      if (!prsm) throw new Error("missing prsm");
      if (spectraSource === "mzml_memory") {
        if (ms1Scan == null || !Number.isFinite(ms1Scan)) throw new Error("missing ms1 scan");
        return fetchMzmlSpectrum(prsm.dataset_id, prsm.run_id, ms1Scan);
      }
      return fetchMs1Spectrum(slug, ms1Id as number);
    },
    enabled:
      Boolean(prsm) &&
      spectraSourceReady &&
      (spectraSource === "mzml_memory"
        ? ms1Scan != null && Number.isFinite(ms1Scan)
        : ms1Id != null && Number.isFinite(ms1Id)),
  });
  const ms2Query = useQuery({
    queryKey: ["ms2", spectraSource, slug, prsm?.run_id, ms2Id, ms2Scan],
    queryFn: () => {
      if (!prsm) throw new Error("missing prsm");
      if (spectraSource === "mzml_memory") {
        if (ms2Scan == null || !Number.isFinite(ms2Scan)) throw new Error("missing ms2 scan");
        return fetchMzmlSpectrum(prsm.dataset_id, prsm.run_id, ms2Scan);
      }
      return fetchMs2Spectrum(slug, ms2Id as number);
    },
    enabled:
      Boolean(prsm) &&
      spectraSourceReady &&
      (spectraSource === "mzml_memory"
        ? ms2Scan != null && Number.isFinite(ms2Scan)
        : ms2Id != null && Number.isFinite(ms2Id)),
  });

  // Memoize the chart-peak arrays so the inline and modal charts share the
  // same reference (and thus don't each trigger their own resets).
  const ms1ChartPeaks = useMemo(
    () => buildRawChartPeaks(ms1Query.data),
    [ms1Query.data],
  );
  const ms1RawSpectrum = useMemo<RawSpectrum | null>(
    () => parseRawSpectrum(ms1Query.data ?? null),
    [ms1Query.data],
  );
  const ms2RawSpectrum = useMemo<RawSpectrum | null>(
    () => parseRawSpectrum(ms2Query.data ?? null),
    [ms2Query.data],
  );
  const ms2ChartPeaks = useMemo(
    () => buildMs2ChartPeaks(ms2RawSpectrum, parsed?.peaks ?? []),
    [ms2RawSpectrum, parsed?.peaks],
  );

  // Zoom state: the inline and modal views have independent state so the
  // modal can remember its zoom across open/close cycles without affecting
  // the small inline chart.
  const [ms1ModalZoom, setMs1ModalZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const [ms2ModalZoom, setMs2ModalZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const [ms1ModalOpen, setMs1ModalOpen] = useState(false);
  const [ms2ModalOpen, setMs2ModalOpen] = useState(false);
  const [peakDetail, setPeakDetail] = useState<{ peak: MsPeakRow; ion: MatchedIon } | null>(null);
  const [spectrumIntensityMode, setSpectrumIntensityMode] =
    useState<SpectrumIntensityMode>("percent");
  const modalChartHeight = useModalHeight();

  const ms2ScanLabel = useMemo(() => {
    const raw = prsm?.ms2_scans?.trim();
    if (!raw) return "Scan";
    const first = raw.split(/[;,]/)[0]?.trim();
    return first ? `Scan ${first}` : "Scan";
  }, [prsm?.ms2_scans]);

  // Reset zoom only when the underlying spectrum actually changes (i.e. a
  // different scan loaded). This keeps the modal zoom stable across
  // open/close events, which only change `ms1ModalOpen`/`ms2ModalOpen`.
  useEffect(() => {
    setMs1ModalZoom(DEFAULT_ZOOM);
  }, [spectraSource === "mzml_memory" ? ms1Scan : ms1Id]);
  useEffect(() => {
    setMs2ModalZoom(DEFAULT_ZOOM);
    setPeakDetail(null);
  }, [spectraSource === "mzml_memory" ? ms2Scan : ms2Id]);

  useEffect(() => {
    setPeakDetail(null);
  }, [prsmIdNum]);

  useEffect(() => {
    setMs1ModalZoom(DEFAULT_ZOOM);
    setMs2ModalZoom(DEFAULT_ZOOM);
  }, [spectrumIntensityMode]);

  const precursorMarker: Marker = prsm?.precursor_mz
    ? { x: prsm.precursor_mz, label: `precursor ${formatNumber(prsm.precursor_mz, 4)}` }
    : null;

  // ----- loading / error states -----
  if (prsmQuery.isLoading) {
    return <PageLoading />;
  }

  if (prsmQuery.isError && !prsm) {
    return <DataLoadError />;
  }

  if (!prsm) return <DataEmptyState />;

  return (
    <>
      <PageHeader
        title={`PrSM #${prsm.prsm_id}`}
        description={parsed?.protein?.sequenceName ?? prsm.spectrum_file_name ?? undefined}
        crumbs={[
          { label: "Datasets", to: "/datasets" },
          { label: slug, to: `/datasets/${slug}` },
          { label: "PrSMs", to: `/datasets/${slug}/${cutoff}/prsms` },
          { label: `PrSM #${prsm.prsm_id}` },
        ]}
        actions={
          <div className="flex items-center gap-2">
            <Badge variant="outline">
              <Link to={`/datasets/${slug}/${cutoff}/proteoforms/${prsm.proteoform_id}`}>
                ← proteoform #{parsed?.protein?.proteoformId ?? ""}
              </Link>
            </Badge>
          </div>
        }
      />

      {/* Stat cards */}
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        <Stat label="e-value" value={formatEValue(prsm.e_value)} />
        <Stat label="p-value" value={formatEValue(prsm.p_value)} />
        <Stat label="Matched frag" value={prsm.matched_fragment_number ?? "—"} />
        <Stat label="Matched peaks" value={prsm.matched_peak_number ?? "—"} />
        <Stat label="Precursor m/z" value={formatNumber(prsm.precursor_mz, 4)} />
        <Stat label="Charge" value={prsm.precursor_charge ?? "—"} />
      </div>

      {/* Sequence view */}
      {parsed?.protein && (
        <Card className="mb-6">
          <CardHeader className="flex flex-row items-start justify-between gap-4">
            <div>
              <CardTitle className="text-base">Sequence coverage</CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                {parsed.protein.sequenceDescription ?? parsed.protein.sequenceName}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>
                length <span className="text-foreground">{parsed.protein.proteinLength}</span>
              </span>
              <span>·</span>
              <span>
                proteoform mass{" "}
                <span className="font-mono text-foreground">
                  {formatNumber(parsed.protein.proteoformMass, 4)}
                </span>
              </span>
              {parsed.protein.unexpectedShiftNumber != null && (
                <>
                  <span>·</span>
                  <span>
                    unexpected shifts{" "}
                    <span className="text-foreground">
                      {parsed.protein.unexpectedShiftNumber}
                    </span>
                  </span>
                </>
              )}
            </div>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <SequenceView protein={parsed.protein} />
          </CardContent>
        </Card>
      )}

      {/* MS1 + MS2 spectra side by side */}
      <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">MS1 / MS2 Y axis</span>
        <div className="inline-flex rounded-md border border-border bg-muted/30 p-0.5">
          <button
            type="button"
            onClick={() => setSpectrumIntensityMode("percent")}
            className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
              spectrumIntensityMode === "percent"
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            Relative abundance (%)
          </button>
          <button
            type="button"
            onClick={() => setSpectrumIntensityMode("absolute")}
            className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
              spectrumIntensityMode === "absolute"
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            Absolute intensity
          </button>
        </div>
        <span className="text-xs text-muted-foreground">
          Percent mode: full-spectrum base peak = 100% (publication-style).
        </span>
      </div>
      <div className="mb-6 grid gap-4 xl:grid-cols-5">
        <Card className="xl:col-span-2">
          <CardHeader className="flex flex-row items-baseline justify-between gap-3">
            <CardTitle className="text-base">MS1 precursor</CardTitle>
            <span className="font-mono text-xs text-muted-foreground">
              scan {prsm.ms1_scans ?? "—"} · id {prsm.ms1_ids ?? "—"}
            </span>
          </CardHeader>
          <CardContent>
            {ms1Query.isLoading ? (
              <Skeleton className="h-[240px]" />
            ) : ms1Query.isError ? (
              <DataLoadError compact />
            ) : (
              <SpectrumChart
                key={`ms1-inline-${spectraSource}-${ms1Scan ?? ms1Id ?? "none"}-${spectrumIntensityMode}`}
                peaks={ms1ChartPeaks}
                xLabel="m/z (MS1)"
                yLabel="intensity"
                yIntensityScale={spectrumIntensityMode}
                height={260}
                marker={precursorMarker}
                emptyHint="no MS1 peaks"
                onOpenFull={() => setMs1ModalOpen(true)}
              />
            )}
          </CardContent>
        </Card>

        <Card className="xl:col-span-3">
          <CardHeader className="flex flex-row items-baseline justify-between gap-3">
            <CardTitle className="text-base">MS2 fragment spectrum</CardTitle>
            <span className="font-mono text-xs text-muted-foreground">
              scan {prsm.ms2_scans ?? "—"} · id {prsm.ms2_ids ?? "—"} · wheel to zoom (Shift = Y) · brush-drag = X
            </span>
          </CardHeader>
          <CardContent>
            {ms2Query.isLoading ? (
              <Skeleton className="h-[260px]" />
            ) : ms2Query.isError ? (
              <DataLoadError compact />
            ) : (
              <SpectrumChart
                key={`ms2-inline-${spectraSource}-${ms2Scan ?? ms2Id ?? "none"}-${spectrumIntensityMode}`}
                peaks={ms2ChartPeaks}
                xLabel="m/z (MS2)"
                yLabel="intensity"
                yIntensityScale={spectrumIntensityMode}
                height={320}
                emptyHint="no MS2 peaks"
                onOpenFull={() => setMs2ModalOpen(true)}
              />
            )}
          </CardContent>
        </Card>
      </div>

      {/* MS/MS fragmentation + sequence ladder + error plot. Long chart,
          so it has its own horizontal scrollbar and a density slider rather
          than wheel zoom. Sits right below MS1/MS2 to make the connection
          between raw peaks and matched ions obvious. */}
      {parsed?.protein && parsed.peaks.length > 0 && (
        <Card className="mb-6">
          <CardHeader className="flex flex-row items-baseline justify-between gap-3">
            <div>
              <CardTitle className="text-base">Fragmentation annotation</CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                deconvoluted peaks in mass space · matched N/C ions annotated on the
                sequence ladder · ppm residuals below
              </p>
            </div>
            <span className="font-mono text-xs text-muted-foreground">
              drag scrollbar to pan · slider adjusts density
            </span>
          </CardHeader>
          <CardContent>
            <FragmentationView protein={parsed.protein} peaks={parsed.peaks} />
          </CardContent>
        </Card>
      )}

      <Lcms3DPanel
        peaks={ms1RawSpectrum?.peaks ?? null}
        scan={ms1RawSpectrum?.scan ?? ms1Scan ?? null}
        retentionTimeSeconds={ms1RawSpectrum?.retentionTime ?? null}
      />

      {/* Matched peaks table */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-base">Matched fragment peaks</CardTitle>
        </CardHeader>
        <CardContent>
          {parsed?.peaks?.length ? (
            <>
              <MatchedPeaksTable
                peaks={parsed.peaks}
                onMatchedPeakClick={(peak, ion) => setPeakDetail({ peak, ion })}
                selectedDetailKey={
                  peakDetail ? matchedPeakDetailKey(peakDetail.peak, peakDetail.ion) : null
                }
              />
              {peakDetail && (
                <MatchedPeakSpectrumPanel
                  key={matchedPeakDetailKey(peakDetail.peak, peakDetail.ion)}
                  selection={peakDetail}
                  ms2ChartPeaks={ms2ChartPeaks}
                  ms2RawSpectrum={ms2RawSpectrum}
                  ms2ScanLabel={ms2ScanLabel}
                  onClose={() => setPeakDetail(null)}
                />
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">No matched peaks found.</p>
          )}
        </CardContent>
      </Card>

      {/* ---------- Fullscreen modal views ---------- */}
      {ms1ModalOpen && (
        <SpectrumModal
          title="MS1 precursor"
          subtitle={`scan ${prsm.ms1_scans ?? "—"} · id ${prsm.ms1_ids ?? "—"}`}
          onClose={() => setMs1ModalOpen(false)}
          actions={
            <ResetZoomButton
              disabled={!isZoomed(ms1ModalZoom)}
              onClick={() => setMs1ModalZoom(DEFAULT_ZOOM)}
            />
          }
        >
          <SpectrumChart
            peaks={ms1ChartPeaks}
            xLabel="m/z (MS1)"
            yLabel="intensity"
            yIntensityScale={spectrumIntensityMode}
            height={modalChartHeight}
            marker={precursorMarker}
            emptyHint="no MS1 peaks"
            zoom={ms1ModalZoom}
            onZoomChange={setMs1ModalZoom}
          />
        </SpectrumModal>
      )}

      {ms2ModalOpen && (
        <SpectrumModal
          title="MS2 fragment spectrum"
          subtitle={`scan ${prsm.ms2_scans ?? "—"} · id ${prsm.ms2_ids ?? "—"}`}
          onClose={() => setMs2ModalOpen(false)}
          actions={
            <ResetZoomButton
              disabled={!isZoomed(ms2ModalZoom)}
              onClick={() => setMs2ModalZoom(DEFAULT_ZOOM)}
            />
          }
        >
          <SpectrumChart
            peaks={ms2ChartPeaks}
            xLabel="m/z (MS2)"
            yLabel="intensity"
            yIntensityScale={spectrumIntensityMode}
            height={modalChartHeight}
            emptyHint="no MS2 peaks"
            zoom={ms2ModalZoom}
            onZoomChange={setMs2ModalZoom}
          />
        </SpectrumModal>
      )}
    </>
  );
}

function ResetZoomButton({
  onClick,
  disabled,
}: {
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs text-muted-foreground shadow-sm transition-colors enabled:hover:text-foreground disabled:opacity-40"
    >
      <RotateCcw className="h-3.5 w-3.5" />
      reset
    </button>
  );
}

// ------------------------ Chart-peak builders -----------------------------

function buildRawChartPeaks(raw: Record<string, unknown> | undefined): ChartPeak[] {
  const s = parseRawSpectrum(raw ?? null);
  if (!s) return [];
  return s.peaks.map((p) => ({ mz: p.mz, intensity: p.intensity }));
}

/**
 * Overlay matched fragment ions (from `ms_peaks`) onto the raw MS2 peaks.
 * Each deconvoluted peak in `ms_peaks` carries `monoisotopic_mz`, so we find
 * the closest raw peak within a small tolerance and mark it as matched.
 */
function buildMs2ChartPeaks(
  s: RawSpectrum | null,
  deconv: MsPeakRow[],
): ChartPeak[] {
  if (!s) {
    // Fallback: plot the deconvoluted peaks directly.
    return deconv.map((d) => ({
      mz: d.monoMz ?? 0,
      intensity: d.intensity ?? 0,
      ion: d.matchedIons[0]?.ionType ?? null,
      ionPos: d.matchedIons[0]?.ionDisplayPosition ?? null,
      charge: d.charge,
      tooltip: d.matchedIons[0]
        ? `pos ${d.matchedIons[0].ionDisplayPosition}`
        : null,
    }));
  }

  // Build a matched-ion lookup by nearest m/z.
  const matched = deconv.filter((d) => d.matchedIons.length > 0 && d.monoMz != null);
  const matchedSorted = [...matched].sort((a, b) => (a.monoMz ?? 0) - (b.monoMz ?? 0));
  const tol = 0.02;
  let matchedIndex = 0;
  const sortedMz = matchedSorted.map((d) => d.monoMz ?? 0);

  function findMatch(mz: number): MsPeakRow | null {
    if (matchedSorted.length === 0) return null;
    let lo = 0;
    let hi = sortedMz.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (sortedMz[mid] < mz) lo = mid + 1;
      else hi = mid;
    }
    const candidates: MsPeakRow[] = [];
    if (lo > 0) candidates.push(matchedSorted[lo - 1]);
    candidates.push(matchedSorted[lo]);
    if (lo + 1 < matchedSorted.length) candidates.push(matchedSorted[lo + 1]);
    const tol = 0.02; // 20 mDa – generous for matching into the raw trace
    let best: MsPeakRow | null = null;
    let bestDist = Infinity;
    for (const c of candidates) {
      const d = Math.abs((c.monoMz ?? 0) - mz);
      if (d < bestDist && d < tol) {
        best = c;
        bestDist = d;
      }
    }
    return best;
  }

  function findMatchLinear(mz: number): MsPeakRow | null {
    while (
      matchedIndex < matchedSorted.length &&
      (matchedSorted[matchedIndex].monoMz ?? 0) < mz - tol
    ) {
      matchedIndex++;
    }

    let best: MsPeakRow | null = null;
    let bestDist = Infinity;
    for (let i = Math.max(0, matchedIndex - 1); i <= matchedIndex + 1 && i < matchedSorted.length; i++) {
      const candidate = matchedSorted[i];
      const dist = Math.abs((candidate.monoMz ?? 0) - mz);
      if (dist < bestDist && dist < tol) {
        best = candidate;
        bestDist = dist;
      }
    }
    return best;
  }
  void findMatch;

  return s.peaks.map((p): ChartPeak => {
    const m = findMatchLinear(p.mz);
    const ion = m?.matchedIons[0];
    return {
      mz: p.mz,
      intensity: p.intensity,
      ion: ion?.ionType ?? null,
      ionPos: ion?.ionDisplayPosition ?? null,
      charge: m?.charge ?? null,
      tooltip: ion ? `pos ${ion.ionDisplayPosition}` : null,
    };
  });
}
