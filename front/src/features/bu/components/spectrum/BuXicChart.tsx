import type { BuXicOut } from "@/features/bu/types";
import { BuInteractivePlot } from "@/features/bu/components/spectrum/BuInteractivePlot";
import { BU_CHART, type Zoom } from "@/features/bu/components/spectrum/chartTheme";

export function BuXicChart({
  xic,
  sequence,
  precursorCharge,
  ppm = 10,
  height = BU_CHART.xicHeight,
  zoom,
  onZoomChange,
  onOpenFull,
}: {
  xic: BuXicOut;
  sequence: string;
  precursorCharge: number | null;
  ppm?: number;
  height?: number;
  zoom?: Zoom;
  onZoomChange?: (zoom: Zoom) => void;
  onOpenFull?: () => void;
}) {
  const points = xic.rt.map((rt, index) => ({ x: rt, y: xic.intensity[index] ?? 0 }));
  const bands =
    xic.rt_start !== null && xic.rt_stop !== null
      ? [{ start: xic.rt_start, stop: xic.rt_stop, color: BU_CHART.rtWindow, opacity: 0.15 }]
      : [];
  const guides = xic.rt_apex !== null ? [{ x: xic.rt_apex, color: BU_CHART.apex, dashed: true }] : [];

  return (
    <div>
      <div className="mb-2">
        <div className="text-center text-base font-medium">
          XIC of precursor m/z {xic.precursor_mz.toFixed(4)} (&plusmn;{ppm} ppm)
        </div>
        <div className="text-center text-sm text-muted-foreground">
          peptide: {sequence} charge +{precursorCharge ?? "?"}
        </div>
      </div>
      <BuInteractivePlot
        points={points}
        xLabel="Retention Time (min)"
        yLabel="MS1 intensity at precursor m/z"
        lineColor={BU_CHART.tic}
        fillColor={BU_CHART.tic}
        fillOpacity={0.3}
        height={height}
        bands={bands}
        guides={guides}
        legend={[
          { label: "RT window", color: BU_CHART.rtWindow, kind: "band" },
          { label: "apex", color: BU_CHART.apex, kind: "line" },
        ]}
        zoom={zoom}
        onZoomChange={onZoomChange}
        onOpenFull={onOpenFull}
      />
    </div>
  );
}
