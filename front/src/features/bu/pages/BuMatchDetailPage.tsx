import { useEffect, useState } from "react";
import { useOutletContext, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  fetchBuMatch,
  fetchBuMatchMobilitySlice,
  fetchBuMatchMs1,
  fetchBuMatchMs2,
  fetchBuMatchProductXic,
  fetchBuMatchXic,
} from "@/features/bu/api/buClient";
import { BuFragmentTable } from "@/features/bu/components/match-detail/BuFragmentTable";
import { BuChartModal } from "@/features/bu/components/spectrum/BuChartModal";
import { MzMobilityScatter } from "@/features/bu/components/spectrum/MzMobilityScatter";
import { BuProductXicChart } from "@/features/bu/components/spectrum/BuProductXicChart";
import { BuSpectrumChart } from "@/features/bu/components/spectrum/BuSpectrumChart";
import { BuXicChart, type BuXicPointSelection } from "@/features/bu/components/spectrum/BuXicChart";
import { BU_CHART, DEFAULT_ZOOM, isZoomed, type Zoom } from "@/features/bu/components/spectrum/chartTheme";
import type { BuDatasetContext } from "@/features/bu/layout/BuDatasetLayout";
import type { BuMatchedIon } from "@/features/bu/types";
import { formatDecimal } from "@/features/bu/utils";

const MS2_PPM = 20;
const XIC_PPM = 10;
const ZOOM_HINT = "wheel to zoom (Shift = Y) · brush-drag = X";

