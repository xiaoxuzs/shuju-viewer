import type { PeptideLegendItem } from "./coverageLayout";

export function PeptideLegend({ items }: { items: PeptideLegendItem[] }) {
  if (items.length === 0) return null;

  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-2 md:grid-cols-4">
      {items.map((item) => (
        <div
          key={item.peptideId}
          title={`peptide #${item.peptideId}`}
          className="flex min-w-0 items-center gap-2 font-mono text-xs text-foreground"
        >
          <span
            className="h-2 w-3 shrink-0 rounded-[1px]"
            style={{ backgroundColor: item.color }}
          />
          <span className="min-w-0 break-all">
            {item.sequence}
            {item.ambiguous && <span className="font-sans text-muted-foreground">*</span>}
          </span>
        </div>
      ))}
    </div>
  );
}
