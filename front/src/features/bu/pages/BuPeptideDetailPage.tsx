import { useOutletContext, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Skeleton } from "@/components/ui/skeleton";
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
  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-40" />
        <Skeleton className="h-72" />
      </div>
    );
  }
  if (error) return <p className="text-destructive">{(error as Error).message}</p>;
  if (!data) return null;

  return (
    <div className="space-y-4">
      <BuPeptideHeader peptide={data} />
      <BuPeptideMatchesTable slug={dataset.slug} peptide={data} />
    </div>
  );
}
