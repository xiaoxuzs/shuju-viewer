import { cn } from "@/lib/utils";
import type { BuMatchedIon } from "@/features/bu/types";
import { formatCount, formatDecimal } from "@/features/bu/utils";
import {
  isProductIonSelected,
  productIonLabel,
  toProductIonSelection,
} from "@/features/bu/components/match-detail/productIonSelection";

export function BuFragmentTable({
  ions,
  selectedProductIonIds,
  selectionLimitReached,
  onToggleProductIon,
}: {
  ions: BuMatchedIon[];
  selectedProductIonIds: ReadonlySet<string>;
  selectionLimitReached: boolean;
  onToggleProductIon: (ion: BuMatchedIon) => void;
}) {
  if (ions.length === 0) return null;
  const sorted = [...ions].sort((a, b) => a.ion_type.localeCompare(b.ion_type) || a.position - b.position || a.charge - b.charge);

  return (
    <section
      className="min-w-0 rounded-lg border border-border/70 bg-background/70 p-3"
      data-testid="product-ion-fragment-table-panel"
    >
      <div className="mb-2">
        <h4 className="text-sm font-semibold">
          Live mzML matched b/y fragments ({formatCount(ions.length)})
        </h4>
      </div>
      <div className="max-h-[340px] overflow-auto" data-testid="live-fragment-table-scroll">
        <table className="w-full min-w-[720px] text-xs">
            <thead className="sticky top-0 z-10 border-b border-border bg-background text-xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="py-1.5 text-left">Product XIC</th>
                <th className="py-1.5 text-left">Ion</th>
                <th className="py-1.5 text-right">Position</th>
                <th className="py-1.5 text-right">Charge</th>
                <th className="py-1.5 text-right">Theo m/z</th>
                <th className="py-1.5 text-right">Exp m/z</th>
                <th className="py-1.5 text-right">ppm</th>
                <th className="py-1.5 text-right">Intensity</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((ion) => {
                const selection = toProductIonSelection(ion);
                if (!selection) return null;
                const selected = isProductIonSelected(ion, selectedProductIonIds);
                return (
                  <tr
                    key={selection.id}
                    className={cn(
                      "border-b border-border/60 last:border-0",
                      selected && "border-l-2 border-l-primary bg-primary/10",
                    )}
                    data-testid="live-fragment-row"
                    data-product-ion-id={selection.id}
                    data-product-ion-selected={selected ? "true" : "false"}
                  >
                    <td className="py-1.5 pl-2 text-left">
                      <input
                        type="checkbox"
                        checked={selected}
                        disabled={!selected && selectionLimitReached}
                        onClick={(event) => event.stopPropagation()}
                        onChange={() => onToggleProductIon(ion)}
                        aria-label={`${selected ? "Remove" : "Add"} ${productIonLabel(selection)} ${selected ? "from" : "to"} product ion XIC`}
                        className="h-4 w-4 accent-primary"
                      />
                    </td>
                    <td className="py-1.5 font-mono font-medium">{ionLabel(ion)}</td>
                    <td className="py-1.5 text-right">{ion.position}</td>
                    <td className="py-1.5 text-right">{ion.charge}+</td>
                    <td className="py-1.5 text-right font-mono">{formatDecimal(ion.theo_mz)}</td>
                    <td className="py-1.5 text-right font-mono">{formatDecimal(ion.exp_mz)}</td>
                    <td className="py-1.5 text-right font-mono">{formatDecimal(ion.ppm, 2)}</td>
                    <td className="py-1.5 text-right font-mono">{formatCount(ion.intensity)}</td>
                  </tr>
                );
              })}
            </tbody>
        </table>
      </div>
    </section>
  );
}

function ionLabel(ion: BuMatchedIon): string {
  return `${ion.ion_type}${ion.position}${ion.charge > 1 ? `^${ion.charge}+` : ""}`;
}
