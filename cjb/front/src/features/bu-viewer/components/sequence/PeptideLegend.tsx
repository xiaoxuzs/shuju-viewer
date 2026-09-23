import { cn } from "@/lib/utils";

import { SELECTED_PEPTIDE_HIGHLIGHT_SOFT } from "./coverageColors";
import type { PeptideLegendItem } from "./coverageLayout";

export function PeptideLegend({
  items,
  selectedPeptideKey,
  onSelect,
}: {
  items: PeptideLegendItem[];
  selectedPeptideKey: string | null;
  onSelect: (key: string) => void;
}) {
  if (items.length === 0) return null;

  return (
    <div
      aria-label="Covered peptides"
      className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1"
      role="listbox"
    >
      {items.map((item) => {
        const selected = item.key === selectedPeptideKey;

        return (
          <button
            key={item.key}
            aria-selected={selected}
            className={cn(
              "flex w-full min-w-0 items-start gap-2 rounded-md border px-2.5 py-2 text-left font-mono text-xs text-foreground transition",
              "hover:border-primary/40 hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              selected
                ? "border-yellow-400 bg-yellow-200/80 font-semibold text-yellow-950 shadow-sm ring-1 ring-yellow-300"
                : "border-border/70 bg-background",
            )}
            data-selected={selected ? "true" : undefined}
            data-testid="peptide-legend-item"
            onClick={() => onSelect(item.key)}
            role="option"
            style={selected ? { backgroundColor: SELECTED_PEPTIDE_HIGHLIGHT_SOFT } : undefined}
            title={`peptide #${item.peptideId}`}
            type="button"
          >
            <span
              aria-hidden="true"
              className={cn("mt-1 h-2.5 w-3 shrink-0 rounded-[2px]", selected && "ring-1 ring-yellow-600/60")}
              style={{ backgroundColor: item.color }}
            />
            <span className="min-w-0 flex-1 break-all">
              {item.sequence}
              {item.ambiguous && <span className="font-sans text-muted-foreground">*</span>}
            </span>
          </button>
        );
      })}
    </div>
  );
}