export function BuMatchDetailPage() {
  const { dataset } = useOutletContext<BuDatasetContext>();
  const { matchId = "" } = useParams();
  const parsedMatchId = Number(matchId);
  const [xicFullOpen, setXicFullOpen] = useState(false);
  const [ms1FullOpen, setMs1FullOpen] = useState(false);
  const [ms2FullOpen, setMs2FullOpen] = useState(false);
  const [xicModalZoom, setXicModalZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const [ms1ModalZoom, setMs1ModalZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const [ms2ModalZoom, setMs2ModalZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const [selectedXicPoint, setSelectedXicPoint] = useState<BuXicPointSelection | null>(null);
  const [selectedProductIon, setSelectedProductIon] = useState<BuMatchedIon | null>(null);
  const { data, isLoading, error } = useQuery({
    queryKey: ["bu", dataset.slug, "matches", parsedMatchId],
    queryFn: () => fetchBuMatch(dataset.slug, parsedMatchId),
    enabled: Number.isFinite(parsedMatchId),
  });
  const isMzml = data?.run.raw_format === "mzml";
  const isBruker = data?.run.raw_format === "bruker_d";
  const xic = useQuery({
    queryKey: ["bu", dataset.slug, "matches", parsedMatchId, "xic", XIC_PPM],
    queryFn: () => fetchBuMatchXic(dataset.slug, parsedMatchId, XIC_PPM),
    enabled: !!isMzml && Number.isFinite(parsedMatchId),
  });
  const ms2 = useQuery({
    queryKey: ["bu", dataset.slug, "matches", parsedMatchId, "ms2", MS2_PPM, selectedXicPoint?.rt ?? "default"],
    queryFn: () =>
      fetchBuMatchMs2(
        dataset.slug,
        parsedMatchId,
        MS2_PPM,
        selectedXicPoint ? { rt: selectedXicPoint.rt } : {},
      ),
    enabled: !!isMzml && Number.isFinite(parsedMatchId),
  });
  const productXic = useQuery({
    queryKey: [
      "bu",
      dataset.slug,
      "matches",
      parsedMatchId,
      "product-xic",
      selectedProductIon?.theo_mz ?? null,
      MS2_PPM,
    ],
    queryFn: () =>
      fetchBuMatchProductXic(dataset.slug, parsedMatchId, selectedProductIon!.theo_mz, MS2_PPM),
    enabled: !!isMzml && Number.isFinite(parsedMatchId) && selectedProductIon !== null,
  });
  const ms1 = useQuery({
    queryKey: ["bu", dataset.slug, "matches", parsedMatchId, "ms1"],
    queryFn: () => fetchBuMatchMs1(dataset.slug, parsedMatchId),
    enabled: !!isMzml && Number.isFinite(parsedMatchId),
  });
  const mobility = useQuery({
    queryKey: ["bu", dataset.slug, "matches", parsedMatchId, "mobility-slice"],
    queryFn: () => fetchBuMatchMobilitySlice(dataset.slug, parsedMatchId),
    enabled: !!isBruker && Number.isFinite(parsedMatchId),
  });

  useEffect(() => {
    setXicFullOpen(false);
    setMs1FullOpen(false);
    setMs2FullOpen(false);
    setXicModalZoom(DEFAULT_ZOOM);
    setMs1ModalZoom(DEFAULT_ZOOM);
    setMs2ModalZoom(DEFAULT_ZOOM);
    setSelectedXicPoint(null);
    setSelectedProductIon(null);
  }, [parsedMatchId]);

  const selectXicPoint = (selection: BuXicPointSelection) => {
    setSelectedXicPoint(selection);
    setSelectedProductIon(null);
  };

  if (isLoading) return <Skeleton className="h-64" />;
  if (error) return <p className="text-destructive">{(error as Error).message}</p>;
  if (!data) return null;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>{data.modified_sequence ?? data.sequence}</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          <Field label="Run" value={data.run.file_name} />
          <Field label="Charge" value={data.precursor_charge ? `${data.precursor_charge}+` : "-"} />
          <Field label="m/z" value={formatDecimal(data.precursor_mz)} />
          <Field label="Q.Value" value={formatDecimal(data.q_value)} />
          <Field label="RT apex" value={formatDecimal(data.rt_window.rt_apex)} />
          <Field label="Scan" value={String(data.scan_number)} />
          <Field label="Proteins" value={data.proteins.map((p) => p.accession).join(", ") || "-"} />
          <Field label="Spectrum" value={isMzml ? "mzML precursor XIC + MS1/MS2" : "match-level spectra unsupported"} />
        </CardContent>
      </Card>

      {isMzml ? (
        <>
          {xic.isLoading && <Skeleton className="h-56" />}
          {xic.error && <p className="text-destructive">{(xic.error as Error).message}</p>}
          {xic.data && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Precursor XIC</CardTitle>
                <p className="text-xs text-muted-foreground">
                  MS1 extracted ion chromatogram for the precursor; used as chromatographic context for the MS2 spectrum.
                </p>
                <p className="text-xs text-muted-foreground">
                  Click a point on the XIC to inspect the corresponding MS2 scan. {ZOOM_HINT}
                </p>
                {selectedXicPoint && (
                  <p className="text-xs font-medium text-foreground">
                    Selected {selectedXicPoint.traceLabel}: RT {selectedXicPoint.rt.toFixed(4)} min, intensity{" "}
                    {formatDecimal(selectedXicPoint.intensity, 0)}
                  </p>
                )}
              </CardHeader>
              <CardContent>
                <BuXicChart
                  xic={xic.data}
                  sequence={data.sequence}
                  precursorCharge={data.precursor_charge}
                  ppm={XIC_PPM}
                  onPointClick={selectXicPoint}
                  onOpenFull={() => setXicFullOpen(true)}
                />
              </CardContent>
            </Card>
          )}
          {ms1.isLoading && <Skeleton className="h-64" />}
          {ms1.error && <p className="text-destructive">{(ms1.error as Error).message}</p>}
          {ms1.data && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">MS1 Spectrum</CardTitle>
                <p className="text-xs text-muted-foreground">{ZOOM_HINT}</p>
              </CardHeader>
              <CardContent>
                <BuSpectrumChart
                  spectrum={ms1.data}
                  sequence={data.sequence}
                  precursorCharge={data.precursor_charge}
                  precursorMz={data.precursor_mz}
                  onOpenFull={() => setMs1FullOpen(true)}
                />
              </CardContent>
            </Card>
          )}
          {ms2.isLoading && <Skeleton className="h-64" />}
          {ms2.error && <p className="text-destructive">{(ms2.error as Error).message}</p>}
          {ms2.data && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">MS2 Spectrum</CardTitle>
                <p className="text-xs text-muted-foreground">
                  Fragment spectrum near the selected retention time. Click a matched fragment ion to extract its product ion chromatogram.
                </p>
                <p className="text-xs text-muted-foreground">
                  点击 MS2 谱图中匹配的 b/y 碎片峰，可查看该碎片离子的 Product ion XIC（二级色谱曲线）。
                </p>
                <p className="text-xs text-muted-foreground">
                  Current scan #{ms2.data.scan}, RT {ms2.data.rt_minutes.toFixed(4)} min. {ZOOM_HINT}
                </p>
              </CardHeader>
              <CardContent>
                <BuSpectrumChart
                  spectrum={ms2.data}
                  sequence={data.sequence}
                  precursorCharge={data.precursor_charge}
                  precursorMz={data.precursor_mz}
                  ppm={MS2_PPM}
                  onMatchedIonClick={setSelectedProductIon}
                  onOpenFull={() => setMs2FullOpen(true)}
                />
                {selectedProductIon && productXic.isLoading && <Skeleton className="mt-4 h-56" />}
                {selectedProductIon && productXic.error && (
                  <div className="mt-4 rounded-md border border-destructive/40 p-3 text-sm">
                    <p className="text-destructive">{(productXic.error as Error).message}</p>
                    <button
                      type="button"
                      onClick={() => setSelectedProductIon(null)}
                      className="mt-2 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
                    >
                      clear product ion XIC
                    </button>
                  </div>
                )}
                {selectedProductIon && productXic.data && (
                  <BuProductXicChart
                    xic={productXic.data}
                    ion={selectedProductIon}
                    onClear={() => setSelectedProductIon(null)}
                  />
                )}
                <BuFragmentTable ions={ms2.data.matched_ions} />
              </CardContent>
            </Card>
          )}
        </>
      ) : (
        <>
          <Card>
            <CardContent className="p-6 text-sm text-muted-foreground">
              {isBruker
                ? "Bruker .d match-level Precursor XIC and MS1/MS2 spectra are not supported."
                : "This raw format does not support match-level Precursor XIC or MS1/MS2 spectra."}
            </CardContent>
          </Card>
          {isBruker && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">m/z × 1/K0 slice</CardTitle>
                <p className="text-xs text-muted-foreground">Bruker .d MS1 frame nearest to the match RT apex</p>
              </CardHeader>
              <CardContent>
                {mobility.isLoading && <Skeleton className="h-72" />}
                {mobility.error && <p className="text-destructive">{(mobility.error as Error).message}</p>}
                {mobility.data && <MzMobilityScatter slice={mobility.data} />}
              </CardContent>
            </Card>
          )}
        </>
      )}

      {xicFullOpen && xic.data && (
        <BuChartModal
          title="Precursor XIC"
          subtitle={`${data.sequence} · ${ZOOM_HINT}`}
          onClose={() => setXicFullOpen(false)}
          actions={<ResetZoomButton zoom={xicModalZoom} onReset={() => setXicModalZoom(DEFAULT_ZOOM)} />}
        >
          <BuXicChart
            xic={xic.data}
            sequence={data.sequence}
            precursorCharge={data.precursor_charge}
            ppm={XIC_PPM}
            height={Math.max(BU_CHART.xicHeight, 560)}
            zoom={xicModalZoom}
            onZoomChange={setXicModalZoom}
            onPointClick={selectXicPoint}
          />
        </BuChartModal>
      )}

      {ms1FullOpen && ms1.data && (
        <BuChartModal
          title="MS1 Spectrum"
          subtitle={`${data.sequence} · ${ZOOM_HINT}`}
          onClose={() => setMs1FullOpen(false)}
          actions={<ResetZoomButton zoom={ms1ModalZoom} onReset={() => setMs1ModalZoom(DEFAULT_ZOOM)} />}
        >
          <BuSpectrumChart
            spectrum={ms1.data}
            sequence={data.sequence}
            precursorCharge={data.precursor_charge}
            precursorMz={data.precursor_mz}
            height={Math.max(BU_CHART.ms2Height, 620)}
            zoom={ms1ModalZoom}
            onZoomChange={setMs1ModalZoom}
          />
        </BuChartModal>
      )}

      {ms2FullOpen && ms2.data && (
        <BuChartModal
          title="MS2 Spectrum"
          subtitle={`${data.sequence} · ${ZOOM_HINT}`}
          onClose={() => setMs2FullOpen(false)}
          actions={<ResetZoomButton zoom={ms2ModalZoom} onReset={() => setMs2ModalZoom(DEFAULT_ZOOM)} />}
        >
          <BuSpectrumChart
            spectrum={ms2.data}
            sequence={data.sequence}
            precursorCharge={data.precursor_charge}
            precursorMz={data.precursor_mz}
            ppm={MS2_PPM}
            height={Math.max(BU_CHART.ms2Height, 620)}
            zoom={ms2ModalZoom}
            onZoomChange={setMs2ModalZoom}
            onMatchedIonClick={setSelectedProductIon}
          />
        </BuChartModal>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/60 bg-muted/30 p-3">
      <div className="text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1 break-words font-medium">{value}</div>
    </div>
  );
}

function ResetZoomButton({ zoom, onReset }: { zoom: Zoom; onReset: () => void }) {
  return (
    <button
      type="button"
      onClick={onReset}
      disabled={!isZoomed(zoom)}
      className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-xs text-muted-foreground transition-colors enabled:hover:text-foreground disabled:opacity-40"
    >
      <RotateCcw className="h-3.5 w-3.5" />
      reset
    </button>
  );
}
