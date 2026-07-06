import { PlotStatus } from "@/components/common/plot-status";
import type { PeakAnnotation } from "@/features/spectra-only/utils/peakAnnotations";
import {
  formatPeakIntensity,
  formatPeakMz,
  formatPeakRelativeIntensity,
} from "@/features/spectra-only/utils/peakAnnotations";
import { cn } from "@/lib/utils";

interface DetectedPeaksTableProps {
  annotations: PeakAnnotation[];
  selectedPeakKey: string | null;
  onSelectPeak: (annotation: PeakAnnotation) => void;
}

export function DetectedPeaksTable({
  annotations,
  selectedPeakKey,
  onSelectPeak,
}: DetectedPeaksTableProps) {
  return (
    <div className="rounded-md border border-border/60">
      <div className="border-b border-border/60 p-3">
        <div className="text-sm font-medium">Detected peaks</div>
        <div className="mt-1 text-xs text-muted-foreground">
          Top peaks by intensity in the selected MS2 spectrum.
        </div>
      </div>
      {annotations.length === 0 ? (
        <PlotStatus
          kind="empty"
          title="No peaks are available for this MS2 spectrum."
          className="min-h-32"
        />
      ) : (
        <div className="max-h-64 overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-background text-muted-foreground">
              <tr>
                <th className="px-2 py-2 font-medium">Rank</th>
                <th className="px-2 py-2 font-medium">mz</th>
                <th className="px-2 py-2 font-medium">Intensity</th>
                <th className="px-2 py-2 font-medium">Relative intensity</th>
                <th className="px-2 py-2 font-medium">Type</th>
              </tr>
            </thead>
            <tbody>
              {annotations.map((annotation) => (
                <tr
                  key={annotation.peak.key}
                  className={cn(
                    "cursor-pointer border-t border-border/50 transition-colors hover:bg-accent/50",
                    annotation.peak.key === selectedPeakKey && "bg-primary/10 text-primary",
                  )}
                  tabIndex={0}
                  onClick={() => onSelectPeak(annotation)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelectPeak(annotation);
                    }
                  }}
                >
                  <td className="px-2 py-1.5 font-mono">{annotation.rank}</td>
                  <td className="px-2 py-1.5 font-mono">{formatPeakMz(annotation.peak.mz)}</td>
                  <td className="px-2 py-1.5 font-mono">
                    {formatPeakIntensity(annotation.peak.intensity)}
                  </td>
                  <td className="px-2 py-1.5 font-mono">
                    {formatPeakRelativeIntensity(annotation.relativeIntensity)}
                  </td>
                  <td className="px-2 py-1.5">{formatPeakTypes(annotation)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function formatPeakTypes(annotation: PeakAnnotation): string {
  const types: string[] = [];
  if (annotation.isSelected) types.push("Selected");
  if (annotation.isBasePeak) types.push("Base peak");
  if (annotation.isTopPeak) types.push("Top peak");
  return types.join(", ") || "Top peak";
}
