import { TransitionLink } from "@/features/page-transition";
import { ArrowRight, FileText, Layers, ListTree } from "lucide-react";
import type { ReactNode } from "react";

import { Stat } from "@/components/common/stat";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { BuOverviewOut } from "@/features/bu/types";
import { formatCount } from "@/features/bu/utils";

export function BuSummaryCards({ overview }: { overview: BuOverviewOut }) {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Matches" value={formatCount(overview.counts.matches)} />
        <Stat label="Peptides" value={formatCount(overview.counts.peptides)} />
        <Stat label="Proteins" value={formatCount(overview.counts.proteins)} />
        <Stat label="Runs" value={formatCount(overview.counts.runs)} />
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <EntryCard
          to={`/datasets/${overview.slug}/proteins`}
          icon={<FileText className="h-4 w-4" />}
          title="Proteins"
          value={overview.counts.proteins}
        />
        <EntryCard
          to={`/datasets/${overview.slug}/peptides`}
          icon={<Layers className="h-4 w-4" />}
          title="Peptides"
          value={overview.counts.peptides}
        />
        <EntryCard
          to={`/datasets/${overview.slug}/matches`}
          icon={<ListTree className="h-4 w-4" />}
          title="Matches"
          value={overview.counts.matches}
        />
      </div>
    </div>
  );
}

function EntryCard({
  to,
  icon,
  title,
  value,
}: {
  to: string;
  icon: ReactNode;
  title: string;
  value: number;
}) {
  return (
    <TransitionLink to={to} className="group">
      <Card className="h-full border-border/50 transition-colors hover:border-primary/40">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            {icon}
            {title}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex items-end justify-between">
          <div className="text-2xl font-semibold">{formatCount(value)}</div>
          <ArrowRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
        </CardContent>
      </Card>
    </TransitionLink>
  );
}
