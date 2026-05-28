/**
 * Deconvolved peaks vs matched ions: expand a row into one row per ion, or keep unmatched peaks folded.
 * Ion-type colors mirror the spectrum (N-terminal blues / C-terminal reds via CSS vars).
 */
import { useMemo, useState } from "react";
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { formatNumber } from "@/lib/utils";
import { matchedPeakDetailKey, type MatchedIon, type MsPeakRow } from "./parse";

interface Props {
  peaks: MsPeakRow[];
  className?: string;
  /** Matched rows only: click Peak to open detail panel. */
  onMatchedPeakClick?: (peak: MsPeakRow, ion: MatchedIon) => void;
  /** Highlights the Peak cell when this key equals `matchedPeakDetailKey`. */
  selectedDetailKey?: string | null;
}

type PeakIonRow = { peak: MsPeakRow; ion: MatchedIon | null };

const N_IONS = new Set(["B", "C", "A"]);
const C_IONS = new Set(["Y", "Z", "Z_DOT", "X"]);

export function MatchedPeaksTable({
  peaks,
  className,
  onMatchedPeakClick,
  selectedDetailKey,
}: Props) {
  const [filter, setFilter] = useState<"all" | "matched">("matched");

  const rows = useMemo(() => {
    const flat = peaks.flatMap((p): PeakIonRow[] =>
      p.matchedIons.length > 0
        ? p.matchedIons.map((ion) => ({ peak: p, ion }))
        : [{ peak: p, ion: null }],
    );
    return filter === "matched" ? flat.filter((r) => r.ion) : flat;
  }, [peaks, filter]);

  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex items-center gap-2 text-xs">
        <span className="text-muted-foreground">Show:</span>
        <Toggle active={filter === "matched"} onClick={() => setFilter("matched")}>
          Matched ({peaks.reduce((n, p) => n + p.matchedIons.length, 0)})
        </Toggle>
        <Toggle active={filter === "all"} onClick={() => setFilter("all")}>
          All peaks ({peaks.length})
        </Toggle>
      </div>

      <div className="max-h-[480px] overflow-auto rounded-lg border border-border">
        <table className={cn("w-full caption-bottom text-sm")}>
          <TableHeader>
            <TableRow>
              <TableHead className="w-14 text-right">Peak</TableHead>
              <TableHead className="text-right">m/z</TableHead>
              <TableHead className="text-right">Intensity</TableHead>
              <TableHead className="text-right">Charge</TableHead>
              <TableHead>Ion</TableHead>
              <TableHead className="text-right">Position</TableHead>
              <TableHead className="text-right">Mass err</TableHead>
              <TableHead className="text-right">ppm</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r, idx) => {
              const isN = r.ion && N_IONS.has(r.ion.ionType);
              const isC = r.ion && C_IONS.has(r.ion.ionType);
              const clickable = Boolean(r.ion && onMatchedPeakClick);
              const active = clickable && r.ion && selectedDetailKey === matchedPeakDetailKey(r.peak, r.ion);
              return (
                <TableRow key={`${r.peak.peakId}-${idx}`}>
                  <TableCell className="p-0 text-right align-middle font-mono text-xs">
                    {clickable && r.ion ? (
                      <button
                        type="button"
                        onClick={() => {
                          const ion = r.ion;
                          if (ion) onMatchedPeakClick?.(r.peak, ion);
                        }}
                        className={cn(
                          "w-full px-3 py-2 text-right font-mono text-xs transition-colors",
                          "text-primary underline-offset-2 hover:underline",
                          active && "bg-primary/10 font-semibold",
                        )}
                      >
                        {Number.isFinite(r.peak.peakId) ? r.peak.peakId + 1 : "—"}
                      </button>
                    ) : (
                      <span className="block px-3 py-2 text-right text-muted-foreground">
                        {Number.isFinite(r.peak.peakId) ? r.peak.peakId + 1 : "—"}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">
                    {formatNumber(r.peak.monoMz, 4)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums text-muted-foreground">
                    {formatNumber(r.peak.intensity, 1)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{r.peak.charge ?? "—"}</TableCell>
                  <TableCell>
                    {r.ion ? (
                      <Badge
                        variant="secondary"
                        className={cn(
                          "font-mono text-[11px]",
                          isN && "bg-[hsl(var(--ion-n)/0.15)] text-[hsl(var(--ion-n))]",
                          isC && "bg-[hsl(var(--ion-c)/0.15)] text-[hsl(var(--ion-c))]",
                        )}
                      >
                        {r.ion.ionType.replace("_DOT", "·")}
                      </Badge>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">
                    {r.ion ? r.ion.ionDisplayPosition : "—"}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums text-muted-foreground">
                    {formatNumber(r.ion?.massError ?? null, 4)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums text-muted-foreground">
                    {formatNumber(r.ion?.ppm ?? null, 2)}
                  </TableCell>
                </TableRow>
              );
            })}
            {rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="py-8 text-center text-sm text-muted-foreground">
                  no peaks to show
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </table>
      </div>
    </div>
  );
}

function Toggle({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-md border px-2 py-0.5 text-xs transition",
        active
          ? "border-primary/50 bg-primary/10 text-primary"
          : "border-border text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}
