import { X } from "lucide-react";

import type { BuMatchedIon, BuProductXicOut } from "@/features/bu/types";
import { BuInteractivePlot } from "@/features/bu/components/spectrum/BuInteractivePlot";
import { BU_CHART } from "@/features/bu/components/spectrum/chartTheme";

function ionLabel(ion: BuMatchedIon): string {
  return `${ion.ion_type}${ion.position}${ion.charge > 1 ? `^${ion.charge}+` : ""}`;
}

export function BuProductXicChart({
  xic,
  ion,
  onClear,
}: {
  xic: BuProductXicOut;
  ion: BuMatchedIon;
  onClear: () => void;
}) {
  return (
    <div className="mt-4 rounded-md border border-border/70 p-3">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div>
          <div className="font-medium">
            Product ion XIC: {ionLabel(ion)} / m/z {xic.product_mz.toFixed(4)}
          </div>
          <div className="text-xs text-muted-foreground">
            MS2 extraction at the theoretical fragment m/z (&plusmn;{xic.ppm} ppm), restricted to the precursor DIA window.
          </div>
        </div>
        <button
          type="button"
          onClick={onClear}
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <X className="h-3.5 w-3.5" />
          clear
        </button>
      </div>
      <BuInteractivePlot
        points={xic.points.map((point) => ({ x: point.rt, y: point.intensity }))}
        xLabel="Retention Time (min)"
        yLabel="MS2 intensity at product m/z"
        lineColor={BU_CHART.y}
        fillColor={BU_CHART.y}
        fillOpacity={0.18}
        height={BU_CHART.chromatogramHeight}
        emptyHint="No MS2 scans matched this precursor isolation window in the RT range."
      />
    </div>
  );
}
