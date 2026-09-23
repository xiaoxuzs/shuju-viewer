import { useOutletContext, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { DataEmptyState, DataLoadError } from "@/components/common/data-state";
import { PageLoading } from "@/components/common/page-loading";
import { PlotStatus } from "@/components/common/plot-status";
import { fetchBuProtein } from "@/features/bu/api/buClient";
import { BuPeptideLinksTable } from "@/features/bu/components/protein-detail/BuPeptideLinksTable";
import { BuProteinHeader } from "@/features/bu/components/protein-detail/BuProteinHeader";
import { SequenceCoverage } from "@/features/bu/components/sequence/SequenceCoverage";
import type { BuDatasetContext } from "@/features/bu/layout/BuDatasetLayout";
import {
  findDatasetViewCapability,
  useDatasetCapability,
} from "@/features/dataset-capabilities/DatasetCapabilityContext";
import { usePageTransitionReady } from "@/features/page-transition";

export function BuProteinDetailPage() {
  const { dataset } = useOutletContext<BuDatasetContext>();
  const capabilityReport = useDatasetCapability();
  const coverageCapability = findDatasetViewCapability(
    capabilityReport,
    "bu.protein_coverage",
    "protein_coverage",
  );
  const { proteinId = "" } = useParams();
  const parsedProteinId = Number(proteinId);
  const { data, isLoading, error } = useQuery({
    queryKey: ["bu", dataset.slug, dataset.revision_id ?? "legacy", "protein", parsedProteinId],
    queryFn: () => fetchBuProtein(dataset.slug, parsedProteinId),
    enabled: Number.isFinite(parsedProteinId),
  });
  usePageTransitionReady(!isLoading);

  if (!Number.isFinite(parsedProteinId)) return <p className="text-destructive">Invalid protein id.</p>;
  if (isLoading) return <PageLoading />;
  if (error && !data) return <DataLoadError />;
  if (!data) return <DataEmptyState />;

  return (
    <div className="space-y-4">
      <BuProteinHeader slug={dataset.slug} protein={data} />
      {coverageCapability?.availability === "DISABLED" ? (
        <PlotStatus
          kind="unsupported"
          title={coverageCapability.message ?? "Protein sequence coverage is unavailable."}
        />
      ) : (
        <SequenceCoverage protein={data} />
      )}
      <BuPeptideLinksTable slug={dataset.slug} protein={data} />
    </div>
  );
}
