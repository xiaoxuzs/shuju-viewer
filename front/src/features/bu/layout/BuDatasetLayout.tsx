import { Outlet } from "react-router-dom";

import type { DatasetOut } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/common/page-header";
import { cn } from "@/lib/utils";
import { getBuDefaultQMax } from "@/features/bu/utils";
import { TransitionNavLink } from "@/features/page-transition";

export interface BuDatasetContext {
  dataset: DatasetOut;
  defaultQMax?: number;
}

export function BuDatasetLayout({ dataset }: { dataset: DatasetOut }) {
  const defaultQMax = getBuDefaultQMax(dataset);
  const tabs = [
    { to: `/datasets/${dataset.slug}`, label: "Overview", end: true },
    { to: `/datasets/${dataset.slug}/proteins`, label: "Proteins" },
    { to: `/datasets/${dataset.slug}/peptides`, label: "Peptides" },
    { to: `/datasets/${dataset.slug}/matches`, label: "Matches" },
  ];

  return (
    <>
      <PageHeader
        title={dataset.name}
        description={dataset.description ?? "Bottom-Up DIA dataset imported from DIA-NN results."}
        crumbs={[{ label: "Datasets", to: "/datasets" }, { label: dataset.name }]}
        actions={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Badge>Bottom-Up</Badge>
            {dataset.source_software && <Badge variant="outline">{dataset.source_software}</Badge>}
            {dataset.status && <Badge variant="secondary">{dataset.status}</Badge>}
          </div>
        }
      />

      <div className="mb-5 flex flex-wrap gap-2 border-b border-border/60 pb-2">
        {tabs.map((tab) => (
          <TransitionNavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) =>
              cn(
                "rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors",
                "hover:bg-accent hover:text-foreground",
                isActive && "bg-primary/10 text-primary",
              )
            }
          >
            {tab.label}
          </TransitionNavLink>
        ))}
      </div>

      <Outlet context={{ dataset, defaultQMax } satisfies BuDatasetContext} />
    </>
  );
}
