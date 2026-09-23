import { Outlet, useLocation } from "react-router-dom";

import type { DatasetOut, DatasetViewCapability } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/common/page-header";
import {
  findDatasetViewCapability,
  useDatasetCapability,
} from "@/features/dataset-capabilities/DatasetCapabilityContext";
import { DatasetCapabilityReportSlot } from "@/features/dataset-capabilities/DatasetCapabilityReportSlot";
import { cn } from "@/lib/utils";
import { formatSourceSoftwareName, getBuDatasetDisplayDescription, getBuDefaultQMax } from "@/features/bu/utils";
import { TransitionNavLink, usePageTransitionReady } from "@/features/page-transition";

export interface BuDatasetContext {
  dataset: DatasetOut;
  defaultQMax?: number;
}

export function BuDatasetLayout({ dataset }: { dataset: DatasetOut }) {
  const location = useLocation();
  const capabilityReport = useDatasetCapability();
  const defaultQMax = getBuDefaultQMax(dataset);
  const tabs = [
    { to: `/datasets/${dataset.slug}`, label: "Overview", end: true },
    { to: `/datasets/${dataset.slug}/proteins`, label: "Proteins", viewIds: ["bu.proteins", "bu_proteins"] },
    { to: `/datasets/${dataset.slug}/peptides`, label: "Peptides", viewIds: ["bu.peptides", "bu_peptides"] },
    { to: `/datasets/${dataset.slug}/matches`, label: "Matches", viewIds: ["bu.matches", "bu_matches"] },
  ];
  const datasetHome = `/datasets/${dataset.slug}`;
  const activeDisabledView = tabs
    .filter((tab) => tab.viewIds && (location.pathname === tab.to || location.pathname.startsWith(`${tab.to}/`)))
    .map((tab) => findDatasetViewCapability(capabilityReport, ...(tab.viewIds ?? [])))
    .find((view) => view?.availability === "DISABLED");
  usePageTransitionReady(Boolean(activeDisabledView));

  return (
    <>
      <PageHeader
        title={dataset.name}
        description={getBuDatasetDisplayDescription(dataset)}
        crumbs={[{ label: "Datasets", to: "/datasets" }, { label: dataset.name }]}
        actions={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Badge>Bottom-Up</Badge>
            {dataset.source_software && <Badge variant="outline">{formatSourceSoftwareName(dataset.source_software)}</Badge>}
            {dataset.status && <Badge variant="secondary">{dataset.status}</Badge>}
          </div>
        }
      />

      {location.pathname === datasetHome && <DatasetCapabilityReportSlot />}

      <div className="mb-5 flex flex-wrap gap-2 border-b border-border/60 pb-2">
        {tabs.map((tab) => {
          const view = tab.viewIds
            ? findDatasetViewCapability(capabilityReport, ...tab.viewIds)
            : null;
          if (view?.availability === "DISABLED") {
            return <DisabledDatasetTab key={tab.to} label={tab.label} view={view} />;
          }
          return (
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
          );
        })}
      </div>

      {activeDisabledView ? (
        <div
          role="status"
          data-testid="disabled-direct-view"
          className="rounded-md border border-destructive/30 bg-destructive/5 p-5 text-sm"
        >
          <div className="font-medium">{activeDisabledView.title} is unavailable.</div>
          <div className="mt-1 text-muted-foreground">
            {activeDisabledView.message ?? "The imported dataset does not satisfy this view's requirements."}
          </div>
          {activeDisabledView.reason_code && (
            <code className="mt-2 block font-mono text-xs text-destructive">
              {activeDisabledView.reason_code}
            </code>
          )}
        </div>
      ) : (
        <Outlet context={{ dataset, defaultQMax } satisfies BuDatasetContext} />
      )}
    </>
  );
}

function DisabledDatasetTab({ label, view }: { label: string; view: DatasetViewCapability }) {
  const descriptionId = `disabled-view-${view.view_id}`;
  return (
    <div className="flex max-w-sm flex-col gap-1" data-testid={`disabled-tab-${view.view_id}`}>
      <button
        type="button"
        disabled
        aria-describedby={descriptionId}
        className="cursor-not-allowed rounded-md bg-muted px-3 py-1.5 text-left text-sm font-medium text-muted-foreground opacity-70"
      >
        {label}
      </button>
      <span id={descriptionId} className="max-w-xs text-xs text-destructive">
        {view.message ?? "This view is unavailable."}
        {view.reason_code && <code className="ml-1 font-mono">({view.reason_code})</code>}
      </span>
    </div>
  );
}
