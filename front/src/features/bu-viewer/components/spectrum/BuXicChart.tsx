import type { BuXicOut } from "@/features/bu-viewer/types";
import {
  BuInteractivePlot,
  type BuPlotPointClick,
} from "@/features/bu-viewer/components/spectrum/BuInteractivePlot";
import { BU_CHART, type Zoom } from "@/features/bu-viewer/components/spectrum/chartTheme";

export interface BuXicPointSelection {
  rt: number;
  intensity: number;
  traceLabel: string;
}

export function BuXicChart({
  xic,
  sequence,
  precursorCharge,
  ppm = 10,
  height = BU_CHART.xicHeight,
  zoom,
  onZoomChange,
  onPointClick,
  onOpenFull,
}: {
  xic: BuXicOut;
  sequence: string;
  precursorCharge: number | null;
  ppm?: number;
  height?: number;
  zoom?: Zoom;
  onZoomChange?: (zoom: Zoom) => void;
  onPointClick?: (selection: BuXicPointSelection) => void;
  onOpenFull?: () => void;
}) {
  const traces = xic.traces?.length
    ? xic.traces
    : [{ label: "M", isotope_index: 0, target_mz: xic.precursor_mz, intensity: xic.intensity }];
  const colorForTrace = (isotopeIndex: number) => {
    if (isotopeIndex === 1) return BU_CHART.isotopeM1;
    if (isotopeIndex === 2) return BU_CHART.isotopeM2;
    return BU_CHART.tic;
  };
  const series = traces.map((trace) => {
    const color = colorForTrace(trace.isotope_index);
    return {
      label: trace.label,
      points: xic.rt.map((rt, index) => ({ x: rt, y: trace.intensity[index] ?? 0 })),
      color,
      fill: trace.isotope_index === 0,
      fillColor: color,
      fillOpacity: trace.isotope_index === 0 ? 0.25 : 0,
    };
  });
  const points = series[0]?.points ?? [];
  const bands =
    xic.rt_start !== null && xic.rt_stop !== null
      ? [{ start: xic.rt_start, stop: xic.rt_stop, color: BU_CHART.rtWindow, opacity: 0.15 }]
      : [];
  const guides = xic.rt_apex !== null ? [{ x: xic.rt_apex, color: BU_CHART.apex, dashed: true }] : [];
  const charge = xic.precursor_charge ?? precursorCharge;
  const handlePointClick = ({ point, seriesLabel }: BuPlotPointClick) => {
    onPointClick?.({ rt: point.x, intensity: point.y, traceLabel: seriesLabel });
  };

  return (
    <div>
      <div className="mb-2">
        <div className="text-center text-base font-medium">
          Precursor isotope XIC ({traces.map((trace) => trace.label).join(", ")}) (&plusmn;{ppm} ppm)
        </div>
        <div className="text-center text-sm text-muted-foreground">
          MS1 extraction for {sequence}, charge +{charge ?? "?"}, M m/z {xic.precursor_mz.toFixed(4)}
        </div>
      </div>
      <BuInteractivePlot
        points={points}
        series={series}
        xLabel="Retention Time (min)"
        yLabel="MS1 intensity at isotope m/z"
        lineColor={BU_CHART.tic}
        fillColor={BU_CHART.tic}
        fillOpacity={0.25}
        height={height}
        bands={bands}
        guides={guides}
        legend={[
          ...traces.map((trace) => ({ label: trace.label, color: colorForTrace(trace.isotope_index), kind: "line" as const })),
          { label: "RT window", color: BU_CHART.rtWindow, kind: "band" },
          { label: "Identification RT apex", color: BU_CHART.apex, kind: "line" },
        ]}
        zoom={zoom}
        onZoomChange={onZoomChange}
        onPointClick={onPointClick ? handlePointClick : undefined}
        onOpenFull={onOpenFull}
      />
    </div>
  );
}
