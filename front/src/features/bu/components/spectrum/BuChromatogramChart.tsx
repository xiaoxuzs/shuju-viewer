import type { BuChromatogramOut } from "@/features/bu/types";
import { BuInteractivePlot } from "@/features/bu/components/spectrum/BuInteractivePlot";
import { BU_CHART, type Zoom } from "@/features/bu/components/spectrum/chartTheme";

export function BuChromatogramChart({
  chromatogram,
  height = BU_CHART.chromatogramHeight,
  zoom,
  onZoomChange,
  onOpenFull,
  onFirstRender,
}: {
  chromatogram: BuChromatogramOut;
  height?: number;
  zoom?: Zoom;
  onZoomChange?: (zoom: Zoom) => void;
  onOpenFull?: () => void;
  onFirstRender?: () => void;
}) {
  const isBpc = chromatogram.type === "bpc";
  const points = chromatogram.rt.map((rt, index) => ({ x: rt, y: chromatogram.intensity[index] ?? 0 }));
  const color = isBpc ? BU_CHART.bpc : BU_CHART.tic;
  const title = isBpc ? "MS1 Base Peak Chromatogram (BPC)" : "MS1 Total Ion Chromatogram (TIC)";
  const yLabel = isBpc ? "Base Peak Intensity" : "Total Ion Current";

  return (
    <div>
      <div className="mb-2">
        <div className="text-center text-base font-medium">{title}</div>
        <div className="text-center text-sm text-muted-foreground">
          {chromatogram.rt.length.toLocaleString()} points
          {chromatogram.downsampled
            ? ` · downsampled from ${chromatogram.point_count_original.toLocaleString()}`
            : ""}
        </div>
      </div>
      <BuInteractivePlot
        points={points}
        xLabel="Retention Time (min)"
        yLabel={yLabel}
        lineColor={color}
        fillColor={color}
        fillOpacity={0.2}
        height={height}
        zoom={zoom}
        onZoomChange={onZoomChange}
        onOpenFull={onOpenFull}
        onFirstRender={onFirstRender}
      />
    </div>
  );
}
