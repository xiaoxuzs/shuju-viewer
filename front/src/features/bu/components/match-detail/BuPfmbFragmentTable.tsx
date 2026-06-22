import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { BuPfmbMatchedIon } from "@/features/bu/types";
import { formatCount, formatDecimal } from "@/features/bu/utils";
import { PFMB_SERIES_COLOR, ionFamilyKey, ionLabel } from "@/features/bu/components/match-detail/pfmbSeries";

type SortKey = "ion" | "intensity" | "ppm" | "peak";
type SortDir = "asc" | "desc";

function defaultCmp(a: BuPfmbMatchedIon, b: BuPfmbMatchedIon): number {
  return (
    a.ion_type.localeCompare(b.ion_type) ||
    a.fragment_ordinal - b.fragment_ordinal ||
    a.charge - b.charge
  );
}

function comparator(key: SortKey): (a: BuPfmbMatchedIon, b: BuPfmbMatchedIon) => number {
  switch (key) {
    case "intensity":
      return (a, b) => a.intensity - b.intensity || defaultCmp(a, b);
    case "ppm":
      return (a, b) => a.mass_error_ppm - b.mass_error_ppm || defaultCmp(a, b);
    case "peak":
      return (a, b) => a.peak_id - b.peak_id || defaultCmp(a, b);
    default:
      return defaultCmp;
  }
}

export function BuPfmbFragmentTable({
  ions,
  highlight,
  onHighlight,
}: {
  ions: BuPfmbMatchedIon[];
  highlight?: ReadonlySet<string>;
  onHighlight?: (familyKey: string) => void;
}) {
  // Default order: ion type -> fragment ordinal -> charge.
  const [sortKey, setSortKey] = useState<SortKey>("ion");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const sorted = useMemo(() => {
    const cmp = comparator(sortKey);
    const arr = [...ions];
    arr.sort((a, b) => (sortDir === "asc" ? cmp(a, b) : -cmp(a, b)));
    return arr;
  }, [ions, sortKey, sortDir]);

  if (ions.length === 0) {
    return (
      <Card className="mt-4 border-border/70">
        <CardContent
          className="py-6 text-center text-sm text-muted-foreground"
          data-testid="pfmb-empty-ions"
        >
          This Fragment Match record has no matched fragment ions.
        </CardContent>
      </Card>
    );
  }

  function toggle(key: SortKey) {
    if (key === sortKey) {
      setSortDir((dir) => (dir === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  return (
    <Card className="mt-4 border-border/70">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          Pre-computed Fragment Match matched fragments ({formatCount(ions.length)})
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-sm">
            <thead className="border-b border-border text-xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <SortHeader label="Ion" sortKey="ion" active={sortKey} dir={sortDir} onSort={toggle} align="left" />
                <th className="py-2 text-right">Ordinal</th>
                <th className="py-2 text-right">Charge</th>
                <th className="py-2 text-right">Theoretical neutral mass</th>
                <th className="py-2 text-right">Observed neutral mass</th>
                <SortHeader label="Mass error (ppm)" sortKey="ppm" active={sortKey} dir={sortDir} onSort={toggle} align="right" />
                <th className="py-2 text-right">Mass error (Da)</th>
                <SortHeader label="Intensity" sortKey="intensity" active={sortKey} dir={sortDir} onSort={toggle} align="right" />
                <SortHeader label="Peak ID" sortKey="peak" active={sortKey} dir={sortDir} onSort={toggle} align="right" />
              </tr>
            </thead>
            <tbody>
              {sorted.map((ion, index) => {
                const family = ionFamilyKey(ion);
                const isHighlighted = highlight?.has(family) ?? false;
                return (
                <tr
                  key={`${ion.ion_type}-${ion.fragment_ordinal}-${ion.charge}-${ion.peak_id}-${index}`}
                  className={cn(
                    "border-b border-border/60 last:border-0",
                    onHighlight && "cursor-pointer",
                    isHighlighted && "bg-primary/10",
                  )}
                  data-testid="pfmb-ion-row"
                  data-family={family}
                  data-highlighted={isHighlighted ? "true" : "false"}
                  onClick={onHighlight ? () => onHighlight(family) : undefined}
                >
                  <td className="py-2 font-mono font-medium" style={{ color: PFMB_SERIES_COLOR[ion.ion_type] }}>
                    {ionLabel(ion)}
                  </td>
                  <td className="py-2 text-right">{ion.fragment_ordinal}</td>
                  <td className="py-2 text-right">{ion.charge}+</td>
                  <td className="py-2 text-right font-mono text-xs">{formatDecimal(ion.theoretical_neutral_mass)}</td>
                  <td className="py-2 text-right font-mono text-xs">{formatDecimal(ion.observed_neutral_mass)}</td>
                  <td className="py-2 text-right font-mono text-xs">{formatDecimal(ion.mass_error_ppm, 2)}</td>
                  <td className="py-2 text-right font-mono text-xs">{formatDecimal(ion.mass_error_da, 4)}</td>
                  <td className="py-2 text-right font-mono text-xs">{formatCount(ion.intensity)}</td>
                  <td className="py-2 text-right font-mono text-xs text-muted-foreground">{ion.peak_id}</td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function SortHeader({
  label,
  sortKey,
  active,
  dir,
  onSort,
  align,
}: {
  label: string;
  sortKey: SortKey;
  active: SortKey;
  dir: SortDir;
  onSort: (key: SortKey) => void;
  align: "left" | "right";
}) {
  const isActive = active === sortKey;
  return (
    <th className={cn("py-2", align === "right" ? "text-right" : "text-left")}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        aria-label={`Sort by ${label}`}
        aria-pressed={isActive}
        className={cn(
          "inline-flex items-center gap-1 uppercase tracking-wider transition-colors hover:text-foreground",
          align === "right" ? "flex-row-reverse" : "flex-row",
          isActive ? "text-foreground" : "",
        )}
      >
        {label}
        {isActive ? (
          dir === "asc" ? (
            <ArrowUp className="h-3 w-3" aria-hidden />
          ) : (
            <ArrowDown className="h-3 w-3" aria-hidden />
          )
        ) : null}
      </button>
    </th>
  );
}

