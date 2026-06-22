import { useState } from "react";

import { BuChartModal } from "@/features/bu/components/spectrum/BuChartModal";
import {
  BuInteractivePlot,
  type BuPlotBand,
  type BuPlotGuide,
} from "@/features/bu/components/spectrum/BuInteractivePlot";
import { BU_CHART, DEFAULT_ZOOM, type Zoom } from "@/features/bu/components/spectrum/chartTheme";
import type {
  ProductIonXicTrace,
  ProductIonYAxisMode,
} from "@/features/bu/components/match-detail/productIonXicViewModel";

export interface ProductIonRtMarker {
  rt: number;
  label: string;
  color: string;
  dashed?: boolean;
}

export function BuProductIonXicChart({
  traces,
  mode,
  rtMarkers,
  rtWindow,
  height = BU_CHART.chromatogramHeight,
}: {
  traces: ProductIonXicTrace[];
  mode: ProductIonYAxisMode;
  rtMarkers: ProductIonRtMarker[];
  rtWindow: { start: number | null; stop: number | null };
  height?: number;
}) {
  const [fullOpen, setFullOpen] = useState(false);
  const [modalZoom, setModalZoom] = useState<Zoom>(DEFAULT_ZOOM);
  const series = traces.map((trace) => ({
    label: `${trace.ion}${trace.charge > 1 ? `^${trace.charge}+` : ""} · ${trace.mz.toFixed(4)} m/z · ${trace.charge}+`,
    color: trace.color,
    points: trace.points.map((point) => ({ x: point.rt, y: point.intensity })),
  }));
  const guides: BuPlotGuide[] = rtMarkers
    .filter((marker) => Number.isFinite(marker.rt))
    .map((marker) => ({
      x: marker.rt,
      label: marker.label,
      color: marker.color,
      dashed: marker.dashed,
    }));
  const bands: BuPlotBand[] =
    rtWindow.start !== null
    && rtWindow.stop !== null
    && Number.isFinite(rtWindow.start)
    && Number.isFinite(rtWindow.stop)
      ? [{
          start: rtWindow.start,
          stop: rtWindow.stop,
          color: BU_CHART.rtWindow,
          opacity: 0.08,
          label: "RT window",
        }]
      : [];
  const legend = [
    ...traces.map((trace) => ({
      label: `${trace.ion}${trace.charge > 1 ? `^${trace.charge}+` : ""}`,
      color: trace.color,
      kind: "line" as const,
    })),
    ...rtMarkers.map((marker) => ({ label: marker.label, color: marker.color, kind: "line" as const })),
    ...(bands.length > 0
      ? [{ label: "RT window", color: BU_CHART.rtWindow, kind: "band" as const }]
      : []),
  ];
  const yLabel = mode === "normalized" ? "Normalized intensity (%)" : "Intensity";

  return (
    <>
      <BuInteractivePlot
        points={[]}
        series={series}
        xLabel="Retention Time (min)"
        yLabel={yLabel}
        lineColor={BU_CHART.y}
        height={height}
        bands={bands}
        guides={guides}
        legend={legend}
        onOpenFull={() => {
          setModalZoom(DEFAULT_ZOOM);
          setFullOpen(true);
        }}
        emptyHint="No product ion XIC traces are available."
        className="mt-3"
      />
      {fullOpen && (
        <BuChartModal
          title="Product ion XIC comparison"
          subtitle={mode === "normalized" ? "Normalized intensity by trace" : "Raw intensity"}
          onClose={() => setFullOpen(false)}
        >
          <BuInteractivePlot
            points={[]}
            series={series}
            xLabel="Retention Time (min)"
            yLabel={yLabel}
            lineColor={BU_CHART.y}
            height={560}
            bands={bands}
            guides={guides}
            legend={legend}
            zoom={modalZoom}
            onZoomChange={setModalZoom}
          />
        </BuChartModal>
      )}
    </>
  );
}
