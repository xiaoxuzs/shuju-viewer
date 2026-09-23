import { useOutletContext, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { DataEmptyState, DataLoadError } from "@/components/common/data-state";
import { PageLoading } from "@/components/common/page-loading";
import { fetchBuProtein } from "@/features/bu-viewer/api/buClient";
import { BuPeptideLinksTable } from "@/features/bu-viewer/components/protein-detail/BuPeptideLinksTable";
import { BuProteinHeader } from "@/features/bu-viewer/components/protein-detail/BuProteinHeader";
import { SequenceCoverage } from "@/features/bu-viewer/components/sequence/SequenceCoverage";
import type { BuDatasetContext } from "@/features/bu-viewer/layout/BuDatasetLayout";

export function BuProteinDetailPage() {
  const { dataset } = useOutletContext<BuDatasetContext>();
  const { proteinId = "" } = useParams();
  const parsedProteinId = Number(proteinId);
  const { data, isLoading, error } = useQuery({
    queryKey: ["bu", dataset.slug, "protein", parsedProteinId],
    queryFn: () => fetchBuProtein(dataset.slug, parsedProteinId),
    enabled: Number.isFinite(parsedProteinId),
  });

  if (!Number.isFinite(parsedProteinId)) return <p className="text-destructive">Invalid protein id.</p>;
  if (isLoading) return <PageLoading />;
  if (error && !data) return <DataLoadError />;
  if (!data) return <DataEmptyState />;

  return (
    <div className="space-y-4">
      <BuProteinHeader slug={dataset.slug} protein={data} />
      <SequenceCoverage protein={data} />
      <BuPeptideLinksTable slug={dataset.slug} protein={data} />
    </div>
  );
}
