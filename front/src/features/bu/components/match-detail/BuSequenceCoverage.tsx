import { Fragment, useMemo } from "react";

import { cn } from "@/lib/utils";
import type { BuPfmbMatchedIon } from "@/features/bu/types";
import {
  PFMB_SERIES_COLOR,
  cleavageSite,
  ionFamilyKey,
  ionLabel,
  pfmbResidues,
  seriesLabel,
  type PfmbIonType,
} from "@/features/bu/components/match-detail/pfmbSeries";

const N_TERM_SERIES: PfmbIonType[] = ["b", "c"];
const C_TERM_SERIES: PfmbIonType[] = ["y", "z_dot"];

interface SiteInfo {
  nTypes: Set<PfmbIonType>; // b / c (from N-terminus)
  cTypes: Set<PfmbIonType>; // y / z. (from C-terminus)
  families: Set<string>;
  ionNames: Set<string>;
}

export function BuSequenceCoverage({
  peptide,
  ions,
  highlight,
  onHighlight,
}: {
  peptide: string;
  ions: BuPfmbMatchedIon[];
  highlight?: ReadonlySet<string>;
  onHighlight?: (familyKeys: string[]) => void;
}) {
  const residues = useMemo(() => pfmbResidues(peptide), [peptide]);
  const len = residues.length;

  const sites = useMemo(() => {
    const map = new Map<number, SiteInfo>();
    for (const ion of ions) {
      const site = cleavageSite(ion, len);
      if (site < 1 || site > len - 1) continue;
      let info = map.get(site);
      if (!info) {
        info = { nTypes: new Set(), cTypes: new Set(), families: new Set(), ionNames: new Set() };
        map.set(site, info);
      }
      info.families.add(ionFamilyKey(ion));
      info.ionNames.add(ionLabel(ion));
      if (ion.ion_type === "b" || ion.ion_type === "c") info.nTypes.add(ion.ion_type);
      else info.cTypes.add(ion.ion_type);
    }
    return map;
  }, [ions, len]);

  if (len === 0 || sites.size === 0) {
    return (
      <div className="mb-6 rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground" data-testid="pfmb-sequence-coverage-empty">
        PFMB sequence coverage not available
      </div>
    );
  }

  return (
    <div className="mb-6 rounded-md border border-border/70 bg-muted/10 p-4" data-testid="pfmb-sequence-coverage">
      <div className="mb-3">
        <div className="text-xs uppercase tracking-wider text-muted-foreground">PFMB sequence coverage</div>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>N-terminal fragments: b/c (top markers)</span>
          <span>C-terminal fragments: y/z. (bottom markers)</span>
        </div>
      </div>
      <div className="overflow-x-auto pb-2">
        <div className="inline-flex min-w-max items-stretch font-mono text-base leading-none">
          {residues.map((residue, index) => {
            const site = index + 1;
            const info = site <= len - 1 ? sites.get(site) : undefined;
            const highlighted = info ? [...info.families].some((family) => highlight?.has(family)) : false;
            return (
              <Fragment key={`${residue}-${index}`}>
                <div
                  data-testid="seq-residue"
                  data-index={index + 1}
                  title={`Residue ${residue}, index ${index + 1}`}
                  className="min-w-7 rounded-sm px-1 py-4 text-center font-semibold text-foreground hover:bg-muted"
                >
                  {residue}
                </div>
                {site <= len - 1 && (
                  <SiteMarker
                    site={site}
                    info={info}
                    highlighted={highlighted}
                    onClick={info && onHighlight ? () => onHighlight([...info.families]) : undefined}
                  />
                )}
              </Fragment>
            );
          })}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
        {([...N_TERM_SERIES, ...C_TERM_SERIES] as PfmbIonType[]).map((t) => (
          <span key={t} className="inline-flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: PFMB_SERIES_COLOR[t] }} />
            {seriesLabel(t)}
          </span>
        ))}
      </div>
    </div>
  );
}

function SiteMarker({
  site,
  info,
  highlighted,
  onClick,
}: {
  site: number;
  info: SiteInfo | undefined;
  highlighted: boolean;
  onClick?: () => void;
}) {
  const covered = Boolean(info && info.families.size > 0);
  const supportedSeries = info
    ? [...info.nTypes, ...info.cTypes].map(seriesLabel).join(", ")
    : "none";
  const matchedIons = info ? [...info.ionNames].sort().join(", ") : "none";
  return (
    <button
      type="button"
      data-testid="seq-site"
      data-site={site}
      data-covered={covered ? "true" : "false"}
      data-highlighted={highlighted ? "true" : "false"}
      disabled={!covered}
      onClick={onClick}
      aria-label={`Cleavage site ${site}`}
      title={`Cleavage position ${site}; supported ion series: ${supportedSeries}; matched ions: ${matchedIons}`}
      className={cn(
        "relative flex w-3 flex-col justify-between rounded-sm py-1",
        covered ? "cursor-pointer" : "cursor-default",
        highlighted && "bg-primary/15 ring-2 ring-primary ring-offset-1",
      )}
    >
      <span className="flex flex-col gap-px">
        {N_TERM_SERIES.filter((t) => info?.nTypes.has(t)).map((t) => (
          <span key={t} className="h-1 w-full rounded-sm" style={{ backgroundColor: PFMB_SERIES_COLOR[t] }} />
        ))}
      </span>
      <span className="flex flex-col gap-px">
        {C_TERM_SERIES.filter((t) => info?.cTypes.has(t)).map((t) => (
          <span key={t} className="h-1 w-full rounded-sm" style={{ backgroundColor: PFMB_SERIES_COLOR[t] }} />
        ))}
      </span>
    </button>
  );
}
