import { useOutletContext, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { DataEmptyState, DataLoadError } from "@/components/common/data-state";
import { PageLoading } from "@/components/common/page-loading";
import { fetchBuPeptide } from "@/features/bu/api/buClient";
import { BuPeptideHeader } from "@/features/bu/components/peptide-detail/BuPeptideHeader";
import { BuPeptideMatchesTable } from "@/features/bu/components/peptide-detail/BuPeptideMatchesTable";
import type { BuDatasetContext } from "@/features/bu/layout/BuDatasetLayout";

export function BuPeptideDetailPage() {
  const { dataset } = useOutletContext<BuDatasetContext>();
  const { peptideId = "" } = useParams();
  const parsedPeptideId = Number(peptideId);
  const { data, isLoading, error } = useQuery({
    queryKey: ["bu", dataset.slug, "peptide", parsedPeptideId],
    queryFn: () => fetchBuPeptide(dataset.slug, parsedPeptideId),
    enabled: Number.isFinite(parsedPeptideId),
  });

  if (!Number.isFinite(parsedPeptideId)) return <p className="text-destructive">Invalid peptide id.</p>;
  if (isLoading) return <PageLoading />;
  if (error && !data) return <DataLoadError />;
  if (!data) return <DataEmptyState />;

  return (
    <div className="space-y-4">
      <BuPeptideHeader peptide={data} />
      <BuPeptideMatchesTable slug={dataset.slug} peptide={data} />
    </div>
  );
}
