import { useEffect, useState } from "react";
import { useOutletContext, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchBuMatch, fetchBuMatchMs2, fetchBuMatchXic } from "@/features/bu/api/buClient";
import { BuChartModal } from "@/features/bu/components/spectrum/BuChartModal";
import { BuSpectrumChart } from "@/features/bu/components/spectrum/BuSpectrumChart";
import { BuXicChart } from "@/features/bu/components/spectrum/BuXicChart";
import { BU_CHART, DEFAULT_ZOOM, isZoomed, type Zoom } from "@/features/bu/components/spectrum/chartTheme";
import type { BuDatasetContext } from "@/features/bu/layout/BuDatasetLayout";
import { formatDecimal } from "@/features/bu/utils";

const MS2_PPM = 20;
const XIC_PPM = 10;
const ZOOM_HINT = "wheel to zoom (Shift = Y) · brush-drag = X";

export function BuMatchDetailPage() {
  const { dataset } = useOutletContext<BuDatasetContext>();
  const { matchId = "" } = useParams();
  const parsedMatchId = Number(matchId);
  const [xicFullOpen, setXicFullOpen] = useState(false);
  const [ms2FullOpen, setMs2FullOpen] = useState(false);
  const [xicModalZoom, setXicModalZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const [ms2ModalZoom, setMs2ModalZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const { data, isLoading, error } = useQuery({
    queryKey: ["bu", dataset.slug, "matches", parsedMatchId],
    queryFn: () => fetchBuMatch(dataset.slug, parsedMatchId),
    enabled: Number.isFinite(parsedMatchId),
  });
  const isMzml = data?.run.raw_format === "mzml";
  const xic = useQuery({
    queryKey: ["bu", dataset.slug, "matches", parsedMatchId, "xic", XIC_PPM],
    queryFn: () => fetchBuMatchXic(dataset.slug, parsedMatchId, XIC_PPM),
    enabled: !!isMzml && Number.isFinite(parsedMatchId),
  });
  const ms2 = useQuery({
    queryKey: ["bu", dataset.slug, "matches", parsedMatchId, "ms2", MS2_PPM],
    queryFn: () => fetchBuMatchMs2(dataset.slug, parsedMatchId, MS2_PPM),
    enabled: !!isMzml && Number.isFinite(parsedMatchId),
  });

  useEffect(() => {
    setXicFullOpen(false);
    setMs2FullOpen(false);
    setXicModalZoom(DEFAULT_ZOOM);
    setMs2ModalZoom(DEFAULT_ZOOM);
  }, [parsedMatchId]);

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
          <Field label="Spectrum" value={isMzml ? "mzML MS2/XIC" : "D10 unsupported"} />
        </CardContent>
      </Card>

      {isMzml ? (
        <>
          {xic.isLoading && <Skeleton className="h-56" />}
          {xic.error && <p className="text-destructive">{(xic.error as Error).message}</p>}
          {xic.data && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">XIC</CardTitle>
                <p className="text-xs text-muted-foreground">{ZOOM_HINT}</p>
              </CardHeader>
              <CardContent>
                <BuXicChart
                  xic={xic.data}
                  sequence={data.sequence}
                  precursorCharge={data.precursor_charge}
                  ppm={XIC_PPM}
                  onOpenFull={() => setXicFullOpen(true)}
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
                <p className="text-xs text-muted-foreground">{ZOOM_HINT}</p>
              </CardHeader>
              <CardContent>
                <BuSpectrumChart
                  spectrum={ms2.data}
                  sequence={data.sequence}
                  precursorCharge={data.precursor_charge}
                  precursorMz={data.precursor_mz}
                  ppm={MS2_PPM}
                  onOpenFull={() => setMs2FullOpen(true)}
                />
              </CardContent>
            </Card>
          )}
        </>
      ) : (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            D10: Bruker .d match-level MS2/XIC is not supported in v1.
          </CardContent>
        </Card>
      )}

      {xicFullOpen && xic.data && (
        <BuChartModal
          title="XIC"
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
